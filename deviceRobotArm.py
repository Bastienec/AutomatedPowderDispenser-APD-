#!/usr/bin/env python3
# BEC - November 2025
#-------------------------------------------------------------------------------
# Client simple pour piloter un UR3 via Ethernet (Dashboard + Script)
#-------------------------------------------------------------------------------
from __future__ import annotations
from typing import Sequence, Optional, List

import socket
import threading

try:
    import rtde_io  # from ur-rtde
except ImportError:
    rtde_io = None

from config import UR3_CONFIG


class UR3ConnectionError(RuntimeError):
    """Erreur de connexion ou de communication avec le robot UR3."""


class _UR3Client:
    """
    Client bas niveau pour UR3, utilisant :
      - le Dashboard Server (port 29999, texte)
      - l'interface Script (port 30002, URScript)
      - SFTP (port 22) pour lister les programmes .urp sur /programs
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.ip: str = cfg.get("ip", "192.168.0.5")
        self.script_port: int = int(cfg.get("script_port", 30002))
        self.dashboard_port: int = int(cfg.get("dashboard_port", 29999))
        self.default_a: float = float(cfg.get("default_a", 1.0))
        self.default_v: float = float(cfg.get("default_v", 0.5))

        # SFTP (pour listes de programmes)
        self.sftp_user: str = cfg.get("sftp_user", "root")
        self.sftp_password: str = cfg.get("sftp_password", "")
        self.programs_dir: str = cfg.get("programs_dir", "/programs")
        self.sftp_port: int = int(cfg.get("sftp_port", 22))

        self._dash_sock: Optional[socket.socket] = None
        self._script_sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._rtde_io = None  # client RTDE IO 

    # ------------------------------------------------------------------
    # Gestion connexions
    # ------------------------------------------------------------------
    def connect(self, timeout_s: float = 3.0) -> str:
        """
        Ouvre les connexions Dashboard + Script.
        Retourne la bannière du dashboard (souvent 'Connected: Universal Robots Dashboard Server').
        """
        self.close()

        try:
            dash = socket.create_connection((self.ip, self.dashboard_port), timeout=timeout_s)
            script = socket.create_connection((self.ip, self.script_port), timeout=timeout_s)
            dash.settimeout(timeout_s)
            script.settimeout(timeout_s)
            self._dash_sock = dash
            self._script_sock = script
        except OSError as e:
            self.close()
            raise UR3ConnectionError(f"Erreur connexion UR3 ({self.ip}): {e}") from e

        banner = ""
        try:
            data = self._dash_sock.recv(1024)
            banner = data.decode(errors="ignore").strip()
        except OSError:
            # certains firmwares n'envoient rien, on ignore
            banner = ""

        return banner

    def close(self) -> None:
        """Ferme les sockets si ouverts."""
        for attr in ("_dash_sock", "_script_sock"):
            s = getattr(self, attr, None)
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
            setattr(self, attr, None)

    def is_connected(self) -> bool:
        return self._dash_sock is not None and self._script_sock is not None

    # ------------------------------------------------------------------
    # Helpers bas niveau
    # ------------------------------------------------------------------
    def _ensure_dash(self) -> socket.socket:
        if self._dash_sock is None:
            raise UR3ConnectionError("Dashboard non connecté.")
        return self._dash_sock

    def _ensure_script(self) -> socket.socket:
        if self._script_sock is None:
            raise UR3ConnectionError("Interface script non connectée.")
        return self._script_sock

    def send_dashboard(self, cmd: str, expect_reply: bool = True) -> str:
        """
        Envoie une commande Dashboard, retourne la réponse (ligne).
        Exemple de commande : 'robotmode', 'play', 'stop', 'power on', etc.
        """
        with self._lock:
            s = self._ensure_dash()
            payload = (cmd.strip() + "\n").encode("ascii", errors="ignore")
            try:
                s.sendall(payload)
            except OSError as e:
                raise UR3ConnectionError(f"Erreur envoi Dashboard: {e}") from e

            if not expect_reply:
                return ""

            try:
                data = s.recv(4096)
            except OSError as e:
                raise UR3ConnectionError(f"Erreur lecture Dashboard: {e}") from e

        return data.decode(errors="ignore").strip()

    def send_script(self, program: str) -> None:
        """
        Envoie une (ou plusieurs) lignes URScript sur le port script.
        URScript s'exécute dès réception.
        """
        with self._lock:
            s = self._ensure_script()
            if not program.endswith("\n"):
                program = program + "\n"
            payload = program.encode("ascii", errors="ignore")
            try:
                s.sendall(payload)
            except OSError as e:
                raise UR3ConnectionError(f"Erreur envoi Script: {e}") from e

    # ------------------------------------------------------------------
    # API Dashboard de base
    # ------------------------------------------------------------------
    def ping(self) -> bool:
        """Test grossier : on interroge le robotmode, si ça répond → OK."""
        try:
            resp = self.send_dashboard("robotmode", expect_reply=True)
            return bool(resp)
        except UR3ConnectionError:
            return False

    def get_robot_mode(self) -> str:
        """Retourne le mode robot (ex: 'Robotmode: RUNNING')."""
        return self.send_dashboard("robotmode", expect_reply=True)

    def get_safety_mode(self) -> str:
        """Retourne le mode sécurité (ex: 'Safetymode: NORMAL')."""
        return self.send_dashboard("safetymode", expect_reply=True)

    def power_on(self) -> str:
        return self.send_dashboard("power on", expect_reply=True)

    def power_off(self) -> str:
        return self.send_dashboard("power off", expect_reply=True)

    def brake_release(self) -> str:
        return self.send_dashboard("brake release", expect_reply=True)

    def play(self) -> str:
        return self.send_dashboard("play", expect_reply=True)

    def stop(self) -> str:
        return self.send_dashboard("stop", expect_reply=True)
    
    def get_loaded_program(self) -> str:
        return self.send_dashboard("get loaded program", expect_reply=True)

    def get_program_state(self) -> str:
        return self.send_dashboard("programState", expect_reply=True)

    def load_program(self, name: str) -> str:
        """
        Charge un programme .urp présent sur le contrôleur (ex: '/programs/MonProg.urp'
        ou '/programs/SousDossier/MonProg.urp').
        """
        return self.send_dashboard(f"load {name}", expect_reply=True)

    # ------------------------------------------------------------------
    # Listing des programmes via SFTP
    # ------------------------------------------------------------------
    def list_programs(self, recursive: bool = True) -> List[str]:
        """
        Liste les .urp sur le contrôleur via SFTP (SSH:22) en version compacte.
        Pré-req: pip install paramiko
        """
        try:
            import paramiko, stat
        except Exception as e:
            raise UR3ConnectionError(
                "Le listing des programmes nécessite 'paramiko'. "
                "Installe-le avec: pip install paramiko"
            ) from e

        host = self.ip
        port = int(self.sftp_port or 22)
        user = self.sftp_user or "ur"
        pwd  = self.sftp_password or ""
        base = (self.programs_dir or "/programs").rstrip("/") or "/programs"

        transport = None
        sftp = None
        results: List[str] = []

        try:
            # Connexion SFTP simple
            transport = paramiko.Transport((host, port))
            # (Optionnel) timeouts courts côté transport
            # paramiko n'expose pas directement un timeout après .Transport(host,port)
            # mais ça reste OK dès lors que 22 répond rapidement.
            transport.connect(username=user, password=pwd)
            sftp = paramiko.SFTPClient.from_transport(transport)

            def _walk(dir_path: str):
                for attr in sftp.listdir_attr(dir_path):
                    name = attr.filename
                    full = f"{dir_path}/{name}".replace("//", "/")
                    if stat.S_ISDIR(attr.st_mode):
                        if recursive:
                            _walk(full)
                    else:
                        if name.lower().endswith(".urp"):
                            results.append(full)

            _walk(base)
            results.sort()
            return results

        except Exception as e:
            raise UR3ConnectionError(
                f"Echec SFTP vers {host}:{port} (user={user}): {e}"
            ) from e

        finally:
            try:
                if sftp: sftp.close()
            finally:
                if transport: transport.close()

    # ------------------------------------------------------------------
    # RTDE IO : accès aux GPii[0..23] (input integer registers)
    # ------------------------------------------------------------------
    def _ensure_rtde_io(self):
        """Crée le client RTDE IO si besoin."""
        if rtde_io is None:
            raise UR3ConnectionError(
                "rtde_io non disponible. Installe 'ur-rtde' (pip install ur-rtde)."
            )
        if self._rtde_io is None:
            try:
                # RTDE IO utilise le port 30004 par défaut
                self._rtde_io = rtde_io.RTDEIOInterface(self.ip)
            except Exception as e:
                raise UR3ConnectionError(f"Echec connexion RTDE IO ({self.ip}): {e}") from e
        return self._rtde_io

    def set_input_int_register_rtde(self, index: int, value: int) -> None:
        """
        Écrit dans un GPii[n] via RTDE (Input Int Register).
        index: 0..23 → GPii[0..23]
        """
        idx = int(index)
        if not (0 <= idx <= 23):
            raise UR3ConnectionError("index input_int_register hors bornes (0..23).")
        io = self._ensure_rtde_io()
        io.setInputIntRegister(idx, int(value))


#-------------------------------------------------------------------------------
# Façade simple utilisée par la GUI (WinRobotArm)
#-------------------------------------------------------------------------------
class UR3:
    """
    Facade simple autour de _UR3Client pour être utilisée depuis la GUI.
    """
    def __init__(self, **override):
        cfg = dict(UR3_CONFIG)
        cfg.update(override)
        self._impl = _UR3Client(cfg)

    # Connexion / état
    def connect(self, *a, **k): return self._impl.connect(*a, **k)
    def close(self):             return self._impl.close()
    def is_connected(self):      return self._impl.is_connected()
    def ping(self):              return self._impl.ping()

    # Dashboard
    def get_robot_mode(self):    return self._impl.get_robot_mode()
    def get_safety_mode(self):   return self._impl.get_safety_mode()
    def power_on(self):          return self._impl.power_on()
    def power_off(self):         return self._impl.power_off()
    def brake_release(self):     return self._impl.brake_release()
    def play(self):              return self._impl.play()
    def stop(self):              return self._impl.stop()
    def get_loaded_program(self):  return self._impl.get_loaded_program()
    def get_program_state(self):   return self._impl.get_program_state()
    def load_program(self, name: str): return self._impl.load_program(name)

    # Script brut (URScript)
    def send_script(self, program: str) -> None: return self._impl.send_script(program)

    # Listing de programmes
    def list_programs(self, *a, **k): return self._impl.list_programs(*a, **k)

    def set_input_int_register_rtde(self, *a, **k): return self._impl.set_input_int_register_rtde(*a, **k)
