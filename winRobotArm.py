#!/usr/bin/env python3
# BEC - November 2025
# UI pour le bras UR3 (Dashboard + Script)
#-------------------------------------------------------------------------------

import tkinter as tk
import tkinter.ttk as ttk

from config import UR3_CONFIG
from guiUtils import GUIFactory, ToolTip
from deviceRobotArm import UR3, UR3ConnectionError
from winVials import WinVials
from winStorage import WinStorage

WATCH_PERIOD_MS = 3000  # check connexion toutes les 3 s
# Mapping UI ("E1-1" / "F2-3"...) -> numéro physique robot
VIAL_ID_TO_NUMBER = UR3_CONFIG.get("vial_id_to_number", {})
RTDE_INPUT_REGISTER = int(UR3_CONFIG.get("rtde_input_register", 20))

class WinRobotArm(tk.LabelFrame):
    """Pour piloter le bras UR3 (connexion, power, brake, movej simple, load program)."""

    def __init__(self, parent, info_win, devices):
        super().__init__(parent, text="Bras UR3")
        self.info = info_win
        self.devices = devices
        self.factory = GUIFactory(self)

        # Endpoint / config
        self.var_ip = tk.StringVar(value=str(UR3_CONFIG.get("ip", "192.168.0.2")))
        self.var_script_port = tk.StringVar(value=str(UR3_CONFIG.get("script_port", 30002)))
        self.var_dashboard_port = tk.StringVar(value=str(UR3_CONFIG.get("dashboard_port", 29999)))

        # Statut / modes
        self.var_status = tk.StringVar(value="Disconnected")
        self.var_robot_mode = tk.StringVar(value="-")
        self.var_safety_mode = tk.StringVar(value="-")
        self.var_program = tk.StringVar(value="-")
        self.var_prog_state = tk.StringVar(value="-")

        # Programmes UR
        self.var_selected_program = tk.StringVar(value="")
        self.cmb_programs: ttk.Combobox | None = None

        self.btn_connect: tk.Button | None = None
        self.win_vials: WinVials | None = None

        self._build()

        # Lancer le watcher
        self.after(WATCH_PERIOD_MS, self._watch_period)

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------
    def _get_ur3(self) -> UR3:
        arm = self.devices.get("ur3")
        if not arm:
            raise RuntimeError("Bras UR3 non connecté (devices['ur3'] est vide).")
        return arm

    def _make_ur3(self) -> UR3:
        """Crée une instance UR3 à partir des champs UI."""
        return UR3(
            ip=self.var_ip.get().strip(),
            script_port=int(self.var_script_port.get()),
            dashboard_port=int(self.var_dashboard_port.get()),
        )

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------
    def _build(self):
        # Configuration de la grille principale
        for c in range(12):
            self.columnconfigure(c, weight=0, minsize=80)

        row = 0

        # Ligne 0 : Config réseau + bouton Connect
        self.factory.create_label("IP", row, 0, sticky=tk.W)
        self.factory.create_entry(self.var_ip, row, 1, width=14)

        self.factory.create_label("Script", row, 2, sticky=tk.W)
        self.factory.create_entry(self.var_script_port, row, 3, width=6)

        self.factory.create_label("Dash", row, 4, sticky=tk.W)
        self.factory.create_entry(self.var_dashboard_port, row, 5, width=6)

        self.btn_connect = self.factory.create_btn(
            "Connect", self.on_connect, row, 6, width=10, sticky=tk.EW
        )
        ToolTip(self.btn_connect, "Connexion Dashboard + Script sur l'UR3")

        b_refresh = self.factory.create_btn(
            "Refresh modes", self.on_refresh_modes, row, 7, width=12, sticky=tk.W
        )
        ToolTip(b_refresh, "Relit robotmode / safetymode")

        row += 1

        # Ligne 1 : Statut + modes
        self.factory.create_label("Status", row, 0, sticky=tk.W)
        lbl_status = self.factory.create_labelvariable(self.var_status, row, 1, sticky=tk.W)

        lbl_rm = self.factory.create_labelvariable(self.var_robot_mode, row, 2, sticky=tk.W)
        lbl_rm.grid_configure(columnspan=2)

        lbl_sm = self.factory.create_labelvariable(self.var_safety_mode, row, 4, sticky=tk.W)
        lbl_sm.grid_configure(columnspan=2)

        lbl_prog = self.factory.create_labelvariable(self.var_program, row, 6, sticky=tk.W)
        lbl_prog.grid_configure(columnspan=2)

        lbl_prog_state = self.factory.create_labelvariable(self.var_prog_state, row, 8, sticky=tk.W)
        lbl_prog_state.grid_configure(columnspan=2)

        ToolTip(lbl_status, "État de la connexion socket")
        ToolTip(lbl_rm, "Mode robot renvoyé par 'robotmode'")
        ToolTip(lbl_sm, "Mode sécurité renvoyé par 'safetymode'")

        row += 1

        # Séparateur
        sep = ttk.Separator(self, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=12, sticky="ew", pady=(5, 5))
        row += 1

        # Ligne 3 : commandes Dashboard basiques
        row_dash = row
        b_power_on = self.factory.create_btn("Power ON", self.on_power_on, row_dash, 0)
        ToolTip(b_power_on, "Dashboard: 'power on'")

        b_power_off = self.factory.create_btn("Power OFF", self.on_power_off, row_dash, 1)
        ToolTip(b_power_off, "Dashboard: 'power off'")

        b_brake_rel = self.factory.create_btn("Brake release", self.on_brake_release, row_dash, 2)
        ToolTip(b_brake_rel, "Dashboard: 'brake release'")

        b_play = self.factory.create_btn("Play", self.on_play, row_dash, 4)
        ToolTip(b_play, "Dashboard: 'play' (lance le programme chargé)")

        b_stop = self.factory.create_btn("Stop", self.on_stop, row_dash, 5)
        ToolTip(b_stop, "Dashboard: 'stop'")

        # ------------------------------------------------------------------
        # Ligne 4 : Programmes (.urp) — Combo + Refresh + Load
        # ------------------------------------------------------------------
        row += 1
        self.factory.create_label("Program (.urp)", row, 0, sticky=tk.W)

        self.cmb_programs = ttk.Combobox(
            self, textvariable=self.var_selected_program, width=48, state="readonly", values=[]
        )
        self.cmb_programs.grid(row=row, column=1, columnspan=5, sticky="ew", padx=2)

        btn_prog_refresh = self.factory.create_btn(
            "Refresh list", self.on_refresh_programs, row, 6, width=12, sticky=tk.EW
        )
        ToolTip(btn_prog_refresh, "Liste les .urp via SFTP sur /programs")

        btn_prog_load = self.factory.create_btn(
            "Load program", self.on_load_selected_program, row, 7, width=12, sticky=tk.EW
        )
        ToolTip(btn_prog_load, "Dashboard: 'load <chemin>' avec l'élément sélectionné")

        # --------------------------------------------------------------
        # Sous-panneaux Vials + Storage
        # --------------------------------------------------------------
        row_vials = row + 1

        # Vials à gauche
        self.win_vials = WinVials(self, self.info, title="Vials")
        self.win_vials.grid(row=row_vials, column=0, columnspan=2, sticky="ns", padx=5, pady=5)

        # Storage à droite
        self.win_storage = WinStorage(self, self.info, title="Storage")
        self.win_storage.grid(row=row_vials, column=4, sticky="ns", padx=5, pady=5)

    # ------------------------------------------------------------------
    # Connexion + heartbeat
    # ------------------------------------------------------------------
    def on_connect(self):
        """Tentative de connexion UR3."""
        if self.btn_connect:
            self.btn_connect.configure(state="disabled", text="Connecting…")
        try:
            arm = self._make_ur3()
            banner = arm.connect()
            self.devices["ur3"] = arm
            self.var_status.set("Connected")
            if banner:
                self.info.add(f"UR3 connecté. Dashboard: {banner}")
            else:
                self.info.add("UR3 connecté (pas de bannière Dashboard).")
            if self.btn_connect:
                self.btn_connect.configure(state="disabled", text="Connected")
        except Exception as e:
            if self.btn_connect:
                self.btn_connect.configure(state="normal", text="Connect")
            self.var_status.set("Error")
            self.info.add(f"Erreur connexion UR3: {e}", level="error")

    def _watch_period(self):
        """Vérifie périodiquement l'état de la connexion ; si perdu → bouton réactivé."""
        try:
            arm = self.devices.get("ur3")
            ok = bool(arm and arm.is_connected() and arm.ping())
        except Exception:
            ok = False

        if ok:
            if self.btn_connect:
                self.btn_connect.configure(state="disabled", text="Connected")
            self.var_status.set("Connected")
        else:
            if self.btn_connect:
                self.btn_connect.configure(state="normal", text="Connect")
            if self.devices.get("ur3"):
                self.info.add("UR3: connexion perdue.", level="warning")
                try:
                    self.devices["ur3"].close()
                except Exception:
                    pass
                self.devices["ur3"] = None
            self.var_status.set("Disconnected")

        self.after(WATCH_PERIOD_MS, self._watch_period)

    # ------------------------------------------------------------------
    # Actions Dashboard
    # ------------------------------------------------------------------
    def _call_dash(self, label: str, func):
        """Helper pour appeler une méthode Dashboard et logger la réponse."""
        try:
            arm = self._get_ur3()
            resp = func(arm)
            self.info.add(f"UR3 {label} → {resp}")
        except (RuntimeError, UR3ConnectionError) as e:
            self.info.add(f"UR3 {label} → ERREUR : {e}", level="error")
            self.var_status.set("Error")

    def on_power_on(self):
        self._call_dash("power on", lambda arm: arm.power_on())

    def on_power_off(self):
        self._call_dash("power off", lambda arm: arm.power_off())

    def on_brake_release(self):
        self._call_dash("brake release", lambda arm: arm.brake_release())

    def on_play(self):
        """Envoie VialsNB (via RTDE: GPii[RTDE_INPUT_REGISTER]) puis lance le programme chargé."""
        try:
            vial_id, group = self._get_selected_vial_any()
            if not vial_id:
                self.info.add("Play → aucune vial E* ni F* sélectionnée.", level="warning")
                return

            vnum = self._vial_id_to_number(vial_id)
            arm = self._get_ur3()

            # Stop au cas où un programme tourne encore
            arm.stop()

            # Écrire VialsNB via RTDE (GPii[RTDE_INPUT_REGISTER])
            arm.set_input_int_register_rtde(RTDE_INPUT_REGISTER, vnum)
            self.info.add(f"UR3 RTDE: GPii[{RTDE_INPUT_REGISTER}] (VialsNB) ← {vnum} ({vial_id}, groupe {group})")

            # Lancer le programme déjà chargé
            before = arm.get_program_state()
            resp   = arm.play()
            after  = arm.get_program_state()
            self.info.add(f"UR3 play → state_before={before} ; play→{resp} ; state_after={after}")

        except (RuntimeError, UR3ConnectionError, ValueError) as e:
            self.info.add(f"UR3 play (VialsNB via RTDE) → ERREUR : {e}", level="error")
            self.var_status.set("Error")

    def on_stop(self):
        self._call_dash("stop", lambda arm: arm.stop())

    def on_refresh_modes(self):
        try:
            arm = self._get_ur3()
            rm = arm.get_robot_mode()
            sm = arm.get_safety_mode()
            self.var_robot_mode.set(rm)
            self.var_safety_mode.set(sm)
            self.info.add(f"UR3 robotmode → {rm}")
            self.info.add(f"UR3 safetymode → {sm}")
            prog = arm.get_loaded_program()
            state = arm.get_program_state()
            self.var_program.set(prog)
            self.var_prog_state.set(state)
            self.info.add(f"UR3 programme → {prog}")
            self.info.add(f"UR3 state → {state}")
        except (RuntimeError, UR3ConnectionError) as e:
            self.info.add(f"UR3 refresh modes → ERREUR : {e}", level="error")
            self.var_status.set("Error")

    # ------------------------------------------------------------------
    # Programs: refresh + load
    # ------------------------------------------------------------------
    def on_refresh_programs(self):
        """Liste les .urp via SFTP et remplit la Combobox."""
        try:
            arm = self._get_ur3()
            progs = arm.list_programs()
            if not progs:
                self.info.add("UR3: aucun programme .urp trouvé sur /programs", level="warning")
            if self.cmb_programs:
                self.cmb_programs["values"] = progs
                # si un LouisBastien existe, le sélectionner d'office
                default = next((p for p in progs if p.endswith("LouisBastien.urp")), (progs[0] if progs else ""))
                if default:
                    self.var_selected_program.set(default)
            self.info.add(f"UR3: {len(progs)} programme(s) trouvé(s).")
        except (RuntimeError, UR3ConnectionError) as e:
            self.info.add(f"UR3 refresh programs → ERREUR : {e}", level="error")

    def on_load_selected_program(self):
        """Charge le programme actuellement sélectionné dans la Combobox (Dashboard 'load')."""
        prog = self.var_selected_program.get().strip()
        if not prog:
            self.info.add("Load program → aucun programme sélectionné.", level="warning")
            return

        def _do(arm):
            resp = arm.load_program(prog)
            return f"load {prog} → {resp}"

        self._call_dash("load", _do)

    # ------------------------------------------------------------------
    # Accès aux vials / storage (pas vraiment testé encore)
    # ------------------------------------------------------------------
    def get_selected_vial_e(self) -> str | None:
        if self.win_vials:
            return self.win_vials.get_selected_vial_e()
        return None

    def get_selected_vial_f(self) -> str | None:
        if self.win_vials:
            return self.win_vials.get_selected_vial_f()
        return None
    
    def _get_selected_vial_any(self) -> tuple[str | None, str]:
        """
        Retourne (vial_id, group), en prenant E* en priorité, sinon F*.
        group ∈ {"E","F"} si trouvé, sinon ("", "").
        """
        v = self.get_selected_vial_e()
        if v:
            return v, "E"
        v = self.get_selected_vial_f()
        if v:
            return v, "F"
        return None, ""

    def get_selected_storage(self) -> str | None:
        if self.win_storage:
            return self.win_storage.get_selected_storage()
        return None
    
    # ------------------------------------------------------------------
    # Helper: map 'E1-1'..'E3-4' -> 1..11
    # E1: 4 vials -> 1..4
    # E2: 3 vials -> 5..7
    # E3: 4 vials -> 8..11
    # ------------------------------------------------------------------
    def _vial_id_to_number(self, vial_id: str) -> int:
        try:
            return VIAL_ID_TO_NUMBER[vial_id]
        except KeyError:
            raise ValueError(f"vial_id inconnu ou non mappé: {vial_id!r}")

