#!/usr/bin/env python3

# BEC - November 2025 
# Python GUI (Tkinter) for the APD
# Module that creates and manages the different windows of the GUI
#-------------------------------------------------------------------------------
import tkinter as tk

#-------------------------------------------------------------------------------
class WinAuto(tk.Frame):
   def __init__(self, parent, info_win, devices):
        super().__init__(parent)
        self.parent = parent
        self.win_info = info_win
        self.devices = devices
