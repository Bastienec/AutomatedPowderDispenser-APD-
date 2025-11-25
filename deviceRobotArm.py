#!/usr/bin/env python3
from __future__ import annotations
from typing import Optional, List
import socket
import threading

try:
    import rtde_io  # from ur-rtde
except ImportError:
    rtde_io = None

from config import UR3_CONFIG

class UR3ConnectionError(RuntimeError):
    pass

class _UR3Client:
    """
    Minimal: Dashboard (29999) + RTDE IO (30004) + SFTP listing.
    Pas de socket Script, pas de helpers URScript.
    """
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.ip: str = cfg.get("ip", "192.168.0.5")
        self.dashboard_port: int = int(cfg.get("dashboard_port", 29999))

        # SFTP listing
        self.sftp_user: str = cfg.get("sftp_user", "root")
        self.sftp_password: str = cfg.get("sftp_password", "")
        self.programs_dir: str = cfg.get("programs_dir", "/programs")
        self.sftp_port: int = int(cfg.get("sftp_port", 22))

        # RTDE
        self.rtde_register_default: int = int(cfg.get("rtde_input_register", 20))

        self._dash_sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._rtde_io = None  # RTDEIOInterface

    # --- Connexion Dashboard ---
    def connect(self, timeout_s: float = 3.0) -> str:
        self.close()
        try:
            dash = socket.create_connection((self.ip, self.dashboard_port), timeout=timeout_s)
            dash.settimeout(timeout_s)
            self._dash_sock = dash
        except OSError as e:
            self.close()
            raise UR3ConnectionError(f"Erreur connexion UR3 ({self.ip}): {e}") from e

        banner = ""
        try:
            data = self._dash_sock.recv(1024)
            banner = data.decode(errors="ignore").strip()
        except OSError:
            banner = ""
        return banner

    def close(self) -> None:
        s = self._dash_sock
        if s is not None:
            try: s.close()
            except OSError: pass
        self._dash_sock = None

    def is_connected(self) -> bool:
        return self._dash_sock is not None

    # --- Dashboard ---
    def _ensure_dash(self) -> socket.socket:
        if self._dash_sock is None:
            raise UR3ConnectionError("Dashboard non connecté.")
        return self._dash_sock

    def send_dashboard(self, cmd: str, expect_reply: bool = True) -> str:
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

    def ping(self) -> bool:
        try:
            return bool(self.send_dashboard("robotmode", expect_reply=True))
        except UR3ConnectionError:
            return False

    def get_robot_mode(self) -> str:   return self.send_dashboard("robotmode")
    def get_safety_mode(self) -> str:  return self.send_dashboard("safetymode")
    def power_on(self) -> str:         return self.send_dashboard("power on")
    def power_off(self) -> str:        return self.send_dashboard("power off")
    def brake_release(self) -> str:    return self.send_dashboard("brake release")
    def play(self) -> str:             return self.send_dashboard("play")
    def stop(self) -> str:             return self.send_dashboard("stop")
    def get_loaded_program(self) -> str:  return self.send_dashboard("get loaded program")
    def get_program_state(self) -> str:   return self.send_dashboard("programState")
    def load_program(self, name: str) -> str: return self.send_dashboard(f"load {name}")

    # --- SFTP listing ---
    def list_programs(self, recursive: bool = True) -> List[str]:
        try:
            import paramiko, stat
        except Exception as e:
            raise UR3ConnectionError(
                "Le listing des programmes nécessite 'paramiko' (pip install paramiko)."
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
            transport = paramiko.Transport((host, port))
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
            raise UR3ConnectionError(f"Echec SFTP vers {host}:{port} (user={user}): {e}") from e
        finally:
            try:
                if sftp: sftp.close()
            finally:
                if transport: transport.close()

    # --- RTDE IO ---
    def _ensure_rtde_io(self):
        if rtde_io is None:
            raise UR3ConnectionError("rtde_io non disponible. Installe 'ur-rtde' (pip install ur-rtde).")
        if self._rtde_io is None:
            try:
                self._rtde_io = rtde_io.RTDEIOInterface(self.ip)
            except Exception as e:
                raise UR3ConnectionError(f"Echec connexion RTDE IO ({self.ip}): {e}") from e
        return self._rtde_io

    def set_input_int_register_rtde(self, index: int, value: int) -> None:
        idx = int(index)
        if not (0 <= idx <= 23):
            raise UR3ConnectionError("index input_int_register hors bornes (0..23).")
        io = self._ensure_rtde_io()
        io.setInputIntRegister(idx, int(value))

    # Convenience: écrire VialsNB sur le registre configuré
    def set_vials_nb(self, vnum: int, register: Optional[int] = None) -> None:
        reg = self.rtde_register_default if register is None else int(register)
        self.set_input_int_register_rtde(reg, int(vnum))


# --- Façade GUI ---
class UR3:
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

    # SFTP
    def list_programs(self, *a, **k): return self._impl.list_programs(*a, **k)

    # RTDE
    def set_input_int_register_rtde(self, *a, **k): return self._impl.set_input_int_register_rtde(*a, **k)
    def set_vials_nb(self, *a, **k): return self._impl.set_vials_nb(*a, **k)
