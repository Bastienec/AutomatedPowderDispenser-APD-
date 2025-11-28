'''Config file for the "Automated Powder Dispenser" APD'''
#!/usr/bin/env python3
# pylint:disable=no-member,missing-docstring,invalid-name

# BEC - November 2025 
# Constants to be changed for APD
#-------------------------------------------------------------------------------

import os
#-------------------------------------------------------------------------------
# Récupère le chemin ABSOLU du dossier du projet (là où est config.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP_CONFIG = {
    'base_directory': BASE_DIR,   # le dossier où est "config.py"
    'soft_directory': os.path.join(BASE_DIR, "soft"),
    'data_directory': os.path.join(BASE_DIR, "data"),
    'log_app_directory': os.path.join(BASE_DIR, "log"),
    'measures_directory': os.path.join(BASE_DIR, "data", "Measures"),
    'cleanup_old_files': False,
    'days_before_cleanup': 7,
    'log_rotation_days': 20,
}

# --- Balance Mettler (MT-SICS via web service)
SCALE_CONFIG = {
    # HTTP (81) ou HTTPS (444)
    "scheme": "http",                     # "http" ou "https"
    "ip": "192.168.0.50",
    "port": 81,                           # 81 en HTTP, 444 en HTTPS
    "wsdl_path": r"C:\Users\eshaya\Nextcloud\Bastien_nextCloud\project\AutomatedPowderDispenser-main\documents\Mettler\MT.Laboratory.Balance.XprXsr.V03.wsdl",
    "password": "SWISSCAT",               # mot de passe pour décrypter le SessionId
    "verify": False,                      # en HTTPS: False ou chemin .cer ; en HTTP: ignoré
    "timeout_s": 8,
    "autoconnect": True,                  # tenter la connexion automatique au démarrage

    # Paramètres portes (SetPosition)
    "door_ids": ["LeftOuter"],
    "open_width": 100,
    "close_width": 0,

    "vial_presence_min_mg": 14000.0,  # min masse brute pour considérer qu'une vial est présente
}

# --- UR3 
UR3_CONFIG = {
    'ip': '192.168.0.5',
    'script_port': 30002,
    'dashboard_port': 29999,

    # Pour le listing SFTP des programmes
    "sftp_port": 22,
    "sftp_user": "root",          # sera essayé en 1er
    "sftp_password": "swisscat",  # sera essayé en 1er
    "programs_dir": "/programs",  # racine standard sur les UR e-Series

    "rtde_input_register": 20,   # GPii[n] utilisé pour VialsNB
    "disp_rtde_input_register": 21, # GPii[n] pour DispNB
    "vial_id_to_number": {
        "E1-1": 4, "E1-2": 3, "E1-3": 2, "E1-4": 1,
        "E2-1": 7, "E2-2": 6, "E2-3": 5,
        "E3-1": 11, "E3-2": 10, "E3-3": 9, "E3-4": 8,
    },
}

STORAGE_CONFIG = {
    
    "ids": ["S1", "S2", "S3", "S4"],    # IDs logiques disponibles
    "order": ["S3", "S4", "S1", "S2"],      # Ordre VISUEL des positions (Top-Left, Top-Right, Bottom-Left, Bottom-Right)
    "id_to_number": {"S1": 1, "S2": 2, "S3": 3, "S4": 4},        # (optionnel) mapping logique → numéro poussé sur DispNB
    "labels": {"S1":"NaHCO3","S2":"CouCou Edy","S3":"CouCou Louis","S4":"Autre chose"},        #libellés si on veut afficher autre chose que l'ID
}