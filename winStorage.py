#!/usr/bin/env python3
# BEC - November 2025
# Sous-fenêtre pour la sélection des emplacements de storage pour l'UR3
#-------------------------------------------------------------------------------

import tkinter as tk
import tkinter.ttk as ttk

from guiUtils import GUIFactory, ToolTip


class WinStorage(tk.LabelFrame):
    """
    Sous-panneau "Storage" avec une grille compacte de 3 lignes x 5 radiobuttons.
    Une seule case sélectionnable à la fois (un groupe).
    """

    def __init__(self, parent, info_win=None, title: str = "Storage"):
        super().__init__(parent, text=title)
        self.info = info_win
        self.factory = GUIFactory(self)

        # Petite police pour gagner en hauteur
        self.small_font = ("TkDefaultFont", 8)

        # Une seule sélection possible -> un IntVar avec index, -1 = aucune sélection
        self.var_storage_index = tk.IntVar(value=-1)

        # On fait 3 lignes x 5 colonnes => 15 slots
        self.n_rows = 3
        self.n_cols = 5

        # Mapping index -> ID (S1, S2, ..., S15)
        self._storage_ids: list[str] = []
        self._storage_buttons: list[tk.Radiobutton] = []

        self._build()

        # S'assurer qu'au démarrage, rien n'est visuellement sélectionné
        self.after(0, self._reset_selection)

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------
    def _build(self):
        """
        Construit une grille simple 3x5 de radiobuttons (pas de quinconce).
        IDs internes: S1..S15 (tu pourras changer si besoin).
        """

        idx = 0
        for r in range(self.n_rows):
            for c in range(self.n_cols):
                slot_id = f"S{idx+1}"   # S1, S2, ..., S15
                self._storage_ids.append(slot_id)

                rb = tk.Radiobutton(
                    self,
                    variable=self.var_storage_index,
                    value=idx,
                    indicatoron=True,       # rond
                    font=self.small_font,
                    padx=0,
                    pady=0,
                    borderwidth=0,
                    highlightthickness=0,
                )
                # +1 pour laisser la ligne 0 dispo si un jour tu veux un header
                rb.grid(row=r+1, column=c, padx=3, pady=0)

                self._storage_buttons.append(rb)
                ToolTip(rb, f"Storage {slot_id}")

                idx += 1

    def _reset_selection(self):
        """
        Force état initial: aucune storage sélectionnée.
        """
        self.var_storage_index.set(-1)
        for rb in self._storage_buttons:
            rb.deselect()

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------
    def get_selected_storage(self) -> str | None:
        """
        Retourne l'emplacement de storage sélectionné (ex: 'S3') ou None.
        """
        idx = self.var_storage_index.get()
        if 0 <= idx < len(self._storage_ids):
            return self._storage_ids[idx]
        return None

    def set_selected_storage(self, storage_id: str) -> None:
        """
        Permet de forcer une sélection depuis l'extérieur (optionnel).
        """
        try:
            idx = self._storage_ids.index(storage_id)
        except ValueError:
            self._reset_selection()
            return
        self.var_storage_index.set(idx)

    def log_selected(self):
        """
        Helper pour logger la sélection actuelle dans la fenêtre d'info.
        """
        if not self.info:
            return
        v = self.get_selected_storage()
        if v:
            self.info.add(f"Storage sélectionné: {v}")
        else:
            self.info.add("Aucun storage sélectionné.")
