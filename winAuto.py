#!/usr/bin/env python3

# BEC - November 2025 
# Python GUI (Tkinter) for the APD
# Mode Auto : séquence P1 → P4 avec dosing
#-------------------------------------------------------------------------------
import tkinter as tk
import time

# chemins .urp – adapte si besoin
P1_PROGRAM = "/programs/00Main/P1Bastien.urp"
P2_PROGRAM = "/programs/00Main/P2Bastien.urp"
P3_PROGRAM = "/programs/00Main/P3Bastien.urp"
P4_PROGRAM = "/programs/00Main/P4Bastien.urp"


class WinAuto(tk.Frame):
    def __init__(self, parent, info_win, devices):
        super().__init__(parent)
        self.parent = parent
        self.win_info = info_win
        self.devices = devices

        # Références vers les widgets du Mode Man
        self.win_robot = None     # WinRobotArm (pour P1..P4)
        self.win_balance = None   # WinBalance (pour le dosing job)

        # État de la séquence auto
        self._seq_running = False
        self._seq_after_id = None

        self._build()

    # ------------------------------------------------------------------
    # Wiring avec le Mode Man (appelé depuis winMode dans win.py)
    # ------------------------------------------------------------------
    def attach_manual_views(self, robot_window, balance_window):
        """
        robot_window : instance de WinRobotArm (onglet Mode Man)
        balance_window : instance de WinBalance (onglet Mode Man)
        """
        self.win_robot = robot_window
        self.win_balance = balance_window

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)

        lbl = tk.Label(
            self,
            text="Mode automatique : test boucle complète P1 → P4 avec dosing",
            font=("TkDefaultFont", 10, "bold"),
        )
        lbl.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=(5, 2))

        self.btn_full_loop = tk.Button(
            self,
            text="Test boucle complète",
            width=22,
            command=self.on_test_full_loop,
        )
        self.btn_full_loop.grid(row=1, column=0, padx=5, pady=5, sticky="w")

        self.lbl_status = tk.Label(self, text="", anchor="w")
        self.lbl_status.grid(row=1, column=1, padx=5, pady=5, sticky="w")

    # ------------------------------------------------------------------
    # Helpers logs / status
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

    def _set_status(self, msg):
        try:
            self.lbl_status.configure(text=msg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers connexion auto UR3 / balance
    # ------------------------------------------------------------------
    def _ensure_ur3_connected(self):
        """S'assure que l'UR3 est connecté. Utilise exactement la logique du bouton 'Connect' de WinRobotArm."""
        # Si la clé n'existe pas, on la crée à None pour être tranquille
        if "ur3" not in self.devices:
            self.devices["ur3"] = None

        arm = self.devices.get("ur3")

        # Déjà connecté → OK
        if arm and getattr(arm, "is_connected", lambda: False)():
            return True

        if not self.win_robot:
            self._log(
                "Mode Auto: WinRobotArm non initialisé, impossible de connecter automatiquement l'UR3.",
                level="error",
            )
            return False

        self._log("Mode Auto: UR3 non connecté, je lance 'Connect' dans le Mode Man…", level="info")

        # On utilise EXACTEMENT la même logique que le bouton "Connect"
        try:
            # C'est cette méthode qui fait : _make_ur3() + arm.connect() + devices['ur3'] = arm + refresh
            self.win_robot.on_connect()
        except Exception as e:
            self._log(f"Mode Auto: erreur en appelant win_robot.on_connect(): {e}", level="error")
            return False

        # Relecture après connexion
        arm = self.devices.get("ur3")
        if arm and getattr(arm, "is_connected", lambda: False)():
            self._log("Mode Auto: UR3 connecté automatiquement.", level="info")
            return True

        self._log(
            "Mode Auto: impossible de connecter automatiquement l'UR3. "
            "Connecte-le manuellement dans l'onglet 'Mode Man'.",
            level="error",
        )
        return False

    def _ensure_scale_connected(self):
        """S'assure que la balance est connectée. Utilise la logique du bouton 'Connect' de WinBalance."""
        if "scale" not in self.devices:
            self.devices["scale"] = None

        wm = self.devices.get("scale")

        # Déjà connectée → OK
        if wm and getattr(wm, "is_connected", lambda: False)():
            return True

        if not self.win_balance:
            self._log(
                "Mode Auto: WinBalance non initialisé, impossible de connecter automatiquement la balance.",
                level="error",
            )
            return False

        self._log("Mode Auto: balance non connectée, je lance 'Connect' dans le Mode Man…", level="info")

        try:
            # WinBalance.on_connect() crée WM(), fait connect(), et met devices['scale'] = wm
            self.win_balance.on_connect()
        except Exception as e:
            self._log(f"Mode Auto: erreur en appelant win_balance.on_connect(): {e}", level="error")
            return False

        wm = self.devices.get("scale")
        if wm and getattr(wm, "is_connected", lambda: False)():
            self._log("Mode Auto: balance connectée automatiquement.", level="info")
            return True

        self._log(
            "Mode Auto: impossible de connecter automatiquement la balance. "
            "Connecte-la manuellement dans l'onglet 'Mode Man'.",
            level="error",
        )
        return False

    # ------------------------------------------------------------------
    # Entrée de la séquence
    # ------------------------------------------------------------------
    def on_test_full_loop(self):
        if self._seq_running:
            self._log("Mode Auto: une séquence est déjà en cours.", level="warning")
            return
        
        if not self.win_robot or not self.win_balance:
            self._log(
                "Mode Auto: références win_robot / win_balance manquantes (wiring winMode).",
                level="error",
            )
            return

        # Connexion auto UR3 + balance
        if not self._ensure_ur3_connected():
            return
        if not self._ensure_scale_connected():
            return

        if not self.win_robot or not self.win_balance:
            self._log(
                "Mode Auto: références win_robot / win_balance manquantes (wiring winMode).",
                level="error",
            )
            return

        self._seq_running = True
        self._seq_after_id = None
        self._seq_seen_running = False

        self._set_status("Séquence P1→P4 en cours…")
        self._log("Mode Auto: démarrage de la séquence complète P1 → P4 avec dosing.", level="info")

        self._start_p1()

    # ------------------------------------------------------------------
    # Gestion fin / abort
    # ------------------------------------------------------------------
    def _abort_sequence(self, reason):
        if not self._seq_running:
            return
        self._seq_running = False
        if self._seq_after_id is not None:
            try:
                self.after_cancel(self._seq_after_id)
            except Exception:
                pass
            self._seq_after_id = None
        self._set_status("Séquence interrompue.")
        self._log(f"Mode Auto: séquence interrompue. {reason}", level="error")

    def _finish_sequence(self):
        if not self._seq_running:
            return
        self._seq_running = False
        self._seq_after_id = None
        self._set_status("Séquence complète terminée.")
        self._log("Mode Auto: séquence complète terminée (P1→P4 + dosing).", level="info")

    # ------------------------------------------------------------------
    # Étapes robot : P1 / P2 / P3 / P4
    # ------------------------------------------------------------------
    def _check_load_ok(self, resp, step_name, program_path, human_name=None):
        """
        Vérifie la réponse de load_program().
        - Log standardisé
        - Si 'File not found' détecté → on ABORT et on retourne False.
        """
        label = human_name or program_path
        self._log(f"Mode Auto: lancement programme {label} ({step_name}).")
        self._log(f"UR3 load → {resp}", level="info")

        if isinstance(resp, str) and "FILE NOT FOUND" in resp.upper():
            self._abort_sequence(
                f"Programme {step_name} introuvable sur le robot ({program_path}). "
                "Vérifie le chemin / le nom du .urp."
            )
            return False

        return True
    
    def _start_p1(self):
        """Charge P1Bastien.urp, fait les vérifs comme en manuel, puis démarre le programme."""
        if not self._seq_running:
            return
        arm = self.devices.get("ur3")
        if not (arm and arm.is_connected()):
            self._abort_sequence("UR3 non connecté au lancement de P1.")
            return
        try:
            resp = arm.load_program(P1_PROGRAM)
            if not self._check_load_ok(resp, "P1", P1_PROGRAM, "P1Bastien.urp"):
                return  # on n'appelle pas play() si le fichier est introuvable
            self._log("Mode Auto: lancement programme P1Bastien.urp (P1).")
            self._log(f"UR3 load → {resp}", level="info")

            # Aligner l'UI robot sur le programme chargé
            try:
                self.win_robot.on_refresh_programs()
            except Exception:
                pass

            # Vérifs préalables P1 (vial sélectionnée, porte, plateau vide, RTDE…)
            self.win_robot._play_p1(arm)

            # Démarrer le programme UR
            before = arm.get_program_state()
            play_resp = arm.play()
            self._log(
                f"Mode Auto: démarrage programme P1 (state_before={before} ; play→{play_resp})",
                level="info",
            )

            # Mettre l'UI robot en 'running' et laisser son watcher interne tourner
            try:
                self.win_robot._set_state("running")
                self.win_robot._start_run_watch()
            except Exception:
                pass

            # Attendre la fin P1 avant de lancer P2
            self._wait_robot_stopped(step_name="P1", next_step="P2")

        except Exception as e:
            self._abort_sequence(f"erreur lancement programme P1: {e}")

    def _start_p2(self):
        """Charge P2Bastien.urp, vérifs P2, lance, puis attend STOPPED → dosing."""
        if not self._seq_running:
            return
        arm = self.devices.get("ur3")
        if not (arm and arm.is_connected()):
            self._abort_sequence("UR3 non connecté au lancement de P2.")
            return
        try:
            resp = arm.load_program(P2_PROGRAM)
            if not self._check_load_ok(resp, "P2", P2_PROGRAM, "P2Bastien.urp"):
                return
            self._log("Mode Auto: lancement programme P2Bastien.urp (P2).")
            self._log(f"UR3 load → {resp}", level="info")

            try:
                self.win_robot.on_refresh_programs()
            except Exception:
                pass

            # Vérifs préalables P2 (storage sélectionné, dispenser non présent sur pan, RTDE…)
            self.win_robot._play_p2(arm)

            before = arm.get_program_state()
            play_resp = arm.play()
            self._log(
                f"Mode Auto: démarrage programme P2 (state_before={before} ; play→{play_resp})",
                level="info",
            )

            try:
                self.win_robot._set_state("running")
                self.win_robot._start_run_watch()
            except Exception:
                pass

            self._wait_robot_stopped(step_name="P2", next_step="DOSING")

        except Exception as e:
            self._abort_sequence(f"erreur lancement programme P2: {e}")

    def _start_p3(self):
        """Charge P3Bastien.urp, vérifs P3, lance, puis attend STOPPED → P4."""
        if not self._seq_running:
            return
        arm = self.devices.get("ur3")
        if not (arm and arm.is_connected()):
            self._abort_sequence("UR3 non connecté au lancement de P3.")
            return
        try:
            resp = arm.load_program(P3_PROGRAM)
            if not self._check_load_ok(resp, "P3", P3_PROGRAM, "P3Bastien.urp"):
                return
            self._log("Mode Auto: lancement programme P3Bastien.urp (P3).")
            self._log(f"UR3 load → {resp}", level="info")

            try:
                self.win_robot.on_refresh_programs()
            except Exception:
                pass

            # Vérifs préalables P3 (vial sélectionnée, porte ouverte, pan NON vide…)
            self.win_robot._play_p3(arm)

            before = arm.get_program_state()
            play_resp = arm.play()
            self._log(
                f"Mode Auto: démarrage programme P3 (state_before={before} ; play→{play_resp})",
                level="info",
            )

            try:
                self.win_robot._set_state("running")
                self.win_robot._start_run_watch()
            except Exception:
                pass

            self._wait_robot_stopped(step_name="P3", next_step="P4")

        except Exception as e:
            self._abort_sequence(f"erreur lancement programme P3: {e}")

    def _start_p4(self):
        """Charge P4Bastien.urp, vérifs P4, lance, puis attend STOPPED → fin séquence."""
        if not self._seq_running:
            return
        arm = self.devices.get("ur3")
        if not (arm and arm.is_connected()):
            self._abort_sequence("UR3 non connecté au lancement de P4.")
            return
        try:
            resp = arm.load_program(P4_PROGRAM)
            if not self._check_load_ok(resp, "P4", P4_PROGRAM, "P4Bastien.urp"):
                return
            self._log("Mode Auto: lancement programme P4Bastien.urp (P4).")
            self._log(f"UR3 load → {resp}", level="info")

            try:
                self.win_robot.on_refresh_programs()
            except Exception:
                pass

            # Vérifs préalables P4 (dosing head présent et reconnu…)
            self.win_robot._play_p4(arm)

            before = arm.get_program_state()
            play_resp = arm.play()
            self._log(
                f"Mode Auto: démarrage programme P4 (state_before={before} ; play→{play_resp})",
                level="info",
            )

            try:
                self.win_robot._set_state("running")
                self.win_robot._start_run_watch()
            except Exception:
                pass

            self._wait_robot_stopped(step_name="P4", next_step=None)

        except Exception as e:
            self._abort_sequence(f"erreur lancement programme P4: {e}")

    # ------------------------------------------------------------------
    # Attente fin programme UR (STOPPED) en pollant programState
    # ------------------------------------------------------------------
    def _wait_robot_stopped(self, step_name, next_step):
        """
        Surveille programState jusqu'à ce qu'on voie STOPPED *après* avoir vu RUNNING/PAUSED,
        ou bien après un petit timeout (pour les programmes ultra courts).
        """
        if not self._seq_running:
            return

        start_ts = time.monotonic()
        seen_active = False   # a-t-on déjà vu RUNNING ou PAUSED pour ce programme ?

        def _poll():
            nonlocal seen_active

            if not self._seq_running:
                return

            arm = self.devices.get("ur3")
            if not (arm and arm.is_connected()):
                self._abort_sequence("UR3 déconnecté en cours de programme.")
                return

            try:
                raw = arm.get_program_state()  # ex: "programState: PLAYING", "STOPPED P1Bastien.urp", ...
            except Exception as e:
                self._abort_sequence(f"Erreur lecture état programme ({step_name}): {e}")
                return

            # Normalisation via la même fonction que WinRobotArm
            try:
                canon = self.win_robot._canon_prog_state(raw)
            except Exception:
                canon = str(raw or "").strip().upper()

            # On reflète l'état brut dans le label WinRobotArm (debug)
            try:
                self.win_robot.var_prog_state.set(raw)
            except Exception:
                pass

            # Si on voit RUNNING ou PAUSED, on sait que le programme est vraiment parti
            if canon in ("RUNNING", "PAUSED"):
                seen_active = True

            if canon == "STOPPED":
                now = time.monotonic()

                # Cas 1 : STOPPED trop tôt, sans jamais avoir vu RUNNING/PAUSED
                # → on laisse une fenêtre (~2 s) pour laisser le temps au programme de démarrer.
                if not seen_active and (now - start_ts) < 2.0:
                    self._seq_after_id = self.after(200, _poll)
                    return

                # Cas 2 : soit on a déjà vu RUNNING, soit le timeout est passé
                # → on considère le programme comme terminé.
                self._log(f"Mode Auto: programme {step_name} terminé (STOPPED).", level="info")
                try:
                    self.win_robot._set_state("idle")
                except Exception:
                    pass

                # Enchaîner sur l'étape suivante
                if next_step == "P2":
                    self._start_p2()
                elif next_step == "DOSING":
                    self._start_dosing()
                elif next_step == "P3":
                    self._start_p3()
                elif next_step == "P4":
                    self._start_p4()
                else:
                    self._finish_sequence()
                return

            # Sinon (toujours en RUNNING/PAUSED/UNKNOWN) → re-poller plus tard
            self._seq_after_id = self.after(700, _poll)

        # Premier sondage un peu différé pour éviter de lire l'état 'STOPPED' juste avant le démarrage
        self._seq_after_id = self.after(300, _poll)

    # ------------------------------------------------------------------
    # Étape Dosing : démarrer job + attendre fin du thread notifications
    # ------------------------------------------------------------------
    def _start_dosing(self):
        """Lance le dosing job (comme le bouton 'Start dosing job') puis attend la fin."""
        if not self._seq_running:
            return
        wm = self.devices.get("scale")
        if not (wm and wm.is_connected()):
            self._abort_sequence("Balance non connectée au lancement du dosing job.")
            return

        self._log("Mode Auto: démarrage du dosing job.", level="info")

        # Lance exactement la même logique que le bouton manuel
        try:
            self.win_balance.on_start_dosing_job()
        except Exception as e:
            self._abort_sequence(f"erreur lancement dosing job: {e}")
            return

        # Laisser un petit délai pour que WinBalance puisse créer le thread
        self.after(300, self._check_dosing_started)

    def _check_dosing_started(self):
        """Vérifie que le thread de notifications dosing a réellement démarré."""
        if not self._seq_running:
            return
        t = getattr(self.win_balance, "_dosing_thread", None)
        if t is None or not t.is_alive():
            # Pas de thread → le job ne s'est probablement pas lancé
            self._abort_sequence(
                "dosing job non démarré (vérifie la présence de la vial et du dosing head)."
            )
            return

        self._log("Mode Auto: dosing job en cours… attente de fin avant P3.", level="info")
        self._wait_dosing_finished()

    def _wait_dosing_finished(self):
        """Poll sur l'état du thread _dosing_thread jusqu'à sa fin."""
        if not self._seq_running:
            return

        t = getattr(self.win_balance, "_dosing_thread", None)
        if t is None:
            # plus de thread → on considère que c'est fini
            self._on_dosing_done()
            return

        if t.is_alive():
            # Toujours en cours → replanifier un check
            self._seq_after_id = self.after(1000, self._wait_dosing_finished)
        else:
            self._on_dosing_done()

    def _on_dosing_done(self):
        """Appelé quand le thread de notifications dosing est terminé (job terminé)."""
        self._log("Mode Auto: dosing job terminé (Fin DosingAutomation détecté).", level="info")

        # Petite marge de sécurité avant d'ouvrir la porte / lancer P3
        self.after(1000, self._start_p3)
