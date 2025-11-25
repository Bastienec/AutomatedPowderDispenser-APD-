'''Module that creates and manages the different windows of the GUI'''
#!/usr/bin/env python

# BEC - November 2025 
# Python GUI (Tkinter) for the APD
#-------------------------------------------------------------------------------
import tkinter as tk
from tkinter import ttk
#-------------------------------------------------------------------------------
# CLASS
class GUIFactory:
    def __init__(self, parent):
        self.parent = parent

    def create_btn(self, label, command, row, column,
                   state=tk.NORMAL, width=10, padx=5, pady=5, sticky=None, **kwargs):
        '''Fonction pour créer un bouton'''
        button = tk.Button(self.parent, text=label, command=command, width=width, state=state, **kwargs)
        button.grid(row=row, column=column, padx=padx, pady=pady, sticky=sticky if sticky else "")
        return button

    def create_label(self, text, row, column, padx=5, pady=5, sticky=tk.W, bg=None, fg=None, **kwargs):
        """Fonction pour créer un label (sans couleurs par défaut invalides)."""
        label = tk.Label(self.parent, text=text, **kwargs)
        if bg is not None:
            label.configure(bg=bg)
        if fg is not None:
            label.configure(fg=fg)
        label.grid(row=row, column=column, padx=padx, pady=pady, sticky=sticky)
        return label
    
    def create_labelvariable(self, textvariable, row, column,
                             padx=5, pady=5, sticky=tk.W, bg=None, fg=None, **kwargs):
        """Label lié à une StringVar / DoubleVar, dans le même style que create_label."""
        label = tk.Label(self.parent, textvariable=textvariable, **kwargs)
        if bg is not None:
            label.configure(bg=bg)
        if fg is not None:
            label.configure(fg=fg)
        label.grid(row=row, column=column, padx=padx, pady=pady, sticky=sticky)
        return label

    def create_entry(self, textvariable, row, column, width=10, padx=5, pady=5, sticky=tk.EW, **kwargs):
        '''Fonction pour créer une entrée'''
        entry = tk.Entry(self.parent, textvariable=textvariable, width=width, **kwargs)
        entry.grid(row=row, column=column, padx=padx, pady=pady, sticky=sticky)
        return entry

class ToolTip:
    """
    Classe pour créer une info-bulle (tooltip) pour un widget donné.
    """
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.id = None
        self.delay = 500  # Délai avant l'apparition de l'info-bulle en millisecondes
        self.x_offset = 20  # Décalage horizontal de l'info-bulle
        self.y_offset = 10  # Décalage vertical de l'info-bulle
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
    
    def enter(self, event=None):
        self.schedule()
    
    def leave(self, event=None):
        self.unschedule()
        self.hidetip()
    
    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(self.delay, self.showtip)
    
    def unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
    
    def showtip(self, event=None):
        x = self.widget.winfo_rootx() + self.x_offset
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.y_offset
        # Création d'une fenêtre Toplevel
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)  # Supprime les bordures de la fenêtre
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background="#ffffe0", relief=tk.SOLID, borderwidth=1,
            font=("tahoma", "8", "normal")
        )
        label.pack(ipadx=1)
    
    def hidetip(self):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None
