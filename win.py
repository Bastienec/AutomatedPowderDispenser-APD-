#!/usr/bin/env python3

# BEC - November 2025 
# Python GUI (Tkinter) for the APD
# Module that creates and manages the different windows of the GUI
#-------------------------------------------------------------------------------
import tkinter as tk
import tkinter.ttk as ttk

import winInfo
import winMan
import winAuto
#-------------------------------------------------------------------------------
# CLASS
class winMode(tk.Frame):
    def __init__(self, parent, info_win, devices):
        super().__init__(parent)
        self.parent = parent
        self.win_info = info_win
        self.devices = devices

        self.setup_layout()
        self.create_frames()

    def setup_layout(self):
        """Configure the layout of the main window."""
        self.parent.columnconfigure(0, weight=1)
        self.parent.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, pady=5, padx=5, sticky=tk.EW)

    def create_frames(self):
        """Create and add frames to the notebook."""
        self.frame_auto = ttk.Frame(self.notebook)
        self.frame_man = ttk.Frame(self.notebook)

        self.win_man = winMan.WinMan(self.frame_man, self.win_info, self.devices)
        self.win_auto = winAuto.WinAuto(self.frame_auto, self.win_info, self.devices)

        # (pour réutiliser toutes les vérifs déjà codées)
        self.win_auto.attach_manual_views(
            robot_window=self.win_man.win_robot,
            balance_window=self.win_man.win_balance,
        )       

        self.win_auto.grid(row=0, column=0, pady=5, padx=5, sticky=tk.EW)
        self.win_man.grid(row=0, column=0, pady=5, padx=5, sticky=tk.EW)

        self.notebook.add(self.frame_man, text='Mode Man')
        self.notebook.add(self.frame_auto, text='Mode Auto')
        
        # sélectionner "Man" au démarrage
        self.notebook.select(self.frame_man)

class WinMain(tk.Tk):
    def __init__(self, devices, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state('zoomed')
        self.devices = devices      # Recuperaton du dictionnaire devices pour fermer les connections
        self.win_info = winInfo.WinInfo(self)
        self.setup_gui()
        self.active_threads = []

    def setup_gui(self):
        """Setup the main GUI layout."""
        self.configure_canvas()

        self.win_info.add("-----------------------------------------------------------", level="info")
        self.win_info.add("-----------------------------------------------------------", level="info")
        self.win_info.add("Init...\n", level="info")
        self.win_mode = winMode(self.frame, self.win_info, self.devices)
        self.win_mode.grid(row=0, column=0, padx=10, pady=10, sticky=tk.EW)
        self.win_info.grid(row=1, column=0, padx=10, pady=10, sticky=tk.EW)

        self.update()
        self.minsize(self.winfo_width(), self.winfo_height())
        self.resizable(width=True, height=True)

        self.limit_window_size()

    def configure_canvas(self):
        """Configure the canvas with scrollbars."""
        self.canvas = tk.Canvas(self)
        self.scroll_y = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        # self.scroll_x = tk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.scroll_y.set,
                            #   xscrollcommand=self.scroll_x.set
                            )

        self.frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.frame, anchor="nw")

        self.frame.bind("<Configure>", self.on_frame_configure)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll_y.grid(row=0, column=1, sticky="ns")
        # self.scroll_x.grid(row=1, column=0, sticky="ew")


    def on_frame_configure(self, event=None):
        """Adjust the scroll region to encompass the entire frame."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def limit_window_size(self):
        """Limit the maximum window size to the screen size."""
        # Obtenir les dimensions de l'écran
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Définir la taille maximale de la fenêtre avec une marge
        margin = 0
        max_width = screen_width - margin
        max_height = screen_height - margin
        self.maxsize(max_width, max_height)

        # S'assurer que la fenêtre commence avec une taille appropriée
        self.geometry(f"{max_width}x{max_height}")

    def start(self):
        """Start the Tkinter main loop."""
        self.protocol("WM_DELETE_WINDOW", self.cbkWinMainExit)
        self.mainloop()

    def cbkWinMainExit(self):
        """Callback to clean up and close the application safely."""
        self.win_info.doWhenExiting()
        self.win_info.add("User exit program")
        self.win_info.add("-----------------------------------------------------------", level="info")
        self.win_info.add("-----------------------------------------------------------\n\n", level="info")
        self.destroy()


    def close_devices(self):
        """ Fermer tous les périphériques en toute sécurité """
        for device in self.devices.values():
            if device is not None:
                device.close()
