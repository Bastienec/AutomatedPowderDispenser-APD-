#!/usr/bin/env python3
# BEC - November 2025 
#-------------------------------------------------------------------------------
from __future__ import annotations
from typing import Optional, List, Callable
import time

from config import SCALE_CONFIG

# --- zeep / crypto ---
try:
    from zeep import Client, Settings
    from zeep.transports import Transport
except Exception:
    Client = Settings = Transport = None

try:
    from base64 import b64decode
    from cryptography.hazmat.primitives import hashes, padding
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except Exception:
    PBKDF2HMAC = Cipher = None


def _need(modname: str):
    raise RuntimeError(f"Module requis manquant : {modname}. Installe : pip install {modname}")


def _decrypt_session_id(password: str, enc_b64: str, salt_b64: str) -> str:
    """Déchiffre le SessionId renvoyé par OpenSession (AES/ECB + PBKDF2-SHA1/1000)."""
    if PBKDF2HMAC is None:
        _need("cryptography")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=32,
        salt=b64decode(salt_b64),
        iterations=1000,
    )
    key = kdf.derive(password.encode("utf-8"))

    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    dec = decryptor.update(b64decode(enc_b64)) + decryptor.finalize()

    unpad = padding.PKCS7(128).unpadder()
    data = unpad.update(dec) + unpad.finalize()
    return data.decode("utf-8")


class _WMWebService:
    """Backend WebService (XPR/XSR/Q3). Gère Session, Portes, Pesée, Méthodes et Dosing Automation."""
    TNS = "http://MT/Laboratory/Balance/XprXsr/V03"

    def __init__(self, cfg: dict):
        if Client is None:
            _need("zeep")

        scheme   = cfg.get("scheme", "http")
        ip       = cfg.get("ip", "192.168.0.50")
        port     = int(cfg.get("port", 81))
        wsdl     = cfg["wsdl_path"]
        self.password  = cfg["password"]
        self.verify    = cfg.get("verify", False)
        self.timeout_s = int(cfg.get("timeout_s", 8))

        self.door_ids    : List[str] = cfg.get("door_ids") or ["LeftOuter", "RightOuter"]
        self.open_width  : int       = int(cfg.get("open_width", 113))
        self.close_width : int       = int(cfg.get("close_width", 0))

        # Méthode de pesée courante (menu "Methods" sur la balance)
        self._method_name: str = cfg.get("method_name", "General Weighing")

        # Base des endpoints
        self.base = f"{scheme}://{ip}:{port}/MT/Laboratory/Balance/XprXsr/V03/"

        import requests
        self._session = requests.Session()
        self._session.verify = self.verify
        self._transport = Transport(session=self._session, timeout=self.timeout_s)

        self._client = Client(
            wsdl,
            settings=Settings(strict=False, xml_huge_tree=True),
            transport=self._transport,
        )
        ns = f"{{{self.TNS}}}"

        # Services
        self._svc_basic = self._client.create_service(
            ns + "BasicHttpBinding_IBasicService",
            self.base,
        )
        self._svc_dosing = self._client.create_service(
            ns + "BasicHttpBinding_IDosingAutomationService",
            self.base,
        )
        self._svc_draft   = self._client.create_service(
            ns + "BasicHttpBinding_IDraftShieldsService",
            self.base,
        )

        self._svc_notify = self._client.create_service(
            ns + "BasicHttpBinding_INotificationService",
            self.base,
        )

        self._svc_session = self._client.create_service(
            ns + "BasicHttpBinding_ISessionService",
            self.base,
        )

        self._svc_weigh   = self._client.create_service(
            ns + "BasicHttpBinding_IWeighingService",
            self.base,
        )
        self._svc_wtask   = self._client.create_service(
            ns + "BasicHttpBinding_IWeighingTaskService",
            self.base,
        )
        

        self.session_id: Optional[str] = None
        self._task_ready: bool = False

    # --- Session ---
    def _open_session(self):
        resp = self._svc_session.OpenSession()
        enc_id = getattr(resp, "SessionId", None)
        salt   = getattr(resp, "Salt", None)
        if not enc_id or not salt:
            raise RuntimeError("OpenSession: SessionId ou Salt manquant")
        self.session_id = _decrypt_session_id(self.password, enc_id, salt)
        self._task_ready = False

    def _ensure_session(self):
        if not self.session_id:
            self._open_session()

    def connect(self):
        self._ensure_session()

    def close(self):
        # Pas d'API CloseSession dans ce binding → on oublie juste l'ID
        self.session_id = None
        self._task_ready = False

    def is_connected(self) -> bool:
        return bool(self.session_id)

    # --- Portes (DraftShields) ---
    def _set_position_one(self, draft_id: str, width: int):
        req = {
            "SessionId": self.session_id,
            "DraftShieldsPositions": {
                "DraftShieldPosition": [
                    {"DraftShieldId": draft_id, "OpeningWidth": int(width)}
                ]
            },
        }
        return self._svc_draft.SetPosition(**req)

    def _set_all_doors(self, width: int):
        for d in self.door_ids:
            self._set_position_one(d, width)

    def _drive_doors(self, target_width: int, label: str, tol: int = 2) -> str:
        self._ensure_session()

        # 1) tentative directe
        try:
            self._set_all_doors(target_width)
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                self._set_all_doors(target_width)
            else:
                raise
        if self._verify_door(target_width, tol=tol):
            return "OK"

        # 2) Standby profond → wake + retente
        self.wakeup_from_standby()
        self._set_all_doors(target_width)
        if self._verify_door(target_width, tol=tol):
            return "OK (after WakeupFromStandby)"

        # 3) UI assoupie / pile SOAP → petit nudge + retente
        self._poke_display()
        self._set_all_doors(target_width)
        if self._verify_door(target_width, tol=tol):
            return "OK (after nudge)"

        # 4) échec clair
        raise RuntimeError(f"{label}: mouvement non observé (veille/UI/verrouillage ?)")

    def open_door(self) -> str:
        return self._drive_doors(self.open_width, "Open door")

    def close_door(self) -> str:
        return self._drive_doors(self.close_width, "Close door")

    def wakeup_from_standby(self) -> bool:
        """Réveille le *Standby* profond via IBasicService.WakeupFromStandby.
        Retourne True si on n’est plus en Standby après l’appel (ou si service absent)."""
        self._ensure_session()
        try:
            # Service Basic (crée-le une fois dans __init__)
            resp = self._svc_basic.WakeupFromStandby(SessionId=self.session_id)
            # si zeep → getattr, si dict → .get
            is_active = getattr(resp, "IsStandbyActive", None)
            if isinstance(resp, dict):
                is_active = resp.get("IsStandbyActive", is_active)
            return (is_active is False)  # plus en standby
        except Exception:
            # Si service non dispo sur ce firmware, on ne bloque pas.
            return False

    def _poke_display(self):
        """Nudge léger de l’UI via une requête inoffensive."""
        self._ensure_session()
        try:
            _ = self._svc_draft.GetPosition(
                SessionId=self.session_id,
                DraftShieldIds={"DraftShieldIdentifier": list(self.door_ids or [])},
            )
        except Exception:
            # C’est un nudge : on ignore toute erreur ici.
            pass

    # --- Pesée (Zero / Tare / GetWeight) ---
    def zero(self) -> str:
        self._ensure_session()
        try:
            self._svc_weigh.Zero(SessionId=self.session_id, ZeroImmediately=True)
            return "OK"
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                self._svc_weigh.Zero(SessionId=self.session_id, ZeroImmediately=True)
                return "OK"
            raise

    def tare(self) -> str:
        self._ensure_session()
        try:
            self._svc_weigh.Tare(SessionId=self.session_id, TareImmediately=True)
            return "OK"
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                self._svc_weigh.Tare(SessionId=self.session_id, TareImmediately=True)
                return "OK"
            raise

    def get_weight(self) -> float:
        """Retourne le poids net en grammes (fallback sur le brut si pas de net).
        Essaye d'abord 'Stable', puis 'Immediate' si aucun échantillon n'est renvoyé.
        Gère les deux formes de réponse: ValueWithUnit OU Value/Unit.
        """
        self._ensure_session()

        def _call(mode: str):
            return self._svc_weigh.GetWeight(
                SessionId=self.session_id,
                WeighingCaptureMode=mode,  # "Stable" d'abord, puis "Immediate" en fallback
                TimeoutInSeconds=5,
            )

        # 1) Essai en "Stable"
        try:
            resp = _call("Stable")
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                resp = _call("Stable")
            else:
                raise

        # Extraction compatible V03 (WeightSample direct) + fallback conteneur
        def _extract_ws(r):
            ws = getattr(r, "WeightSample", None)
            if ws is None:
                wi = getattr(r, "WeighingInformation", None)
                if wi:
                    ws_container = getattr(wi, "WeightSamples", None)
                    if ws_container:
                        ws = getattr(ws_container, "WeightSample", None)
            return ws

        ws = _extract_ws(resp)

        # 2) Si aucun échantillon → essai "Immediate"
        if ws is None:
            try:
                resp = _call("Immediate")
            except Exception as e:
                if "Session" in str(e):
                    self._open_session()
                    resp = _call("Immediate")
                else:
                    raise
            ws = _extract_ws(resp)

            if ws is None:
                outcome = getattr(resp, "Outcome", None)
                cmdid = getattr(resp, "CommandId", None)
                if outcome and outcome != "Success":
                    raise RuntimeError(f"GetWeight: Outcome={outcome}, CommandId={cmdid}")
                raise RuntimeError("GetWeight: pas de WeightSample dans la réponse")

        # Zeep peut renvoyer une liste ou un objet unique
        sample = ws[-1] if isinstance(ws, list) else ws

        # Helper: supporte Net/Gross sous forme ValueWithUnit OU Value/Unit
        def _vu_from(node):
            if not node:
                return None, None
            vwu = getattr(node, "ValueWithUnit", None)
            if vwu is not None:
                val = getattr(vwu, "Value", None)
                unit = getattr(vwu, "Unit", None)
            else:
                val = getattr(node, "Value", None)
                unit = getattr(node, "Unit", None)
            return val, unit

        # On privilégie NetWeight; sinon GrossWeight
        for field in ("NetWeight", "GrossWeight"):
            wobj = getattr(sample, field, None)
            val_str, unit = _vu_from(wobj)
            if val_str is None or unit is None:
                continue

            try:
                val = float(str(val_str).replace(",", "."))
            except ValueError:
                continue

            u = str(unit).strip().lower()
            if u in ("gram", "g"):
                return val
            if u in ("milligram", "mg"):
                return val / 1000.0
            if u in ("kilogram", "kg"):
                return val * 1000.0

            # Autres unités possibles → à étendre si nécessaire
            raise RuntimeError(f"GetWeight: unité non gérée '{unit}'")

        raise RuntimeError("GetWeight: Net/Gross Weight absent")
    
    def get_weights(self, capture_mode: str = "Immediate", timeout_s: int = 2) -> dict:
        """
        Retourne {'net_g': float|None, 'gross_g': float|None} en grammes.
        Ne lève pas si un des deux manque : met None.
        """
        self._ensure_session()

        def _call(mode: str):
            return self._svc_weigh.GetWeight(
                SessionId=self.session_id,
                WeighingCaptureMode=mode,
                TimeoutInSeconds=int(timeout_s),
            )

        try:
            resp = _call(capture_mode)
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                resp = _call(capture_mode)
            else:
                raise

        def _extract_ws(r):
            ws = getattr(r, "WeightSample", None)
            if ws is None:
                wi = getattr(r, "WeighingInformation", None)
                if wi:
                    ws_container = getattr(wi, "WeightSamples", None)
                    if ws_container:
                        ws = getattr(ws_container, "WeightSample", None)
            return ws

        ws = _extract_ws(resp)
        if ws is None:
            return {"net_g": None, "gross_g": None}

        sample = ws[-1] if isinstance(ws, list) else ws

        def _to_g(node):
            if not node:
                return None
            vwu = getattr(node, "ValueWithUnit", None)
            if vwu is not None:
                val, unit = getattr(vwu, "Value", None), getattr(vwu, "Unit", None)
            else:
                val, unit = getattr(node, "Value", None), getattr(node, "Unit", None)
            if val is None or unit is None:
                return None
            try:
                v = float(str(val).replace(",", "."))
            except Exception:
                return None
            u = str(unit).strip().lower()
            if u in ("g", "gram", "gramme", "grams"):
                return v
            if u in ("mg", "milligram", "milligramme"):
                return v / 1000.0
            if u in ("kg", "kilogram", "kilogramme"):
                return v * 1000.0
            return None

        net_g   = _to_g(getattr(sample, "NetWeight",   None))
        gross_g = _to_g(getattr(sample, "GrossWeight", None))
        return {"net_g": net_g, "gross_g": gross_g}


    def is_pan_empty(self, threshold_mg: float = 9.0, samples: int = 10, sleep_s: float = 0.05) -> tuple[bool, dict]:
        """
        Renvoie (is_empty, stats) ; stats = {'mean_gross_g','std_gross_g','threshold_g','n'}.
        Lit plusieurs fois le GROSS en 'Immediate', moyenne + écart-type, compare au seuil.
        """
        self._ensure_session()
        vals = []
        for _ in range(max(3, int(samples))):
            w = self.get_weights(capture_mode="Immediate", timeout_s=1)
            if w["gross_g"] is not None:
                vals.append(w["gross_g"])
            time.sleep(sleep_s)

        if not vals:
            return (False, {"mean_gross_g": None, "std_gross_g": None, "threshold_g": threshold_mg/1000.0, "n": 0})

        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
        std = var ** 0.5
        threshold_g = max(threshold_mg / 1000.0, 5.0 * std)  # 5σ ou seuil fixe, le plus strict

        return (abs(mean) < threshold_g, {
            "mean_gross_g": mean,
            "std_gross_g": std,
            "threshold_g": threshold_g,
            "n": len(vals),
        })
    
    def is_pan_present(self, min_present_mg: float = 1000.0, samples: int = 10, sleep_s: float = 0.05) -> tuple[bool, dict]:
        """
        Renvoie (has_vial, stats) ; stats = {'mean_gross_g','std_gross_g','threshold_g','n'}.
        Lit plusieurs fois le GROSS en 'Immediate', puis teste mean ≥ min_present_mg.
        """
        self._ensure_session()
        vals = []
        for _ in range(max(3, int(samples))):
            w = self.get_weights(capture_mode="Immediate", timeout_s=1)
            if w["gross_g"] is not None:
                vals.append(w["gross_g"])
            time.sleep(sleep_s)

        if not vals:
            return (False, {"mean_gross_g": None, "std_gross_g": None, "threshold_g": min_present_mg/1000.0, "n": 0})

        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
        std = var ** 0.5
        threshold_g = float(min_present_mg) / 1000.0

        return (mean >= threshold_g, {
            "mean_gross_g": mean,
            "std_gross_g": std,
            "threshold_g": threshold_g,
            "n": len(vals),
        })
    
    def get_door_positions(self) -> dict[str, int]:
        """Retourne les positions actuelles des portes sous forme {DraftShieldId: OpeningWidth}."""
        self._ensure_session()
        return self._draft_positions()

    # --- Helpers internes ---
    def _draft_positions(self) -> dict[str, int]:
        """Retourne {draft_id: opening_width} via IDraftShieldsService.GetPosition (V03).
        Réponse attendue: DraftShieldsInformation -> DraftShieldInformation[].
        """
        if not self.door_ids:
            return {}

        # Requête conforme au squelette SOAP :
        req = {
            "SessionId": self.session_id,
            "DraftShieldIds": {"DraftShieldIdentifier": list(self.door_ids)},
        }
        resp = self._svc_draft.GetPosition(**req)

        # Sérialiser pour avoir un dict propre, quel que soit zeep
        try:
            from zeep.helpers import serialize_object
            sresp = serialize_object(resp)
        except Exception:
            sresp = resp

        # Vérif souple de l’Outcome
        try:
            outcome = (sresp or {}).get("Outcome")
            if outcome and str(outcome) != "Success":
                emsg = (sresp or {}).get("ErrorMessage")
                raise RuntimeError(f"GetPosition Outcome={outcome}, Error={emsg}")
        except Exception:
            pass

        # ----> La bonne arborescence d’après le helper:
        # DraftShieldsInformation -> DraftShieldInformation (liste)
        info = None
        if isinstance(sresp, dict):
            info = sresp.get("DraftShieldsInformation")
        if info is None:
            info = getattr(resp, "DraftShieldsInformation", None)
        if info is None:
            return {}

        items = None
        if isinstance(info, dict):
            items = info.get("DraftShieldInformation")
        if items is None:
            items = getattr(info, "DraftShieldInformation", None)
        if items is None:
            # parfois la liste est déjà plate
            items = info

        if not isinstance(items, (list, tuple)):
            items = [items]

        out: dict[str, int] = {}
        for it in items:
            if it is None:
                continue
            if isinstance(it, dict):
                did = it.get("DraftShieldId")
                w   = it.get("OpeningWidth")
            else:
                did = getattr(it, "DraftShieldId", None)
                w   = getattr(it, "OpeningWidth", None)
            if did is None or w is None:
                continue
            try:
                out[str(did)] = int(w)
            except Exception:
                try:
                    out[str(did)] = int(float(str(w).replace(",", ".")))
                except Exception:
                    pass
        return out

    def _verify_door(self, expect_width: int, tol: int = 2, timeout_s: float = 2.0) -> bool:
        """Poll GetPosition jusqu’à ce que toutes les portes soient ~expect_width (±tol)."""
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            pos = self._draft_positions()
            if pos and all(abs(pos.get(d, -9999) - expect_width) <= tol for d in self.door_ids):
                return True
            time.sleep(0.05)
        return False

    def _unit_to_ws(self, u: str) -> str:
        if not u:
            return "Gram"
        s = str(u).strip().lower()
        if s in ("g", "gram", "gramme", "grams"):
            return "Gram"
        if s in ("mg", "milligram", "milligramme"):
            return "Milligram"
        if s in ("kg", "kilogram", "kilogramme"):
            return "Kilogram"
        if s in ("%", "percent", "pourcent", "percentage"):
            return "Percent"
        return u

    def _safe_get_target_and_tols(self):
        """Lit (target_val, target_unit, tol_plus, tol_minus, tol_unit) via IWeighingTaskService.
        En cas d’indispo (pas de tâche active) → valeurs neutres.
        """
        self._ensure_session()
        try:
            resp = self._svc_wtask.GetTargetValueAndTolerances(SessionId=self.session_id)
        except Exception:
            return None, "Gram", 0.0, 0.0, "Percent"

        def _read(node):
            if not node:
                return None, None
            vwu = getattr(node, "ValueWithUnit", None)
            if vwu is not None:
                v = getattr(vwu, "Value", None)
                u = getattr(vwu, "Unit",  None)
            else:
                v = getattr(node, "Value", None)
                u = getattr(node, "Unit",  None)
            if v is None or u is None:
                return None, None
            try:
                return float(str(v).replace(",", ".")), str(u)
            except Exception:
                return None, str(u)

        t_v,  t_u  = _read(getattr(resp, "TargetWeight",   None))
        up_v, up_u = _read(getattr(resp, "UpperTolerance", None))
        lo_v, lo_u = _read(getattr(resp, "LowerTolerance", None))

        if t_u is None:
            t_u = "Gram"
        tol_u = up_u or lo_u or "Percent"
        return t_v, t_u, (up_v or 0.0), (lo_v or 0.0), tol_u

    def _start_task(self, method_name: str):
        """Appelle IWeighingTaskService.StartTask pour la méthode donnée."""
        self._ensure_session()

        def _do():
            return self._svc_wtask.StartTask(
                SessionId=self.session_id,
                MethodName=method_name,
            )

        try:
            resp = _do()
            self._method_name = method_name
            self._task_ready = True
            return resp
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                resp = _do()
                self._method_name = method_name
                self._task_ready = True
                return resp
            raise

    def _ensure_task_started(self):
        """
        Ne démarre la tâche courante que si nécessaire.
        - Si une tâche est déjà active, on ne touche à rien.
        - On détecte l'état en tentant un GetTargetValueAndTolerances.
        """
        self._ensure_session()

        # Déjà validé une fois dans cette session ?
        if self._task_ready:
            return

        # 1) Probe: si la tâche est active, ce call réussit => rien à faire.
        try:
            _ = self._svc_wtask.GetTargetValueAndTolerances(SessionId=self.session_id)
            self._task_ready = True
            return
        except Exception:
            # On ne sait pas si c'est parce que pas de tâche ou autre → on tente StartTask
            pass

        # 2) Démarrage une seule fois avec la méthode courante
        try:
            self._start_task(self._method_name)
        except Exception:
            # Certains firmwares peuvent déjà avoir une tâche par défaut
            # et lever une erreur non bloquante ici.
            pass

    def set_method(self, method_name: str) -> str:
        """
        Choisit la méthode de pesée (ex: 'General Weighing', 'DOSING').
        Correspond au menu 'Methods' sur l'écran tactile.
        """
        self._task_ready = False
        self._start_task(method_name)
        return "OK"

    def set_target_weight(
        self,
        value: float,
        unit: str = "g",
        tol_plus: float | None = None,
        tol_minus: float | None = None,
        tol_unit: str | None = None,
    ) -> str:
        """Définit la cible et, si fournis, les tolérances (dans la tâche courante)."""
        self._ensure_session()
        self._ensure_task_started()  # ← clé pour ne pas tout casser

        # On conserve les tolérances actuelles si non passées
        cur_t, cur_tu, cur_up, cur_lo, cur_u = self._safe_get_target_and_tols()
        tp = cur_up if tol_plus  is None else float(tol_plus)
        tm = cur_lo if tol_minus is None else float(tol_minus)
        tu = cur_u  if tol_unit  is None else tol_unit

        req = {
            "SessionId": self.session_id,
            "TargetWeight":   {"Value": float(value), "Unit": self._unit_to_ws(unit)},
            "LowerTolerance": {"Value": float(tm),    "Unit": self._unit_to_ws(tu)},
            "UpperTolerance": {"Value": float(tp),    "Unit": self._unit_to_ws(tu)},
        }

        def _do():
            return self._svc_wtask.SetTargetValueAndTolerances(**req)

        try:
            _do()
            return "OK"
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                _do()
                return "OK"
            # message clair en cas de souci firmware
            raise RuntimeError(f"Set target failed: {e}")

    def set_tolerance_upper(self, value: float, unit: str = "%") -> str:
        """Change uniquement +Tol, en conservant target et −Tol actuelles."""
        self._ensure_session()
        self._ensure_task_started()

        t_val, t_unit, cur_up, cur_lo, cur_u = self._safe_get_target_and_tols()
        if t_val is None:
            t_val, t_unit = 0.0, "Gram"

        req = {
            "SessionId": self.session_id,
            "TargetWeight":   {"Value": float(t_val), "Unit": self._unit_to_ws(t_unit)},
            "LowerTolerance": {"Value": float(cur_lo), "Unit": self._unit_to_ws(unit or cur_u or "Percent")},
            "UpperTolerance": {"Value": float(value),  "Unit": self._unit_to_ws(unit or cur_u or "Percent")},
        }

        def _do():
            return self._svc_wtask.SetTargetValueAndTolerances(**req)

        try:
            _do()
            return "OK"
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                _do()
                return "OK"
            raise RuntimeError(f"Set +Tol failed: {e}")

    def set_tolerance_lower(self, value: float, unit: str = "%") -> str:
        """Change uniquement −Tol, en conservant target et +Tol actuelles."""
        self._ensure_session()
        self._ensure_task_started()

        t_val, t_unit, cur_up, cur_lo, cur_u = self._safe_get_target_and_tols()
        if t_val is None:
            t_val, t_unit = 0.0, "Gram"

        req = {
            "SessionId": self.session_id,
            "TargetWeight":   {"Value": float(t_val), "Unit": self._unit_to_ws(t_unit)},
            "LowerTolerance": {"Value": float(value),  "Unit": self._unit_to_ws(unit or cur_u or "Percent")},
            "UpperTolerance": {"Value": float(cur_up), "Unit": self._unit_to_ws(unit or cur_u or "Percent")},
        }

        def _do():
            return self._svc_wtask.SetTargetValueAndTolerances(**req)

        try:
            _do()
            return "OK"
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                _do()
                return "OK"
            raise RuntimeError(f"Set −Tol failed: {e}")

    # --- Dosing Automation : démarrage job list ---
    def start_dosing_job(
        self,
        vial_name: str,
        substance_name: str,
        target_value: float,
        target_unit: str = "mg",
        lower_tol_value: float | None = None,
        upper_tol_value: float | None = None,
        tol_unit: str | None = None,
    ) -> dict:
        """
        Lance un DosingJobList avec un seul job via IDosingAutomationService.
        - Nécessite qu'une méthode de dosing automatisé soit en cours (ex: 'DOSING').
        """
        self._ensure_session()

        # S'assurer qu'on est bien dans la bonne méthode (DOSING)
        if not self._method_name or self._method_name.strip().lower() != "dosing":
            try:
                self._start_task("Dosing")
            except Exception as e:
                raise RuntimeError(
                    f"Impossible de démarrer la méthode 'Dosing' avant le job de dosage: {e}"
                )

        tu = self._unit_to_ws(target_unit)
        tol_u = self._unit_to_ws(tol_unit or target_unit)

        if lower_tol_value is None:
            lower_tol_value = 0.0
        if upper_tol_value is None:
            upper_tol_value = 0.0

        job = {
            "VialName": vial_name,
            "SubstanceName": substance_name,
            "TargetWeight": {
                "Value": float(target_value),
                "Unit": tu,
            },
            "LowerTolerance": {
                "Value": float(lower_tol_value),
                "Unit": tol_u,
            },
            "UpperTolerance": {
                "Value": float(upper_tol_value),
                "Unit": tol_u,
            },
        }

        req = {
            "SessionId": self.session_id,
            "DosingJobList": {
                "DosingJob": [job]
            },
        }

        def _do():
            return self._svc_dosing.StartExecuteDosingJobListAsync(**req)

        try:
            resp = _do()
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                resp = _do()
            else:
                raise

        outcome   = getattr(resp, "Outcome", None)
        cmd_id    = getattr(resp, "CommandId", None)
        err_msg   = getattr(resp, "ErrorMessage", None)
        start_err = getattr(resp, "StartDosingJobListError", None)
        job_errs  = getattr(resp, "JobErrors", None)

        return {
            "Outcome": str(outcome) if outcome is not None else None,
            "CommandId": cmd_id,
            "ErrorMessage": err_msg,
            "StartDosingJobListError": str(start_err) if start_err is not None else None,
            "JobErrors": job_errs,
        }

    # --- Dosing Automation : Read / Write Dosing Head ---
    def read_dosing_head_name(self) -> str:
        """
        Lit la substance du dosing head en place via ReadDosingHead
        et retourne DosingHeadInfo.SubstanceName (ou chaîne vide si absent).
        """
        self._ensure_session()

        try:
            resp = self._svc_dosing.ReadDosingHead(SessionId=self.session_id)
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                resp = self._svc_dosing.ReadDosingHead(SessionId=self.session_id)
            else:
                raise

        # resp ressemble à :
        # {
        #   'Outcome': 'Success',
        #   'ErrorMessage': None,
        #   'HeadType': 'Powder',
        #   'HeadTypeName': 'QH008-BNMW',
        #   'HeadId': '238248102153',
        #   'DosingHeadInfo': {
        #       'SubstanceName': 'NAHCO3',
        #       ...
        #   }
        # }
        if isinstance(resp, dict):
            dhi = resp.get("DosingHeadInfo") or {}
            substance = dhi.get("SubstanceName")
        else:
            dhi = getattr(resp, "DosingHeadInfo", None)
            substance = getattr(dhi, "SubstanceName", None) if dhi is not None else None

        if not substance:
            return ""
        return str(substance)

    def write_dosing_head_name(self, name: str) -> str:
        """
        Écrit uniquement le champ DosingHeadInfo.SubstanceName dans le dosing head
        en place via WriteDosingHead.

        On lit d'abord la tête actuelle pour récupérer HeadType et HeadId.
        Les autres champs de DosingHeadInfo ne sont pas explicitement remis,
        donc le firmware peut les réinitialiser selon son implémentation.
        """
        self._ensure_session()

        # On relit la tête pour récupérer HeadType / HeadId
        try:
            cur = self._svc_dosing.ReadDosingHead(SessionId=self.session_id)
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                cur = self._svc_dosing.ReadDosingHead(SessionId=self.session_id)
            else:
                raise

        if isinstance(cur, dict):
            head_type = cur.get("HeadType")
            head_id   = cur.get("HeadId")
        else:
            head_type = getattr(cur, "HeadType", None)
            head_id   = getattr(cur, "HeadId", None)

        if not head_type:
            raise RuntimeError("WriteDosingHead: HeadType introuvable dans ReadDosingHead")

        req = {
            "SessionId": self.session_id,
            "HeadType": head_type,
            "DosingHeadInfo": {
                "SubstanceName": str(name),
            },
        }
        if head_id:
            req["HeadId"] = head_id

        def _do():
            return self._svc_dosing.WriteDosingHead(**req)

        try:
            resp = _do()
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                resp = _do()
            else:
                raise RuntimeError(f"WriteDosingHead failed: {e}")

        outcome = getattr(resp, "Outcome", None) if not isinstance(resp, dict) else resp.get("Outcome")

        if outcome is not None and str(outcome) != "Success":
            raise RuntimeError(f"WriteDosingHead Outcome={outcome}")

        return "OK"

    # --- Dosing Automation : confirmation d'actions ---
    def confirm_dosing_action(self, action: str, action_item: str | None = None) -> dict:
        """
        Confirme l'exécution d'une action de dosing via
        IDosingAutomationService.ConfirmDosingJobAction.

        - action: valeur du DosingJobActionType (ex: 'PlaceVial', 'RemoveVial',
                  'PlaceDosingHead', 'RemoveDosingHead').
        - action_item: pour PlaceDosingHead → 'SubstanceName',
                       pour PlaceVial     → 'VialName',
                       sinon chaîne vide ou None.
        """
        self._ensure_session()

        req = {
            "SessionId": self.session_id,
            "ExecutedDosingJobAction": str(action),
            "ActionItem": action_item or "",
        }

        def _do():
            return self._svc_dosing.ConfirmDosingJobAction(**req)

        try:
            resp = _do()
        except Exception as e:
            if "Session" in str(e):
                self._open_session()
                resp = _do()
            else:
                raise

        outcome = getattr(resp, "Outcome", None)
        err_msg = getattr(resp, "ErrorMessage", None)

        return {
            "Outcome": str(outcome) if outcome is not None else None,
            "ErrorMessage": err_msg,
        }

    # --- Dosing Automation : polling des notifications + auto-confirm ---
    def _extract_notifications(self, resp) -> list:
        """
        Extrait une liste d'objets "notification" à partir de la réponse GetNotifications.
        """
        if resp is None:
            return []

        cand = getattr(resp, "Notifications", None)
        if cand is None:
            return []

        # Cas zeep-objets : attribut _value_1
        v1 = getattr(cand, "_value_1", None)
        if v1 is not None:
            if isinstance(v1, (list, tuple)):
                return list(v1)
            return [v1]

        # Cas déjà "dict"
        if isinstance(cand, dict):
            inner = cand.get("_value_1") or cand.get("Notification") or cand.get("Notifications")
            if inner is None:
                return []
            if isinstance(inner, (list, tuple)):
                return list(inner)
            return [inner]

        # Fallback
        inner = getattr(cand, "Notification", None)
        if inner is None:
            return [cand]
        if isinstance(inner, (list, tuple)):
            return list(inner)
        return [inner]

    def auto_confirm_dosing_notifications(
        self,
        log_cb: Callable[[str], None] | None = None,
        long_poll_s: int = 10,
        verbose: bool = False,
        stop_event: "threading.Event | None" = None,  # <<< ajouté
    ) -> None:  
        """
        Boucle bloquante qui appelle INotificationService.GetNotifications en long-polling,
        et auto-confirme toutes les DosingAutomationAction... qu'elle voit.

        - log_cb: callback(str) pour logger dans l'UI (optionnel).
        - long_poll_s: timeout pour GetNotifications (en secondes).
        - verbose: si True, log détaillé (debug). Sinon, seulement les événements importants.
        - stop_event: si fourni et set() -> on quitte proprement la boucle.
        """
        self._ensure_session()

        def log(msg: str, force: bool = False):
            """force=True => log même si verbose=False (événements importants)."""
            if not verbose and not force:
                return
            if log_cb:
                log_cb(msg)
            else:
                print(msg)

        # Message de démarrage : on le force
        log("Démarrage auto_confirm_dosing_notifications()", force=True)

        while True:
            if stop_event is not None and stop_event.is_set():
                log("Stop demandé → sortie du polling de notifications.", force=True)
                return
            try:
                log(
                    f"Appel GetNotifications(SessionId={self.session_id}, Timeout={long_poll_s}s)...",
                    force=False,
                )
                resp = self._svc_notify.GetNotifications(
                    SessionId=self.session_id,
                    LongPollingTimeout=int(long_poll_s),
                )
                log(f"Réponse brute GetNotifications: {repr(resp)}", force=False)
            except Exception as e:
                # Erreur importante → toujours loggée
                log(f"ERREUR GetNotifications: {e}", force=True)
                if "Session" in str(e):
                    log("→ tentative de réouverture de session", force=True)
                    self._open_session()
                    continue
                # autre erreur → on sort pour ne pas tourner en boucle silencieuse
                return

            notifs = self._extract_notifications(resp)
            # Nombre de notifs : log seulement si verbose ou s'il y en a (>0)
            if notifs:
                log(f"Nombre de notifications extraites: {len(notifs)}", force=not verbose)
            else:
                log("Nombre de notifications extraites: 0", force=False)

            if not notifs:
                # Rien de spécial, on repart pour un tour
                continue

            for n in notifs:
                if n is None:
                    continue

                # --- CAS 1 : dict ---
                if isinstance(n, dict):
                    log(f"Notification reçue (dict): keys={list(n.keys())}", force=False)
                    try:
                        log(f"  Contenu notif: {repr(n)}", force=False)
                    except Exception:
                        pass

                    # 1.a) Action de dosing à confirmer
                    if "DosingAutomationActionAsyncNotification" in n:
                        notif = n["DosingAutomationActionAsyncNotification"]

                        # notif peut être un dict OU un objet zeep
                        if isinstance(notif, dict):
                            action = (
                                notif.get("DosingJobActionType")
                                or notif.get("RequestedDosingJobAction")
                                or notif.get("ExecutedDosingJobAction")
                            )
                            item = notif.get("ActionItem")
                        else:
                            # objet zeep : on passe par getattr
                            action = (
                                getattr(notif, "DosingJobActionType", None)
                                or getattr(notif, "RequestedDosingJobAction", None)
                                or getattr(notif, "ExecutedDosingJobAction", None)
                            )
                            item = getattr(notif, "ActionItem", None)

                        # Ligne importante : toujours loggée
                        log(f"Dosing action: {action} / {item}", force=True)

                        if not action:
                            log("  Impossible de déterminer l'action → ignorée.", force=False)
                            continue

                        conf = self.confirm_dosing_action(str(action), item)
                        log(f"  ConfirmDosingJobAction → {conf}", force=False)
                        continue

                    # 1.b) Job terminé (résultat d'un job individuel)
                    if "DosingAutomationJobFinishedAsyncNotification" in n:
                        jn = n["DosingAutomationJobFinishedAsyncNotification"]

                        # dict ou objet zeep ?
                        if isinstance(jn, dict):
                            outcome = jn.get("Outcome")
                            dres = jn.get("DosingResult") or {}
                            job_info = dres.get("DosingJob") or {}
                            ws = dres.get("WeightSample") or {}

                            target = job_info.get("TargetWeight") or {}
                            net    = ws.get("NetWeight") or {}

                            lo_tol = job_info.get("LowerTolerance") or {}
                            up_tol = job_info.get("UpperTolerance") or {}

                            target_val  = target.get("Value")
                            target_unit = target.get("Unit")
                            net_val     = net.get("Value")
                            net_unit    = net.get("Unit")

                            lo_val  = lo_tol.get("Value")
                            lo_unit = lo_tol.get("Unit")
                            up_val  = up_tol.get("Value")
                            up_unit = up_tol.get("Unit")
                        else:
                            outcome = getattr(jn, "Outcome", None)
                            dres = getattr(jn, "DosingResult", None)
                            job_info = getattr(dres, "DosingJob", None) if dres else None
                            ws = getattr(dres, "WeightSample", None) if dres else None

                            target = getattr(job_info, "TargetWeight", None) if job_info else None
                            net    = getattr(ws, "NetWeight", None) if ws else None
                            lo_tol = getattr(job_info, "LowerTolerance", None) if job_info else None
                            up_tol = getattr(job_info, "UpperTolerance", None) if job_info else None

                            target_val  = getattr(target, "Value", None) if target else None
                            target_unit = getattr(target, "Unit", None) if target else None
                            net_val     = getattr(net, "Value", None) if net else None
                            net_unit    = getattr(net, "Unit", None) if net else None

                            lo_val  = getattr(lo_tol, "Value", None) if lo_tol else None
                            lo_unit = getattr(lo_tol, "Unit", None) if lo_tol else None
                            up_val  = getattr(up_tol, "Value", None) if up_tol else None
                            up_unit = getattr(up_tol, "Unit", None) if up_tol else None

                        # Petit calcul "dans / hors tolérance" si tout est cohérent
                        within = None
                        try:
                            if (
                                target_val is not None and net_val is not None
                                and lo_val is not None and up_val is not None
                                and target_unit == net_unit == lo_unit == up_unit
                            ):
                                t = float(str(target_val).replace(",", "."))
                                n = float(str(net_val).replace(",", "."))
                                lo = float(str(lo_val).replace(",", "."))
                                up = float(str(up_val).replace(",", "."))
                                diff = n - t
                                within = (-lo <= diff <= up)
                        except Exception:
                            within = None

                        # Résumé important → toujours loggé
                        log("Job de dosing terminé :", force=True)
                        log(f"  Outcome job    = {outcome}", force=True)
                        log(f"  Cible          = {target_val} {target_unit}", force=True)
                        log(f"  Net mesuré     = {net_val} {net_unit}", force=True)
                        log(f"  Tolérance      = -{lo_val} {lo_unit} / +{up_val} {up_unit}", force=True)

                        if within is not None:
                            log(
                                "  → Résultat     = OK (dans tolérance)"
                                if within else
                                "  → Résultat     = HORS tolérance",
                                force=True,
                            )

                        continue


                    # 1.c) Fin de toute la job list
                    if "DosingAutomationFinishedAsyncNotification" in n:
                        log(
                            "Notification de fin de DosingAutomation → sortie de la boucle.",
                            force=True,
                        )
                        return

                    # 1.d) Autres notifs → log only si verbose
                    log("  Notification ignorée (dict, pas une action de dosing ni un finish).", force=False)
                    continue

                # --- CAS 2 : objet zeep "classique" ---
                cls = type(n).__name__
                log(f"Notification reçue: {cls}", force=False)
                try:
                    log(f"  Contenu notif: {repr(n)}", force=False)
                except Exception:
                    pass

                if "DosingAutomationAction" in cls:
                    action = (
                        getattr(n, "DosingJobActionType", None)
                        or getattr(n, "RequestedDosingJobAction", None)
                        or getattr(n, "ExecutedDosingJobAction", None)
                    )
                    item = getattr(n, "ActionItem", None)
                    log(f"Dosing action (obj): {action} / {item}", force=True)
                    if not action:
                        log("  Impossible de déterminer l'action (obj) → ignorée.", force=False)
                        continue
                    conf = self.confirm_dosing_action(str(action), item)
                    log(f"  ConfirmDosingJobAction → {conf}", force=False)

                elif "DosingAutomationJobFinished" in cls:
                    outcome = getattr(n, "Outcome", None)
                    dres = getattr(n, "DosingResult", None)
                    job_info = getattr(dres, "DosingJob", None) if dres else None
                    ws = getattr(dres, "WeightSample", None) if dres else None

                    target = getattr(job_info, "TargetWeight", None) if job_info else None
                    net    = getattr(ws, "NetWeight", None) if ws else None
                    lo_tol = getattr(job_info, "LowerTolerance", None) if job_info else None
                    up_tol = getattr(job_info, "UpperTolerance", None) if job_info else None

                    target_val  = getattr(target, "Value", None) if target else None
                    target_unit = getattr(target, "Unit", None) if target else None
                    net_val     = getattr(net, "Value", None) if net else None
                    net_unit    = getattr(net, "Unit", None) if net else None

                    lo_val  = getattr(lo_tol, "Value", None) if lo_tol else None
                    lo_unit = getattr(lo_tol, "Unit", None) if lo_tol else None
                    up_val  = getattr(up_tol, "Value", None) if up_tol else None
                    up_unit = getattr(up_tol, "Unit", None) if up_tol else None

                    within = None
                    try:
                        if (
                            target_val is not None and net_val is not None
                            and lo_val is not None and up_val is not None
                            and target_unit == net_unit == lo_unit == up_unit
                        ):
                            t = float(str(target_val).replace(",", "."))
                            n = float(str(net_val).replace(",", "."))
                            lo = float(str(lo_val).replace(",", "."))
                            up = float(str(up_val).replace(",", "."))
                            diff = n - t
                            within = (-lo <= diff <= up)
                    except Exception:
                        within = None

                    log("Job de dosing terminé (obj) :", force=True)
                    log(f"  Outcome job    = {outcome}", force=True)
                    log(f"  Cible          = {target_val} {target_unit}", force=True)
                    log(f"  Net mesuré     = {net_val} {net_unit}", force=True)
                    log(f"  Tolérance      = -{lo_val} {lo_unit} / +{up_val} {up_unit}", force=True)

                    if within is not None:
                        log(
                            "  → Résultat     = OK (dans tolérance)"
                            if within else
                            "  → Résultat     = HORS tolérance",
                            force=True,
                        )

                elif "DosingAutomationFinished" in cls:
                    log(
                        "Notification de fin de DosingAutomation (obj) → sortie de la boucle.",
                        force=True,
                    )
                    return

                else:
                    log("  Notification ignorée (obj, pas une action, pas un finish).", force=False)


# --- Façade utilisée par WinBalance ---
class WM:
    def __init__(self, **override):
        cfg = dict(SCALE_CONFIG)
        cfg.update(override)
        self._impl = _WMWebService(cfg)

    def connect(self): return self._impl.connect()
    def close(self):   return self._impl.close()

    def is_connected(self): return self._impl.is_connected()

    def open_door(self):    return self._impl.open_door()
    def close_door(self):   return self._impl.close_door()
    def wakeup_from_standby(self): return self._impl.wakeup_from_standby()

    def zero(self):         return self._impl.zero()
    def tare(self):         return self._impl.tare()
    def get_weight(self):   return self._impl.get_weight()

    def set_method(self, name: str):          return self._impl.set_method(name)
    def set_target_weight(self, *a, **k):     return self._impl.set_target_weight(*a, **k)
    def set_tolerance_upper(self, *a, **k):   return self._impl.set_tolerance_upper(*a, **k)
    def set_tolerance_lower(self, *a, **k):   return self._impl.set_tolerance_lower(*a, **k)

    def start_dosing_job(self, *a, **k):      return self._impl.start_dosing_job(*a, **k)
    def confirm_dosing_action(self, *a, **k): return self._impl.confirm_dosing_action(*a, **k)
    def auto_confirm_dosing_notifications(self, *a, **k):
        return self._impl.auto_confirm_dosing_notifications(*a, **k)

    # Dosing head high-level API
    def get_dosing_head_name(self) -> str: return self._impl.read_dosing_head_name()

    def set_dosing_head_name(self, name: str) -> str: return self._impl.write_dosing_head_name(name)
    
    def get_door_positions(self) -> dict[str, int]: return self._impl.get_door_positions()
    
    def get_weights(self, *a, **k):     return self._impl.get_weights(*a, **k)
    def is_pan_empty(self, *a, **k):    return self._impl.is_pan_empty(*a, **k)
    def is_pan_present(self, *a, **k):  return self._impl.is_pan_present(*a, **k)
