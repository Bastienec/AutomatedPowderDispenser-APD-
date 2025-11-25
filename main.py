'''Python GUI (Tkinter) for the "Automated Powder Dispenser" APD'''
#!/usr/bin/env python3

# BEC - November 2025 
#-------------------------------------------------------------------------------

import config
import win
# import tkinter.messagebox as messagebox
import tkinter as tk

#-------------------------------------------------------------------------------
# MAIN

def main():
    devices = {
        'ur3': None,    # client UR3 (connecté depuis l'UI)
        'scale': None,  # balance Mettler (connecté depuis l'UI)
    }
    try:
        # Création de l'application
        app = win.WinMain(devices)
        app.title("main.py - Automated Powder Dispenser - APD_v1")
        app.start()
    finally:
        pass

if __name__ == '__main__':
    main()