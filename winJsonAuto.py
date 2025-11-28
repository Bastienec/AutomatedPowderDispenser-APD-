#!/usr/bin/env python3

# BEC - November 2025
# Mode JSON Auto : exécute un plan venant d'un fichier JSON
#   - pour chaque vial : P1 (aller chercher la vial) puis, pour chaque poudre :
#       P2 (aller chercher le dispenser) → dosing job → P3 (ramener le dispenser)
#   - à la fin des poudres de la vial : P4 (ramener la vial)
#-------------------------------------------------------------------------------
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import time

AUTO_POLL_MS = 800  # période de sondage (ms) pour UR3 / dosing


class WinJsonAuto(tk.Frame):
    def __init__(
        self,
        parent,
        info_win,
        devices,
        robot_win=None,
        balance_win=None,
        on_select_vial=None,
        on_select_powder=None,
        on_prepare_dosing=None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.win_info = info_win
        self.devices = devices

        # Références vers les vues "Manuel"
        self.robot_win = robot_win
        self.balance_win = balance_win

        # Callbacks fournis par winMode (voir win.py)
        self.cb_select_vial = on_select_vial
        self.cb_select_powder = on_select_powder
        self.cb_prepare_dosing = on_prepare_dosing

        # Plan JSON courant
        self.plan = []   # liste de dict: {"vial_id": str, "powders":[{"name":str,"qty_mg":float}, ...]}
        self.plan_path = None

        # Index courant dans le plan
        self.cur_vial_idx = 0
        self.cur_powder_idx = 0

        # Etat de la séquence
        self._running = False
        self._waiting_for = None      # None / "program" / "dosing"
        self._current_phase = None    # pour log: "P1" / "P2" / "DOSING" / "P3" / "P4"
        self._after_id = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)

        title = tk.Label(
            self,
            text="Mode JSON Auto : exécution de plans vials/poudres depuis un fichier .json",
            font=("TkDefaultFont", 10, "bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=(5, 2))

        # Ligne 1 : bouton charger + label chemin
        btn_load = tk.Button(
            self,
            text="Charger JSON…",
            width=18,
            command=self.on_load_json,
        )
        btn_load.grid(row=1, column=0, sticky="w", padx=5, pady=5)

        self.lbl_plan = tk.Label(self, text="Aucun plan chargé.", anchor="w", justify="left")
        self.lbl_plan.grid(row=1, column=1, sticky="ew", padx=5, pady=5)

        # Ligne 2 : bouton lancer
        self.btn_run = tk.Button(
            self,
            text="Lancer plan JSON",
            width=18,
            command=self.on_start_plan,
            state="disabled",
        )
        self.btn_run.grid(row=2, column=0, sticky="w", padx=5, pady=(0, 5))

        self.lbl_status = tk.Label(self, text="", anchor="w", justify="left")
        self.lbl_status.grid(row=2, column=1, sticky="ew", padx=5, pady=(0, 5))

    # ------------------------------------------------------------------
    # Helpers log / status
    # ------------------------------------------------------------------
    def _log(self, msg, level="info"):
        try:
            self.win_info.add(msg, level=level)
        except Exception:
            print(msg)
        try:
            self.lbl_status.configure(text=msg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Chargement du JSON
    # ------------------------------------------------------------------
    def on_load_json(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Choisir un plan JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Erreur JSON", f"Impossible de lire le fichier:\n{e}")
            return

        plan = self._parse_plan(data)
        if not plan:
            messagebox.showerror("Plan vide", "Le fichier JSON ne contient aucun vial/poudre valide.")
            return

        self.plan = plan
        self.plan_path = path
        self.cur_vial_idx = 0
        self.cur_powder_idx = 0

        # Texte récap
        lines = [f"Plan: {len(plan)} vial(s)"]
        for v in plan:
            powders_desc = ", ".join(f"{p['name']} {p['qty_mg']} mg" for p in v["powders"])
            lines.append(f"  - {v['vial_id']}: {powders_desc}")
        self.lbl_plan.configure(text="\n".join(lines))

        self._log(f"Mode JSON: plan chargé depuis {path}.")
        self.btn_run.configure(state="normal")

    def _parse_plan(self, data):
        """Transforme le dict JSON brut en une liste normalisée pour l'automate."""
        vials_src = data.get("vials") if isinstance(data, dict) else None
        if not isinstance(vials_src, list):
            return []

        plan = []
        for v in vials_src:
            if not isinstance(v, dict):
                continue
            vial_id = (v.get("vial_id") or v.get("name") or v.get("vial") or "").strip()
            if not vial_id:
                continue
            powders_src = v.get("powders") or []
            powders = []
            for p in powders_src:
                if not isinstance(p, dict):
                    continue
                name = (p.get("name") or "").strip()
                try:
                    qty = float(p.get("qty_mg", 0.0))
                except Exception:
                    continue
                if not name or qty <= 0:
                    continue
                powders.append({"name": name, "qty_mg": qty})
            if not powders:
                continue
            plan.append({"vial_id": vial_id, "powders": powders})
        return plan

    # ------------------------------------------------------------------
    # Helpers connexion auto UR3 / balance
    # ------------------------------------------------------------------
    def _ensure_ur3_connected(self):
        arm = self.devices.get("ur3")
        if arm and getattr(arm, "is_connected", lambda: False)():
            return True

        if not self.robot_win:
            self._log("Mode JSON: WinRobotArm indisponible (robot_win=None).", level="error")
            return False

        self._log("Mode JSON: tentative de connexion automatique UR3…", level="info")
        try:
            self.robot_win.on_connect()
        except Exception as e:
            self._log(f"Mode JSON: échec on_connect() UR3: {e}", level="error")
            return False

        arm = self.devices.get("ur3")
        if not (arm and getattr(arm, "is_connected", lambda: False)()):
            self._log("Mode JSON: UR3 toujours non connecté après on_connect().", level="error")
            return False

        self._log("Mode JSON: UR3 connecté automatiquement.", level="info")
        return True

    def _ensure_scale_connected(self):
        wm = self.devices.get("scale")
        if wm and getattr(wm, "is_connected", lambda: False)():
            return True

        if not self.balance_win:
            self._log("Mode JSON: WinBalance indisponible (balance_win=None).", level="error")
            return False

        self._log("Mode JSON: tentative de connexion automatique balance…", level="info")
        try:
            self.balance_win.on_connect()
        except Exception as e:
            self._log(f"Mode JSON: échec on_connect() balance: {e}", level="error")
            return False

        wm = self.devices.get("scale")
        if not (wm and getattr(wm, "is_connected", lambda: False)()):
            self._log("Mode JSON: balance toujours non connectée après on_connect().", level="error")
            return False

        self._log("Mode JSON: balance connectée automatiquement.", level="info")
        return True

    # ------------------------------------------------------------------
    # Entrée de la séquence JSON
    # ------------------------------------------------------------------
    def on_start_plan(self):
        if self._running:
            self._log("Mode JSON: un plan est déjà en cours.", level="warning")
            return
        if not self.plan:
            self._log("Mode JSON: aucun plan chargé.", level="warning")
            return

        if not self._ensure_ur3_connected():
            return
        if not self._ensure_scale_connected():
            return
        if not self.robot_win or not self.balance_win:
            self._log("Mode JSON: vues manuelles robot/balance manquantes.", level="error")
            return

        self._running = True
        self._waiting_for = None
        self._current_phase = None
        self.cur_vial_idx = 0
        self.cur_powder_idx = 0

        self.btn_run.configure(state="disabled")
        self._log("Mode JSON: démarrage du plan JSON.")
        self._start_vial_p1()

    # ------------------------------------------------------------------
    # Gestion arrêt / fin
    # ------------------------------------------------------------------
    def _abort(self, reason):
        if not self._running:
            return
        self._running = False
        self._waiting_for = None
        self._current_phase = None
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self.btn_run.configure(state="normal")
        self._log(f"Mode JSON: séquence interrompue. {reason}", level="error")

    def _finish(self):
        if not self._running:
            return
        self._running = False
        self._waiting_for = None
        self._current_phase = None
        self._after_id = None
        self.btn_run.configure(state="normal")
        self._log("Mode JSON: plan terminé pour toutes les vials.", level="info")

    # ------------------------------------------------------------------
    # Étapes du plan (P1 / P2+dosing+P3 / P4)
    # ------------------------------------------------------------------
    def _get_current_vial(self):
        if 0 <= self.cur_vial_idx < len(self.plan):
            return self.plan[self.cur_vial_idx]
        return None

    def _get_current_powder(self):
        vial = self._get_current_vial()
        if not vial:
            return None
        powders = vial.get("powders") or []
        if 0 <= self.cur_powder_idx < len(powders):
            return powders[self.cur_powder_idx]
        return None

    # --- P1 : aller chercher la vial (une seule fois par vial) ---
    def _start_vial_p1(self):
        if not self._running:
            return
        vial = self._get_current_vial()
        if not vial:
            self._finish()
            return

        vial_id = vial["vial_id"]
        # 1) sélectionner la vial dans l'UI (onglet Man)
        if self.cb_select_vial:
            try:
                self.cb_select_vial(vial_id)
            except Exception as e:
                self._abort(f"Impossible de sélectionner la vial {vial_id}: {e}")
                return

        self._log(f"Mode JSON: P1 pour vial {vial_id}.", level="info")
        self._start_program_with_helper("P1Bastien.urp", "P1", getattr(self.robot_win, "_play_p1", None), on_done=self._after_p1)

    def _after_p1(self):
        """Appelé quand P1 est terminé pour la vial courante."""
        if not self._running:
            return
        self.cur_powder_idx = 0
        self._start_powder_cycle()

    # --- Pour chaque poudre : P2 → dosing → P3 ---
    def _start_powder_cycle(self):
        if not self._running:
            return
        vial = self._get_current_vial()
        powder = self._get_current_powder()
        if not vial or not powder:
            # plus de poudre pour cette vial → passer à P4
            self._start_vial_p4()
            return

        vial_id = vial["vial_id"]
        powder_name = powder["name"]
        qty_mg = powder["qty_mg"]

        # 1) choisir le dispenser (storage) pour cette poudre
        if self.cb_select_powder:
            try:
                self.cb_select_powder(vial_id, powder_name)
            except Exception as e:
                self._abort(f"Impossible de sélectionner le dispenser pour {powder_name}: {e}")
                return

        self._log(f"Mode JSON: P2 pour vial {vial_id}, poudre {powder_name}.", level="info")
        self._start_program_with_helper("P2Bastien.urp", "P2", getattr(self.robot_win, "_play_p2", None),
                                        on_done=self._after_p2_for_powder)

    def _after_p2_for_powder(self):
        if not self._running:
            return
        vial = self._get_current_vial()
        powder = self._get_current_powder()
        if not vial or not powder:
            self._start_vial_p4()
            return

        vial_id = vial["vial_id"]
        powder_name = powder["name"]
        qty_mg = powder["qty_mg"]

        # Préparer le job de dosing (champ target, substance, etc.)
        if self.cb_prepare_dosing:
            try:
                self.cb_prepare_dosing(vial_id, powder_name, qty_mg)
            except Exception as e:
                self._abort(f"Préparation dosing impossible ({powder_name} {qty_mg} mg): {e}")
                return

        # Lancer dosing
        self._log(f"Mode JSON: dosing {powder_name} ({qty_mg} mg) sur {vial_id}.", level="info")
        self._start_dosing(on_done=self._after_dosing_for_powder)

    def _after_dosing_for_powder(self):
        if not self._running:
            return
        vial = self._get_current_vial()
        powder = self._get_current_powder()
        if not vial or not powder:
            self._start_vial_p4()
            return

        vial_id = vial["vial_id"]
        powder_name = powder["name"]

        self._log(f"Mode JSON: P3 pour vial {vial_id}, poudre {powder_name}.", level="info")
        self._start_program_with_helper("P3Bastien.urp", "P3", getattr(self.robot_win, "_play_p3", None),
                                        on_done=self._after_p3_for_powder)

    def _after_p3_for_powder(self):
        if not self._running:
            return
        vial = self._get_current_vial()
        if not vial:
            self._finish()
            return

        # poudre suivante pour cette vial ?
        self.cur_powder_idx += 1
        if self._get_current_powder() is not None:
            self._start_powder_cycle()
        else:
            # plus de poudres pour cette vial → P4
            self._start_vial_p4()

    # --- P4 : ramener la vial (une fois par vial) ---
    def _start_vial_p4(self):
        if not self._running:
            return
        vial = self._get_current_vial()
        if not vial:
            self._finish()
            return

        vial_id = vial["vial_id"]
        self._log(f"Mode JSON: P4 pour vial {vial_id}.", level="info")
        self._start_program_with_helper("P4Bastien.urp", "P4", getattr(self.robot_win, "_play_p4", None),
                                        on_done=self._after_p4)

    def _after_p4(self):
        if not self._running:
            return

        # vial suivante ?
        self.cur_vial_idx += 1
        self.cur_powder_idx = 0
        if self._get_current_vial() is not None:
            self._start_vial_p1()
        else:
            self._finish()

    # ------------------------------------------------------------------
    # Helpers génériques : chargement programme + surveillance STOPPED
    # ------------------------------------------------------------------
    def _start_program_with_helper(self, short_name, phase_label, helper, on_done):
        """Factorise la logique commune à P1..P4."""
        if not self._running:
            return

        if not self._ensure_ur3_connected():
            self._abort("UR3 non connecté.")
            return

        arm = self.devices.get("ur3")
        if not arm or not getattr(arm, "is_connected", lambda: False)():
            self._abort("UR3 non connecté.")
            return

        try:
            # 1) lister les programmes & sélectionner short_name dans la combo, comme en mode Man
            self.robot_win.on_refresh_programs()
            values = list(self.robot_win.cmb_programs["values"] or [])
            if not values:
                raise RuntimeError("aucun programme .urp disponible sur le robot.")

            short_low = short_name.lower()
            target = None
            for p in values:
                p_str = str(p)
                p_low = p_str.lower()
                if p_low.endswith("/" + short_low) or p_low.endswith("\\" + short_low) or p_low == short_low:
                    target = p_str
                    break

            if not target:
                raise RuntimeError(f"programme {short_name!r} introuvable sur le robot.")

            self.robot_win.var_selected_program.set(target)
            self.robot_win.on_load_selected_program()
            self._log(f"Mode JSON: lancement programme {short_name} ({phase_label}).")
        except Exception as e:
            self._abort(f"Impossible de charger le programme {short_name}: {e}")
            return

        # 2) Appeler le helper de WinRobotArm (vérifs préalables)
        if not callable(helper):
            self._abort(f"Aucun helper _play_{phase_label.lower()} disponible dans WinRobotArm.")
            return

        try:
            helper(arm)
        except Exception as e:
            self._abort(f"Erreur dans _play_{phase_label.lower()}(): {e}")
            return

        # 3) Démarrer le programme UR
        try:
            before = arm.get_program_state()
            play_resp = arm.play()
            self._log(
                f"Mode JSON: démarrage programme {phase_label} "
                f"(state_before={before} ; play→{play_resp})",
                level="info",
            )
        except Exception as e:
            self._abort(f"Erreur play() sur UR3: {e}")
            return

        # 4) Mettre l'UI robot en 'running' et laisser son watcher interne tourner
        try:
            self.robot_win._set_state("running")
            self.robot_win._start_run_watch()
        except Exception:
            pass

        # 5) Attendre STOPPED
        self._current_phase = phase_label
        self._waiting_for = "program"
        self._schedule_poll(on_done)

    def _schedule_poll(self, on_done):
        if not self._running:
            return
        # on mémorise le callback à appeler à la fin de la phase
        self._on_done_program = on_done
        self._after_id = self.after(AUTO_POLL_MS, self._poll_program_state)

    def _poll_program_state(self):
        """Surveille l'état du programme UR jusqu'à STOPPED, puis enchaîne."""
        self._after_id = None
        if not self._running:
            return

        if self._waiting_for != "program":
            # état anormal
            self._abort("État interne inattendu (_waiting_for != 'program').")
            return

        arm = self.devices.get("ur3")
        if not arm or not getattr(arm, "is_connected", lambda: False)():
            self._abort("Perte connexion UR3.")
            return

        try:
            raw = arm.get_program_state()
        except Exception as e:
            self._abort(f"Erreur lecture programState: {e}")
            return

        # Normalisation comme dans WinRobotArm / WinAuto
        try:
            canon = self.robot_win._canon_prog_state(raw)
        except Exception:
            up = str(raw or "").strip().upper()
            if "RUNNING" in up or "PLAYING" in up:
                canon = "RUNNING"
            elif "PAUSE" in up:
                canon = "PAUSED"
            elif "STOP" in up:
                canon = "STOPPED"
            else:
                canon = "UNKNOWN"

        if canon in ("RUNNING", "PAUSED", "UNKNOWN"):
            # toujours en cours → re-sonder
            self._after_id = self.after(AUTO_POLL_MS, self._poll_program_state)
            return

        if canon == "STOPPED":
            self._log(f"Mode JSON: programme {self._current_phase} terminé (STOPPED).", level="info")
            try:
                self.robot_win._set_state("idle")
            except Exception:
                pass

            cb = getattr(self, "_on_done_program", None)
            self._on_done_program = None
            self._waiting_for = None
            if callable(cb):
                cb()
            return

        # état encore différent → prudence
        self._after_id = self.after(AUTO_POLL_MS, self._poll_program_state)

    # ------------------------------------------------------------------
    # Dosing : exactement comme en manuel, mais avec callback de fin
    # ------------------------------------------------------------------
    def _start_dosing(self, on_done):
        if not self._running:
            return
        if not self._ensure_scale_connected():
            self._abort("Balance non connectée.")
            return

        # Lance exactement la même logique que le bouton manuel
        try:
            self.balance_win.on_start_dosing_job()
        except Exception as e:
            self._abort(f"Erreur lancement dosing job: {e}")
            return

        # Laisser un petit délai pour que WinBalance puisse créer le thread
        self._waiting_for = "dosing"
        self._on_done_dosing = on_done
        self._after_id = self.after(300, self._poll_dosing_state)

    def _poll_dosing_state(self):
        self._after_id = None
        if not self._running:
            return
        if self._waiting_for != "dosing":
            self._abort("État interne inattendu (_waiting_for != 'dosing').")
            return

        t = getattr(self.balance_win, "_dosing_thread", None)
        if t is None:
            # plus de thread → on considère que c'est fini
            self._log("Mode JSON: dosing job terminé (thread absent).", level="info")
            cb = getattr(self, "_on_done_dosing", None)
            self._on_done_dosing = None
            self._waiting_for = None
            if callable(cb):
                cb()
            return

        if t.is_alive():
            # Toujours en cours → replanifier un check
            self._after_id = self.after(1000, self._poll_dosing_state)
            return

        # thread fini
        self._log("Mode JSON: dosing job terminé.", level="info")
        cb = getattr(self, "_on_done_dosing", None)
        self._on_done_dosing = None
        self._waiting_for = None
        if callable(cb):
            cb()
