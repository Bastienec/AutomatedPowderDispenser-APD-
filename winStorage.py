#!/usr/bin/env python3
# BEC - November 2025
# Sous-fenêtre pour la sélection des emplacements de storage pour l'UR3 (2x2 configurable)
#-------------------------------------------------------------------------------

import tkinter as tk
import tkinter.ttk as ttk

from guiUtils import GUIFactory, ToolTip

try:
    from config import STORAGE_CONFIG
except Exception:
    STORAGE_CONFIG = {
        "ids": ["S1", "S2", "S3", "S4"],
        "order": ["S1", "S2", "S3", "S4"],  # TL, TR, BL, BR
        "labels": {"S1":"S1","S2":"S2","S3":"S3","S4":"S4"},
    }


class WinStorage(tk.LabelFrame):
    """
    Sous-panneau "Storage" 2 x 2 avec mapping visuel configurable.
    Une seule case sélectionnable à la fois (groupe unique).
    """

    def __init__(self, parent, info_win=None, title: str = "Storage"):
        super().__init__(parent, text=title)
        self.info = info_win
        self.factory = GUIFactory(self)

        # Config
        ids = list(STORAGE_CONFIG.get("ids", ["S1","S2","S3","S4"]))
        order = list(STORAGE_CONFIG.get("order", ids))
        labels = dict(STORAGE_CONFIG.get("labels", {i: i for i in ids}))

        # Sanity: garde 4 éléments et corrige silencieusement si nécessaire
        def _take4(seq, fill=None):
            s = list(seq)[:4]
            while len(s) < 4:
                s.append(fill)
            return s

        ids = _take4(ids)
        order = _take4(order, ids[0])
        labels = {k: labels.get(k, k) for k in ids}

        # Membre: ordre visuel TL, TR, BL, BR
        self._order_visual = order           # ex: ["S1","S2","S3","S4"]
        self._labels = labels                # ex: {"S1":"S1", ...}

        # Une seule sélection -> IntVar (index 0..3 dans order)
        self.var_storage_index = tk.IntVar(value=-1)

        self._storage_buttons: list[tk.Radiobutton] = []

        self._build()
        self.after(0, self._reset_selection)

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------
    def _build(self):
        """
        Grille 2x2. Positions (indices var_storage_index):
        0: Top-Left, 1: Top-Right, 2: Bottom-Left, 3: Bottom-Right
        L'ID retourné correspond à self._order_visual[index].
        """
        positions = [
            (0, 0),  # TL
            (0, 1),  # TR
            (1, 0),  # BL
            (1, 1),  # BR
        ]

        for idx, (r, c) in enumerate(positions):
            slot_id = self._order_visual[idx]
            text = self._labels.get(slot_id, slot_id)

            rb = tk.Radiobutton(
                self,
                text=text,
                variable=self.var_storage_index,
                value=idx,
                indicatoron=True,
                padx=6, pady=4,
                borderwidth=0,
                highlightthickness=0,
            )
            rb.grid(row=r, column=c, padx=8, pady=6, sticky="w")
            self._storage_buttons.append(rb)
            ToolTip(rb, f"Storage {slot_id}")

        # (optionnel) layout propre
        for c in range(2):
            self.grid_columnconfigure(c, weight=0)

    def _reset_selection(self):
        """Aucune sélection au démarrage."""
        self.var_storage_index.set(-1)
        for rb in self._storage_buttons:
            try:
                rb.deselect()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------
    def get_selected_storage(self) -> str | None:
        """
        Retourne l'ID logique selon le mapping visuel, ex: 'S3', ou None.
        """
        idx = self.var_storage_index.get()
        if 0 <= idx < len(self._order_visual):
            return self._order_visual[idx]
        return None

    def set_selected_storage(self, storage_id: str) -> None:
        """
        Force une sélection à partir de l'ID logique (S1..S4).
        """
        try:
            idx = self._order_visual.index(storage_id)
        except ValueError:
            self._reset_selection()
            return
        self.var_storage_index.set(idx)

    def log_selected(self):
        """Log la sélection actuelle si info_win est fourni."""
        if not self.info:
            return
        v = self.get_selected_storage()
        if v:
            self.info.add(f"Storage sélectionné: {v}")
        else:
            self.info.add("Aucun storage sélectionné.")
