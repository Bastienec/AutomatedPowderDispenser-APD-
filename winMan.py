'''Module that creates and manages the different windows of the GUI'''
#!/usr/bin/env python3
# pylint:disable=no-member,missing-docstring,invalid-name

# BEC - November 2025 
# Python GUI (Tkinter) for the APD
#-------------------------------------------------------------------------------
import tkinter as tk
from winScale import WinBalance
from winRobotArm import WinRobotArm

class WinMan(tk.Frame):
    def __init__(self, parent, info_win, devices):
        super().__init__(parent)
        self.parent = parent
        self.win_info = info_win
        self.devices = devices

        # Permet à la grille de s'étirer un peu
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # ---- Balance ----
        self.win_balance = WinBalance(self, self.win_info, self.devices)
        self.win_balance.grid(row=0, column=0, padx=5, pady=5, sticky=tk.NSEW)

        # ---- Bras UR3 ----
        self.win_robot = WinRobotArm(self, self.win_info, self.devices)
        self.win_robot.grid(row=1, column=0, padx=5, pady=5, sticky=tk.NSEW)
        self.win_robot.grid_configure(columnspan=2)