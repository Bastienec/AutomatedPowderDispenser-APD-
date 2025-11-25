#!/usr/bin/env python3
# BEC - November 2025
# UI pour la balance (WebService uniquement)
#-------------------------------------------------------------------------------

import tkinter as tk
import tkinter.ttk as ttk
import threading

from config import SCALE_CONFIG
from guiUtils import GUIFactory, ToolTip
from deviceScale import WM

WATCH_PERIOD_MS = 3000  # check connexion toutes les 3 s


class WinBalance(tk.LabelFrame):
    """Pour piloter la balance via WebService (portes / zero / tare / poids / dosing)."""
    def __init__(self, parent, info_win, devices):
        super().__init__(parent, text="Balance Mettler (WebService)")
        self.info = info_win
        self.devices = devices
        self.factory = GUIFactory(self)

        # Vars UI (non éditables)
        self.var_ip     = tk.StringVar(value=str(SCALE_CONFIG.get('ip', '192.168.0.50')))
        self.var_port   = tk.StringVar(value=str(SCALE_CONFIG.get('port', 81)))
        self.var_scheme = tk.StringVar(value=str(SCALE_CONFIG.get('scheme', 'http')).lower())

        # Lecture de poids
        self.var_weight = tk.StringVar(value="— g")

        # Méthode (menu "Methods" sur la balance)
        self.var_method = tk.StringVar(value="DOSING")

        # Paramètres pour un job de dosing
        self.var_d_vial      = tk.StringVar(value="Vessel1")
        self.var_d_substance = tk.StringVar(value="")   # substance du job
        self.var_d_target    = tk.DoubleVar(value=5.0)
        self.var_d_tu        = tk.StringVar(value="mg")
        self.var_d_tol_lo    = tk.DoubleVar(value=0.0)
        self.var_d_tol_up    = tk.DoubleVar(value=0.0)
        self.var_d_tol_u     = tk.StringVar(value="mg")

        # Dosing head (nom du dispenser en place)
        self.var_dosing_head = tk.StringVar(value="")   # substance lue sur la tête

        self.btn_connect = None
        self.btn_dosing_start = None

        # Thread de polling des notifications de dosing
        self._dosing_thread: threading.Thread | None = None

        self._build()

        # Auto-connexion si demandé
        if SCALE_CONFIG.get('autoconnect', True):
            self.after(200, self._auto_connect)
        # Heartbeat (réactive le bouton si on perd la connexion)
        self.after(WATCH_PERIOD_MS, self._watch_period)

    # ---------------------------------------------------------
    def _build(self):
        # Ligne 0 : IP/Port + bouton Connect
        self.factory.create_label("Scheme", 0, 0)
        cb_scheme = ttk.Combobox(
            self,
            textvariable=self.var_scheme,
            width=6,
            values=("http", "https"),
            state="readonly",
        )
        cb_scheme.grid(row=0, column=1, padx=5, pady=5)

        self.factory.create_label("IP", 0, 2)
        self.factory.create_entry(self.var_ip, 0, 3, width=16)

        self.factory.create_label("Port", 0, 4)
        self.factory.create_entry(self.var_port, 0, 5, width=6)

        self.btn_connect = self.factory.create_btn("Connect", self.on_connect, 0, 6)
        ToolTip(self.btn_connect, "Se connecter au WebService de la balance")

        # Quand IP/port/scheme changent → rendre le bouton actif si besoin
        def _on_endpoint_change(*_):
            if self.btn_connect:
                self.btn_connect.configure(state="normal", text="Connect")
        self.var_ip.trace_add("write", _on_endpoint_change)
        self.var_port.trace_add("write", _on_endpoint_change)
        self.var_scheme.trace_add("write", _on_endpoint_change)

        # Ligne 1 : Portes + Zero/Tare/Lire
        b_open = self.factory.create_btn("Open door", self.on_open_door, 1, 0)
        ToolTip(b_open, "Ouvrir porte via DraftShieldsService.SetPosition")
        b_close = self.factory.create_btn("Close door", self.on_close_door, 1, 1)
        ToolTip(b_close, "Fermer porte via DraftShieldsService.SetPosition")

        b_zero = self.factory.create_btn("Zero", self.on_zero, 1, 2)
        b_tare = self.factory.create_btn("Tare", self.on_tare, 1, 3)
        b_read = self.factory.create_btn("Lire poids", self.on_read, 1, 4)

        self.factory.create_label("Poids:", 1, 5)
        lbl_w = self.factory.create_label("", 1, 6, sticky=tk.W)
        lbl_w.configure(textvariable=self.var_weight)

        # Ligne 2 : choix de la méthode (menu "Methods")
        self.factory.create_label("Method", 2, 0)
        cb_method = ttk.Combobox(
            self,
            textvariable=self.var_method,
            width=18,
            values=("DOSING", "General Weighing"),
            state="readonly",
        )
        # cb_method.current(1)  # Par défaut sur General Weighing dans l'UI
        cb_method.grid(row=2, column=1, padx=5, pady=5, columnspan=2, sticky=tk.W)

        b_set_method = self.factory.create_btn("Start method", self.on_start_method, 2, 3)
        ToolTip(b_set_method, "Sélectionner la méthode de pesée (menu 'Methods' de la balance)")

        # Ligne 3-4 : paramètres DOSING (DosingAutomation)
        self.factory.create_label("Dosing vial", 3, 0)
        self.factory.create_entry(self.var_d_vial, 3, 1, width=12)

        self.factory.create_label("Substance", 3, 2)
        self.factory.create_entry(self.var_d_substance, 3, 3, width=12)

        self.factory.create_label("Target", 4, 0)
        self.factory.create_entry(self.var_d_target, 4, 1, width=8)
        cb_dt = ttk.Combobox(
            self,
            textvariable=self.var_d_tu,
            width=6,
            values=("mg", "g"),
            state="readonly",
        )
        cb_dt.grid(row=4, column=2, padx=5, pady=5)

        self.factory.create_label("−Tol", 4, 3)
        self.factory.create_entry(self.var_d_tol_lo, 4, 4, width=8)
        self.factory.create_label("+Tol", 4, 5)
        self.factory.create_entry(self.var_d_tol_up, 4, 6, width=8)
        cb_dtu = ttk.Combobox(
            self,
            textvariable=self.var_d_tol_u,
            width=6,
            values=("mg", "g"),
            state="readonly",
        )
        cb_dtu.grid(row=4, column=7, padx=5, pady=5)

        self.btn_dosing_start = self.factory.create_btn(
            "Start dosing job", self.on_start_dosing_job, 4, 8
        )
        ToolTip(self.btn_dosing_start, "Lancer un job de dosage (DosingAutomation) avec 1 job")

        # Ligne 5 : Dosing Head (lecture / écriture)
        self.factory.create_label("Dosing head", 5, 0)
        self.factory.create_entry(self.var_dosing_head, 5, 1, width=16)

        btn_read_head = self.factory.create_btn("Read", self.on_read_dosing_head, 5, 2)
        ToolTip(btn_read_head, "Lire le dosing head en place (ReadDosingHead)")

        btn_write_head = self.factory.create_btn("Write", self.on_write_dosing_head, 5, 3)
        ToolTip(btn_write_head, "Écrire le nom sur le dosing head en place (WriteDosingHead)")

        # Layout
        for c in range(0, 11):
            self.grid_columnconfigure(c, weight=0)
        self.grid_columnconfigure(6, weight=1)

    # ---------------------------------------------------------
    # Helpers
    def _get_wm(self) -> WM:
        sc = self.devices.get('scale')
        if sc is None:
            raise RuntimeError("Balance non connectée")
        return sc

    def _make_wm(self) -> WM:
        return WM(
            scheme=self.var_scheme.get().strip(),
            ip=self.var_ip.get().strip(),
            port=int(self.var_port.get()),
            wsdl_path=SCALE_CONFIG.get("wsdl_path"),
            password=SCALE_CONFIG.get("password"),
            verify=SCALE_CONFIG.get("verify", False),
            timeout_s=SCALE_CONFIG.get("timeout_s", 8),
            door_ids=SCALE_CONFIG.get("door_ids", ["LeftOuter", "RightOuter"]),
            open_width=SCALE_CONFIG.get("open_width", 100),
            close_width=SCALE_CONFIG.get("close_width", 0),
        )

    # ---------------------------------------------------------
    # Connexion / Heartbeat
    def on_connect(self):
        # désactive le bouton pendant la tentative
        if self.btn_connect:
            self.btn_connect.configure(state="disabled", text="Connecting…")
        try:
            wm = self._make_wm()
            wm.connect()  # fait OpenSession + garde SessionId interne
            self.devices['scale'] = wm
            self.info.add("Balance connectée (WebService).")

            # --- Auto-start de la méthode sélectionnée dans le menu (par défaut: DOSING)
            method_ui = (self.var_method.get() or "").strip()   # ex: "DOSING" ou "General Weighing"
            if method_ui:
                try:
                    # 1er essai tel quel (si ton firmware veut 'DOSING' en maj, ça marche direct)
                    wm.set_method(method_ui)
                    self.info.add(f"Auto-start method '{method_ui}' → OK")
                except Exception as e1:
                    # Fallback de casse le plus courant pour DOSING
                    if method_ui.upper() == "DOSING":
                        try:
                            wm.set_method("Dosing")
                            self.info.add("Auto-start method fallback 'Dosing' → OK")
                            # harmonise l’UI si tu veux rester en majuscules
                            self.var_method.set("DOSING")
                        except Exception as e2:
                            self.info.add(f"Auto-start method '{method_ui}' échouée: {e2}", level="warning")
                    else:
                        self.info.add(f"Auto-start method '{method_ui}' échouée: {e1}", level="warning")

            # si succès → laisser le bouton désactivé
            if self.btn_connect:
                self.btn_connect.configure(state="disabled", text="Connected")
        except Exception as e:
            # échec → réactiver pour retente
            if self.btn_connect:
                self.btn_connect.configure(state="normal", text="Connect")
            self.info.add(f"Connexion WS échouée — {e}", level="error")


    def _auto_connect(self):
        # essai silencieux au démarrage
        try:
            self.on_connect()
        except Exception as e:
            self.info.add(f"Auto-connect échoué: {e}", level="warning")

    def _watch_period(self):
        """Vérifie périodiquement l'état WS ; si perdu → réactiver le bouton."""
        try:
            wm = self.devices.get('scale')
            ok = bool(wm and wm.is_connected() and wm.ping())
        except Exception:
            ok = False

        if ok:
            # connecté → bouton reste disabled
            if self.btn_connect:
                self.btn_connect.configure(state="disabled", text="Connected")
        else:
            # déconnecté → bouton réactivé
            if self.btn_connect:
                self.btn_connect.configure(state="normal", text="Connect")

        # replanifie
        self.after(WATCH_PERIOD_MS, self._watch_period)

    # ---------------------------------------------------------
    # Actions UI basiques
    def on_open_door(self):
        try:
            resp = self._get_wm().open_door()
            self.info.add(f"Open door → {resp}")
        except Exception as e:
            self.info.add(f"Open door: {e}", level="error")

    def on_close_door(self):
        try:
            resp = self._get_wm().close_door()
            self.info.add(f"Close door → {resp}")
        except Exception as e:
            self.info.add(f"Close door: {e}", level="error")

    def on_zero(self):
        try:
            resp = self._get_wm().zero()
            self.info.add(f"Zero → {resp}")
        except Exception as e:
            self.info.add(f"Zero: {e}", level="error")

    def on_tare(self):
        try:
            resp = self._get_wm().tare()
            self.info.add(f"Tare → {resp}")
        except Exception as e:
            self.info.add(f"Tare: {e}", level="error")

    def on_read(self):
        try:
            w = self._get_wm().get_weight()
            self.var_weight.set(f"{w:.3f} g")
            self.info.add(f"Poids: {w:.3f} g")
        except Exception as e:
            self.info.add(f"Lecture: {e}", level="error")

    def on_start_method(self):
        try:
            method = self.var_method.get().strip()
            resp = self._get_wm().set_method(method)
            self.info.add(f"Start method '{method}' → {resp}")
        except Exception as e:
            self.info.add(f"Start method: {e}", level="error")

    # ---------------------------------------------------------
    # Dosing Automation : démarrage job + thread de notifications
    def _start_dosing_notifications_thread(self):
        """Lance un thread (si pas déjà lancé) qui poll GetNotifications et auto-confirme."""
        if self._dosing_thread and self._dosing_thread.is_alive():
            return

        def _worker():
            def log_cb(msg: str):
                # Appelé depuis le thread de fond → repasser par Tk
                self.after(0, lambda m=msg: self.info.add(m))
            try:
                self._get_wm().auto_confirm_dosing_notifications(
                    log_cb=log_cb,
                    long_poll_s=10,
                )
                self.after(0, lambda: self.info.add("DosingAutomation terminé (auto-confirm)."))
            except Exception as e:
                msg = f"Erreur auto-confirm dosing: {e}"
                self.after(0, lambda m=msg: self.info.add(m, level="error"))

        self._dosing_thread = threading.Thread(target=_worker, daemon=True)
        self._dosing_thread.start()

    def on_start_dosing_job(self):
        """Lance un DosingJobList avec un seul job via IDosingAutomationService."""
        try:
            method = self.var_method.get().strip().lower()
            if method != "dosing":
                self.info.add(
                    "La méthode active n'est pas 'Dosing' → je la démarre avant de lancer le job."
                )
                self._get_wm().set_method("Dosing")
                self.var_method.set("DOSING")

            vial   = self.var_d_vial.get().strip()
            sub    = self.var_d_substance.get().strip()
            tgt    = float(self.var_d_target.get())
            t_unit = self.var_d_tu.get()
            tol_lo = float(self.var_d_tol_lo.get())
            tol_up = float(self.var_d_tol_up.get())
            tol_u  = self.var_d_tol_u.get()

            resp = self._get_wm().start_dosing_job(
                vial_name=vial,
                substance_name=sub,
                target_value=tgt,
                target_unit=t_unit,
                lower_tol_value=tol_lo,
                upper_tol_value=tol_up,
                tol_unit=tol_u,
            )

            out   = resp.get("Outcome")
            cmd   = resp.get("CommandId")
            err   = resp.get("ErrorMessage")
            s_err = resp.get("StartDosingJobListError")
            jerr  = resp.get("JobErrors")

            msg = f"Dosing job '{vial}' / '{sub}' {tgt:g}{t_unit} "
            msg += f"(−{tol_lo:g}{tol_u}/+{tol_up:g}{tol_u}) → Outcome={out}, CommandId={cmd}"
            if s_err:
                msg += f", StartError={s_err}"
            if err:
                msg += f", Error={err}"
            if jerr:
                msg += f", JobErrors={jerr}"

            self.info.add(msg)

            # Si le démarrage s'est bien passé → on lance le polling de notifications
            if out == "Success" and not s_err:
                self._start_dosing_notifications_thread()

        except Exception as e:
            self.info.add(f"Start dosing job: {e}", level="error")

    # ---------------------------------------------------------
    # Dosing Head : lecture / écriture
    def on_read_dosing_head(self):
        """Lit le nom du dosing head en place via ReadDosingHead et aligne aussi la substance du job."""
        try:
            name = self._get_wm().get_dosing_head_name().strip()
            # Alimente le champ "Dosing head" (ligne 5)
            self.var_dosing_head.set(name)
            # Et synchronise la substance du job de dosing
            self.var_d_substance.set(name)
            # Log minimaliste (seulement le nom)
            self.info.add(f"Dosing head lu: {name or '—'}")
        except Exception as e:
            self.info.add(f"Read dosing head: {e}", level="error")


    def on_write_dosing_head(self):
        """Écrit le nom dans le dosing head via WriteDosingHead et aligne aussi la substance du job."""
        try:
            name = self.var_dosing_head.get().strip()
            if not name:
                self.info.add("Nom de dosing head vide → rien à écrire.", level="warning")
                return

            resp = self._get_wm().set_dosing_head_name(name)
            # Synchronise la substance du job de dosing avec ce qu'on vient d’inscrire
            self.var_d_substance.set(name)
            self.info.add(f"Dosing head écrit: '{name}' → {resp}")
        except Exception as e:
            self.info.add(f"Write dosing head: {e}", level="error")
