#!/usr/bin/env python3
# BEC - November 2025
# UI pour le bras UR3 (Dashboard + Script)
#-------------------------------------------------------------------------------

import tkinter as tk
import tkinter.ttk as ttk
from contextlib import contextmanager

from config import UR3_CONFIG, STORAGE_CONFIG, SCALE_CONFIG
from guiUtils import GUIFactory, ToolTip
from deviceRobotArm import UR3, UR3ConnectionError
from winVials import WinVials
from winStorage import WinStorage

# ---------------------------------------------------------------------------
# Constantes / Config
# ---------------------------------------------------------------------------
WATCH_PERIOD_MS = 3000  # check connexion toutes les 3 s
VIAL_ID_TO_NUMBER = UR3_CONFIG.get("vial_id_to_number", {})
RTDE_INPUT_REGISTER = int(UR3_CONFIG.get("rtde_input_register", 20))
DISP_RTDE_INPUT_REGISTER = int(UR3_CONFIG.get("disp_rtde_input_register", 21))


class WinRobotArm(tk.LabelFrame):
    """Pilote UR3 (connexion, états, play/pause/stop) avec autoload .urp via combobox."""

    # -----------------------------------------------------------------------
    # Construction / State
    # -----------------------------------------------------------------------
    def __init__(self, parent, info_win, devices):
        super().__init__(parent, text="Bras UR3")
        self.info = info_win
        self.devices = devices
        self.factory = GUIFactory(self)
        self._state = "idle"  # "idle" | "running" | "paused"

        # Endpoint / config
        self.var_ip = tk.StringVar(value=str(UR3_CONFIG.get("ip", "192.168.0.2")))
        self.var_script_port = tk.StringVar(value=str(UR3_CONFIG.get("script_port", 30002)))
        self.var_dashboard_port = tk.StringVar(value=str(UR3_CONFIG.get("dashboard_port", 29999)))

        # Statut / modes
        self.var_status = tk.StringVar(value="Disconnected")
        self.var_robot_mode = tk.StringVar(value="-")
        self.var_safety_mode = tk.StringVar(value="-")
        self.var_program = tk.StringVar(value="-")      # ligne dashboard ("Loaded program: ...")
        self.var_prog_state = tk.StringVar(value="-")   # RUNNING/STOPPED/PAUSED côté robot

        # Programmes (.urp)
        self.var_selected_program = tk.StringVar(value="")
        self.cmb_programs: ttk.Combobox | None = None
        self._suspend_combo_event = 0  # bloqueur d’évènement

        # Pointeurs UI
        self.btn_connect: tk.Button | None = None
        self.btn_pause: tk.Button | None = None
        self.btn_stop: tk.Button | None = None
        self.btn_play: tk.Button | None = None

        # Sous-fenêtres
        self.win_vials: WinVials | None = None
        self.win_storage: WinStorage | None = None

        self._build()
        self.after(WATCH_PERIOD_MS, self._watch_period)

    # -----------------------------------------------------------------------
    # Context manager : bloqueur évènements combo
    # -----------------------------------------------------------------------
    @contextmanager
    def _combo_guard(self):
        self._suspend_combo_event += 1
        try:
            yield
        finally:
            self._suspend_combo_event = max(0, self._suspend_combo_event - 1)

    def _combo_events_enabled(self) -> bool:
        return self._suspend_combo_event == 0

    # -----------------------------------------------------------------------
    # Helpers matériels / mapping
    # -----------------------------------------------------------------------
    def _make_ur3(self) -> UR3:
        return UR3(
            ip=self.var_ip.get().strip(),
            script_port=int(self.var_script_port.get()),
            dashboard_port=int(self.var_dashboard_port.get()),
        )

    def _get_ur3(self) -> UR3:
        arm = self.devices.get("ur3")
        if not arm:
            raise RuntimeError("Bras UR3 non connecté (devices['ur3'] est vide).")
        return arm

    def _get_scale(self):
        """Retourne l'instance balance si connectée, sinon None."""
        return self.devices.get("scale")

    def _vial_id_to_number(self, vial_id: str) -> int:
        try:
            return int(VIAL_ID_TO_NUMBER[vial_id])
        except KeyError:
            raise ValueError(f"vial_id inconnu ou non mappé: {vial_id!r}")

    def _storage_id_to_number(self, storage_id: str) -> int:
        m = (STORAGE_CONFIG.get("id_to_number") or {})
        if storage_id in m:
            return int(m[storage_id])
        if isinstance(storage_id, str) and storage_id.upper().startswith("S"):
            return int(storage_id[1:])
        raise ValueError(f"storage_id invalide: {storage_id!r}")

    # -----------------------------------------------------------------------
    # UI build / wiring
    # -----------------------------------------------------------------------
    def _build(self):
        for c in range(12):
            self.columnconfigure(c, weight=0, minsize=80)

        # Ligne 0: Connexion + actions système
        self.btn_connect = self.factory.create_btn("Connect", self.on_connect, 0, 0, width=12, sticky=tk.EW)
        ToolTip(self.btn_connect, "Connexion Dashboard à l’UR3")

        btn_refresh_modes = self.factory.create_btn("Refresh modes", self.on_refresh_modes, 0, 1, width=14, sticky=tk.W)
        ToolTip(btn_refresh_modes, "Relit robotmode / safetymode")
        self.btn_refresh_modes = btn_refresh_modes

        btn_disconnect = self.factory.create_btn("Disconnect", self.on_disconnect, 0, 2, width=12, sticky=tk.EW)
        ToolTip(btn_disconnect, "Fermer proprement la connexion Dashboard/Script")
        btn_disconnect.configure(state="disabled")
        self.btn_disconnect = btn_disconnect

        btn_power_on  = self.factory.create_btn("Power ON",  self.on_power_on,  0, 3)
        ToolTip(btn_power_on, "Dashboard: 'power on'")
        btn_power_off = self.factory.create_btn("Power OFF", self.on_power_off, 0, 4)
        ToolTip(btn_power_off, "Dashboard: 'power off'")
        btn_brake_rel = self.factory.create_btn("Brake release", self.on_brake_release, 0, 5)
        ToolTip(btn_brake_rel, "Dashboard: 'brake release'")

        self.btn_power_on  = btn_power_on
        self.btn_power_off = btn_power_off
        self.btn_brake_rel = btn_brake_rel

        # Ligne 1: Statuts
        self.factory.create_label("Status", 1, 0, sticky=tk.W)
        lbl_status = self.factory.create_labelvariable(self.var_status, 1, 1, sticky=tk.W)
        lbl_rm = self.factory.create_labelvariable(self.var_robot_mode, 1, 2, sticky=tk.W); lbl_rm.grid_configure(columnspan=2)
        lbl_sm = self.factory.create_labelvariable(self.var_safety_mode, 1, 4, sticky=tk.W); lbl_sm.grid_configure(columnspan=2)
        lbl_prog = self.factory.create_labelvariable(self.var_program, 1, 6, sticky=tk.W); lbl_prog.grid_configure(columnspan=2)
        lbl_prog_state = self.factory.create_labelvariable(self.var_prog_state, 1, 8, sticky=tk.W); lbl_prog_state.grid_configure(columnspan=2)
        ToolTip(lbl_status, "État de la connexion"); ToolTip(lbl_rm, "Robot mode"); ToolTip(lbl_sm, "Safety mode")

        # Séparateur
        ttk.Separator(self, orient="horizontal").grid(row=2, column=0, columnspan=12, sticky="ew", pady=(5, 5))

        # Ligne 3: Programmes
        self.factory.create_label("Program (.urp)", 3, 0, sticky=tk.W)
        self.cmb_programs = ttk.Combobox(self, textvariable=self.var_selected_program, width=48, state="readonly", values=[])
        self.cmb_programs.grid(row=3, column=1, columnspan=3, sticky="ew", padx=2)
        self.cmb_programs.bind("<<ComboboxSelected>>", self._on_program_selected)

        self.btn_play  = self.factory.create_btn("Play",  self.on_play,  3, 4); ToolTip(self.btn_play, "Dashboard: 'play'")
        self.btn_pause = self.factory.create_btn("Pause", self.on_pause, 3, 5); ToolTip(self.btn_pause, "Dashboard: 'pause'")
        self.btn_stop  = self.factory.create_btn("Stop",  self.on_stop,  3, 6); ToolTip(self.btn_stop, "Dashboard: 'stop'")

        # Ligne 4: Sous-panneaux
        self.win_vials = WinVials(self, self.info, title="Vials")
        self.win_vials.grid(row=5, column=0, columnspan=2, sticky="ns", padx=5, pady=5)

        self.win_storage = WinStorage(self, self.info, title="Storage")
        self.win_storage.grid(row=5, column=4, sticky="ns", padx=5, pady=5)

        self._bind_shortcuts()
        self._set_connected_ui(False, initialize=True)

    def _bind_shortcuts(self):
        root = self.winfo_toplevel()
        def _stop(_e=None):
            self.on_stop()
            return "break"
        root.bind_all("<Escape>", _stop, add="+")

    # -----------------------------------------------------------------------
    # Connexion / Heartbeat
    # -----------------------------------------------------------------------
    def _set_connected_ui(self, connected: bool, *, initialize: bool = False):
        if connected:
            self.btn_connect.configure(state="disabled", text="Connected")
            self.btn_disconnect.configure(state="normal")
        else:
            self.btn_connect.configure(state="normal", text="Connect")
            self.btn_disconnect.configure(state="disabled")

        generic_targets = [
            self.btn_refresh_modes, self.btn_disconnect,
            self.btn_power_on, self.btn_power_off, self.btn_brake_rel,
        ]
        if initialize:
            generic_targets += [self.btn_play, self.btn_pause, self.btn_stop]

        state = "normal" if connected else "disabled"
        for w in generic_targets:
            try: w.configure(state=state)
            except Exception: pass

        try:
            self.cmb_programs.configure(state="readonly" if connected else "disabled")
        except Exception:
            pass

        if initialize:
            if connected:
                self._set_state("idle")
            else:
                self.btn_play.configure(state="disabled")
                self.btn_pause.configure(state="disabled", text="Pause")
                self.btn_stop.configure(state="disabled")

    def _set_state(self, state: str):
        self._state = state
        if state == "idle":
            self.btn_play.configure(state="normal")
            self.btn_pause.configure(text="Pause", state="disabled")
            self.btn_stop.configure(state="disabled")
        elif state == "running":
            self.btn_play.configure(state="disabled")
            self.btn_pause.configure(text="Pause", state="normal")
            self.btn_stop.configure(state="normal")
        elif state == "paused":
            self.btn_play.configure(state="disabled")
            self.btn_pause.configure(text="Continue", state="normal")
            self.btn_stop.configure(state="normal")

    def on_connect(self):
        if self.btn_connect:
            self.btn_connect.configure(state="disabled", text="Connecting…")
        if getattr(self, "btn_disconnect", None):
            self.btn_disconnect.configure(state="normal")
        try:
            arm = self._make_ur3()
            banner = arm.connect()
            self.devices["ur3"] = arm
            self._set_connected_ui(True, initialize=True)
            self.var_status.set("Connected")
            self.info.add(f"UR3 connecté. Dashboard: {banner or '—'}")
            if self.btn_connect:
                self.btn_connect.configure(state="disabled", text="Connected")

            def _post_connect_bootstrap():
                try: self.on_refresh_modes()
                except Exception as e: self.info.add(f"Auto-Refresh modes après connexion → ERREUR : {e}", level="error")
                try: self.on_refresh_programs()
                except Exception as e: self.info.add(f"Auto-Refresh list après connexion → ERREUR : {e}", level="error")
            self.after(150, _post_connect_bootstrap)

        except Exception as e:
            if self.btn_connect:
                self.btn_connect.configure(state="normal", text="Connect")
            self.var_status.set("Error")
            self.info.add(f"Erreur connexion UR3: {e}", level="error")

    def _force_need_reconnect(self, reason: str = ""):
        try:
            if self.devices.get("ur3"):
                self.devices["ur3"].close()
        except Exception:
            pass
        self.devices["ur3"] = None
        self.var_status.set("Need Reconnect")
        self._set_connected_ui(False, initialize=True)
        self.btn_connect.configure(text="Reconnect")
        self.info.add("UR3: mode Local/Teach détecté → reconnectez en Remote (Dashboard 29999)." + (f" Détail: {reason}" if reason else ""), level="warning")

    def on_disconnect(self):
        try:
            if self.devices.get("ur3"):
                self.devices["ur3"].close()
        finally:
            self.devices["ur3"] = None
        self.var_status.set("Disconnected")
        self.btn_connect.configure(state="normal", text="Connect")
        self.btn_disconnect.configure(state="disabled")
        self.info.add("UR3: déconnecté proprement.")
        self._set_connected_ui(False, initialize=True)

    def _watch_period(self):
        try:
            arm = self.devices.get("ur3")
            ok = bool(arm and arm.is_connected() and arm.ping())
        except Exception:
            ok = False

        if ok:
            self._set_connected_ui(True, initialize=False)
            self.var_status.set("Connected")
        else:
            self._set_connected_ui(False, initialize=True)
            if self.devices.get("ur3"):
                self.info.add("UR3: connexion perdue.", level="warning")
                try: self.devices["ur3"].close()
                except Exception: pass
                self.devices["ur3"] = None
            self.var_status.set("Disconnected")
        self.after(WATCH_PERIOD_MS, self._watch_period)

    # -----------------------------------------------------------------------
    # Dashboard helpers
    # -----------------------------------------------------------------------
    def _call_dash(self, label: str, func):
        try:
            arm = self._get_ur3()
            resp = func(arm)
            txt = (resp or "").lower()
            if ("remote control mode" in txt) or ("reconnect to port 29999" in txt) or ("not allowed due to safety" in txt):
                self.info.add(f"UR3 {label} → {resp}")
                self._force_need_reconnect(reason=resp)
                return
            self.info.add(f"UR3 {label} → {resp}")
        except (RuntimeError, UR3ConnectionError) as e:
            self.info.add(f"UR3 {label} → ERREUR : {e}", level="error")
            self.var_status.set("Error")

    def on_power_on(self):  self._call_dash("power on",  lambda arm: arm.power_on())
    def on_power_off(self): self._call_dash("power off", lambda arm: arm.power_off())
    def on_brake_release(self): self._call_dash("brake release", lambda arm: arm.brake_release())

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
            self.var_program.set(prog)        # ex: "Loaded program: /programs/xxx.urp"
            self.var_prog_state.set(state)    # ex: "RUNNING", "STOPPED", "PAUSED"
            self.info.add(f"UR3 programme → {prog}")
            self.info.add(f"UR3 state → {state}")

        except (RuntimeError, UR3ConnectionError) as e:
            self.info.add(f"UR3 refresh modes → ERREUR : {e}", level="error")
            self.var_status.set("Error")

    # -----------------------------------------------------------------------
    # Programmes: état chargé / refresh / autoload
    # -----------------------------------------------------------------------
    def _extract_loaded_path(self, s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        return s.split(":", 1)[1].strip() if ":" in s else s

    def _current_loaded_path(self) -> str:
        return self._extract_loaded_path(self.var_program.get())

    def _on_program_selected(self, _event=None):
        if not self._combo_events_enabled():
            return
        try:
            self._get_ur3()
        except Exception:
            self.info.add("Sélection ignorée : UR3 non connecté.", level="warning")
            return
        self.on_load_selected_program()

    def on_refresh_programs(self):
        try:
            arm = self._get_ur3()
            progs = arm.list_programs()
            if not progs:
                self.info.add("UR3: aucun programme .urp trouvé sur /programs", level="warning")

            with self._combo_guard():
                self.cmb_programs["values"] = progs
                try:
                    loaded_line = arm.get_loaded_program()
                except Exception:
                    loaded_line = self.var_program.get()
                loaded_path = self._extract_loaded_path(loaded_line)
                if loaded_path and loaded_path in progs:
                    self.var_selected_program.set(loaded_path)
                else:
                    self.var_selected_program.set(loaded_path if loaded_path else (progs[0] if progs else ""))

            self.info.add(f"UR3: {len(progs)} programme(s) trouvé(s).")
        except (RuntimeError, UR3ConnectionError) as e:
            self.info.add(f"UR3 refresh programs → ERREUR : {e}", level="error")

    def on_load_selected_program(self):
        prog = self.var_selected_program.get().strip()
        if not prog:
            self.info.add("Load program → aucun programme sélectionné.", level="warning")
            return

        def _do(arm):
            resp = arm.load_program(prog)
            return f"load {prog} → {resp}"

        self._call_dash("load", _do)

        with self._combo_guard():
            self.var_selected_program.set(prog)

        self.after(150, self.on_refresh_modes)

    # -----------------------------------------------------------------------
    # Play / Pause / Stop
    # -----------------------------------------------------------------------
    def on_play(self):
        try:
            arm = self._get_ur3()
            loaded_path = self._current_loaded_path()
            prog_name = loaded_path.split("/")[-1] if loaded_path else ""
            low = prog_name.lower()
            if   "p1" in low: self._play_p1(arm)
            elif "p2" in low: self._play_p2(arm)
            elif "p3" in low: self._play_p3(arm)
            elif "p4" in low: self._play_p4(arm)
            else:             self._play_default(arm)

            before = arm.get_program_state()
            resp   = arm.play()
            self._set_state("running")
            self.btn_stop.configure(state="normal")
            after  = arm.get_program_state()
            self.info.add(f"UR3 play → state_before={before} ; play→{resp} ; state_after={after}")
        except (RuntimeError, UR3ConnectionError, ValueError) as e:
            self.info.add(f"UR3 play → ERREUR : {e}", level="error")
            self.var_status.set("Error")

    def on_pause(self):
        try:
            arm = self._get_ur3()
            if self._state == "running":
                resp = arm.pause()
                self.info.add(f"UR3 pause → {resp}")
                self._set_state("paused")
            elif self._state == "paused":
                resp = arm.play()
                self.info.add(f"UR3 continue (play) → {resp}")
                self._set_state("running")
            else:
                self.info.add("Pause ignorée (état idle).", level="warning")
                return
            self.after(120, self.on_refresh_modes)
        except (RuntimeError, UR3ConnectionError) as e:
            self.info.add(f"UR3 pause/continue → ERREUR : {e}", level="error")
            self.var_status.set("Error")

    def on_stop(self):
        self._call_dash("stop", lambda arm: arm.stop())
        self._set_state("idle")

    # -----------------------------------------------------------------------
    # Scénarios P1 / P2 / P3 / P4
    # -----------------------------------------------------------------------
    def _play_p1(self, arm: UR3):
        vial_id, group = self._get_selected_vial_any()
        if not vial_id:
            self.info.add("Play (P1) → aucune vial E* ni F* sélectionnée.", level="warning")
            raise RuntimeError("Vial requise pour P1")

        vnum = self._vial_id_to_number(vial_id)
        self._ensure_scale_door_open()
        if not self._is_pan_empty():
            self.info.add("Play (P1) → La pan n'est pas vide. Merci de vider la balance, puis relance.", level="warning")
            raise RuntimeError("Pan non vide")
        arm.stop()
        arm.set_vials_nb(vnum)
        self.info.add(f"UR3 RTDE: VialsNB ← {vnum} ({vial_id}, groupe {group})")

    def _play_p2(self, arm: UR3):
        storage_id = self.get_selected_storage()
        if not storage_id:
            self.info.add("Play (P2) → aucun Storage sélectionné (S1..S4).", level="warning")
            raise RuntimeError("Storage requis")
        dnum = self._storage_id_to_number(storage_id)
        if self._is_dispenser_present():
            name = self._get_scale_dispenser_name()
            self.info.add(f"Play (P2) → Un dispenser est déjà présent sur la balance ({name or '—'}). Retire-le puis relance.", level="warning")
            raise RuntimeError("Dispenser déjà présent")
        arm.stop()
        arm.set_disp_nb(int(dnum))
        self.info.add(f"UR3 RTDE: DispNB ← {dnum} (Storage {storage_id})")

    def _play_p3(self, arm: UR3):
        vial_id, group = self._get_selected_vial_any()
        if not vial_id:
            self.info.add("Play (P3) → aucune vial E* ni F* sélectionnée.", level="warning")
            raise RuntimeError("Vial requise pour P3")
        vnum = self._vial_id_to_number(vial_id)
        self._ensure_scale_door_open()
        if self._is_pan_empty():
            self.info.add("Play (P3) → La pan est pas vide. Le mouvement ne sert à rien.", level="warning")
            raise RuntimeError("Pan vide → inutile")
        arm.stop()
        arm.set_vials_nb(vnum)  # GPii[20]
        self.info.add(f"UR3 RTDE: VialsNB ← {vnum} ({vial_id}, groupe {group})")

    def _play_p4(self, arm: UR3):
        name = self._get_scale_dispenser_name()
        if not name:
            self.info.add("Play (P4) → Aucun dosing head détecté (nom vide). Place un dispenser puis relance.", level="warning")
            raise RuntimeError("Pas de dispenser")
        storage_id, dnum = self._find_storage_by_substance_label(name)
        if not storage_id or dnum is None:
            self.info.add(f"Play (P4) → Substance '{name}' introuvable dans STORAGE_CONFIG['labels'].", level="warning")
            raise RuntimeError("Label inconnu")
        arm.stop()
        arm.set_disp_nb(int(dnum))  # GPii[21]
        self.info.add(f"UR3 RTDE: DispNB ← {dnum} (via label '{name}', storage {storage_id})")

    def _play_default(self, arm: UR3):
        vial_id, group = self._get_selected_vial_any()
        arm.stop()
        if vial_id:
            vnum = self._vial_id_to_number(vial_id)
            arm.set_vials_nb(vnum)
            self.info.add(f"UR3 RTDE: VialsNB ← {vnum} ({vial_id}, groupe {group})")

    # -----------------------------------------------------------------------
    # Accès Vials / Storage (UI)
    # -----------------------------------------------------------------------
    def get_selected_vial_e(self) -> str | None:
        return self.win_vials.get_selected_vial_e() if self.win_vials else None

    def get_selected_vial_f(self) -> str | None:
        return self.win_vials.get_selected_vial_f() if self.win_vials else None

    def _get_selected_vial_any(self) -> tuple[str | None, str]:
        v = self.get_selected_vial_e()
        if v: return v, "E"
        v = self.get_selected_vial_f()
        if v: return v, "F"
        return None, ""

    def get_selected_storage(self) -> str | None:
        return self.win_storage.get_selected_storage() if self.win_storage else None

    # -----------------------------------------------------------------------
    # Balance (porte / plateau / dispenser)
    # -----------------------------------------------------------------------
    def _is_scale_door_open(self) -> bool:
        wm = self._get_scale()
        if not wm:
            return False
        try:
            pos = wm.get_door_positions() or {}
            if not isinstance(pos, dict):
                return False
            def _to_int(v):
                try:
                    return int(v) if str(v).isdigit() else int(float(v))
                except Exception:
                    return 0
            return any(_to_int(v) > 0 for v in pos.values())
        except Exception:
            return False

    def _ensure_scale_door_open(self):
        wm = self._get_scale()
        if not wm:
            self.info.add("Balance non connectée → je ne peux pas ouvrir la porte.", level="warning")
            return
        try:
            if self._is_scale_door_open():
                self.info.add("Porte balance déjà ouverte.")
                return
            resp = wm.open_door()
            self.info.add(f"Open door (balance) → {resp}")
        except Exception as e:
            self.info.add(f"Open door (balance) a échoué: {e}", level="error")

    def _is_pan_empty(self) -> bool:
        wm = self._get_scale()
        if not wm:
            self.info.add("Balance non connectée → impossible de vérifier que la pan est vide.", level="warning")
            return False  # par prudence on bloque
        try:
            min_mg = float(SCALE_CONFIG.get("vial_presence_min_mg", 1000.0))
            present, stats = wm.is_pan_present(min_present_mg=min_mg, samples=8, sleep_s=0.04)
            mean_mg   = (stats.get("mean_gross_g") or 0.0) * 1000.0
            thr_mg    = (stats.get("threshold_g") or (min_mg/1000.0)) * 1000.0
            std_mg    = (stats.get("std_gross_g") or 0.0) * 1000.0
            n_samples = int(stats.get("n") or 0)
            if present:
                self.info.add(f"Plateau OCCUPÉ (Gross mean={mean_mg:.1f} mg, σ={std_mg:.1f} mg, seuil={thr_mg:.1f} mg, n={n_samples})", level="warning")
                return False
            else:
                self.info.add(f"Plateau VIDE (Gross mean={mean_mg:.1f} mg, σ={std_mg:.1f} mg, seuil={thr_mg:.1f} mg, n={n_samples})")
                return True
        except Exception as e:
            self.info.add(f"Balance: is_pan_present() a échoué → {e}", level="error")
            return False

    def _get_scale_dispenser_name(self) -> str:
        wm = self._get_scale()
        if not wm:
            return ""
        try:
            return (wm.get_dosing_head_name() or "").strip()
        except Exception:
            return ""

    def _is_dispenser_present(self) -> bool:
        return bool(self._get_scale_dispenser_name())

    def _norm_label(self, s: str) -> str:
        return " ".join(str(s or "").strip().lower().split())

    def _find_storage_by_substance_label(self, substance_name: str) -> tuple[str | None, int | None]:
        labels = STORAGE_CONFIG.get("labels", {}) or {}
        id_to_number = STORAGE_CONFIG.get("id_to_number", {}) or {}
        target = self._norm_label(substance_name)
        if not target or not isinstance(labels, dict):
            return None, None
        for sid, lab in labels.items():
            if self._norm_label(lab) == target:
                try:
                    num = int(id_to_number.get(sid, sid[1:] if isinstance(sid, str) and sid.upper().startswith("S") else sid))
                    return str(sid), num
                except Exception:
                    pass
        return None, None
