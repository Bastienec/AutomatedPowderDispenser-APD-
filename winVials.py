#!/usr/bin/env python3
# BEC - November 2025
# Sous-fenêtre pour la sélection des vials pour l'UR3
#-------------------------------------------------------------------------------

import tkinter as tk
import tkinter.ttk as ttk

from guiUtils import GUIFactory, ToolTip



class WinVials(tk.LabelFrame):
    """
    Sous-panneau pour choisir des vials parmi plusieurs positions.
    Il y a deux groupes indépendants de Radiobuttons :
      - groupe E* : E1, E2, E3 (avec 4,3,4 vials)
      - groupe F* : F1, F2, F3 (avec 4,3,4 vials)
    Chaque groupe a une seule sélection possible.
    """

    def __init__(self, parent, info_win=None, title: str = "Vials"):
        super().__init__(parent, text=title)
        self.info = info_win
        self.factory = GUIFactory(self)

        # Petite police pour gagner en hauteur
        self.small_font = ("TkDefaultFont", 8)

        # Deux variables d'index indépendantes : une pour E*, une pour F*
        # -1 = aucune sélection
        self.var_vial_index_c = tk.IntVar(value=-1)
        self.var_vial_index_f = tk.IntVar(value=-1)

        # Layout : (nom_colonne, nombre_de_vials)
        self.vials_layout_c = [
            ("E1", 4),
            ("E2", 3),
            ("E3", 4),
        ]
        self.vials_layout_f = [
            ("F1", 4),
            ("F2", 3),
            ("F3", 4),
        ]

        # stockage pour mapping index -> "E1-1", "F2-3", etc.
        self._vial_ids_c: list[str] = []
        self._vial_buttons_c: list[tk.Radiobutton] = []

        self._vial_ids_f: list[str] = []
        self._vial_buttons_f: list[tk.Radiobutton] = []

        self._build()

        # Important : forcer l'état "aucune sélection" APRÈS construction
        self.after(0, self._reset_selection)

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------
    def _build_group(self, base_col: int, layout, var_index, ids_list, btn_list):
        """
        Construit un groupe de vials en quinconce, à partir d'une colonne de base.
        base_col: colonne de départ (0 pour E*, 4 par ex. pour F*)
        layout: [("E1",4), ("E2",3), ("E3",4)] ou équivalent
        var_index: IntVar pour ce groupe
        ids_list: liste où on pousse les ids ("E1-1",...)
        btn_list: liste où on pousse les Radiobuttons
        """
        idx = 0  # index pour ce groupe

        for offset_col, (col_name, count) in enumerate(layout):
            col = base_col + offset_col

            # Entête de colonne
            lbl = tk.Label(self, text=col_name, font=self.small_font)
            lbl.grid(row=0, column=col, pady=(0, 1))

            for i in range(1, count + 1):
                # Calcul de la ligne en fonction de la colonne pour faire la quinconce
                if col_name.endswith("1") or col_name.endswith("3"):
                    # E1/E3/F1/F3 : lignes 1,3,5,7 (4 vials)
                    # (quand count=3, seules 3 lignes seront utilisées)
                    row = 1 + (i - 1) * 2      # 1,3,5,7
                elif col_name.endswith("2"):
                    # E2/F2 : lignes 2,4,6
                    row = 2 + (i - 1) * 2      # 2,4,6
                else:
                    row = i

                vial_id = f"{col_name}-{i}"
                ids_list.append(vial_id)

                rb = tk.Radiobutton(
                    self,
                    variable=var_index,
                    value=idx,              # chaque bouton a un index unique dans SON groupe
                    indicatoron=True,       # rond
                    font=self.small_font,
                    padx=0,
                    pady=0,
                    borderwidth=0,
                    highlightthickness=0,
                )
                rb.grid(row=row, column=col, padx=3, pady=0)

                btn_list.append(rb)
                ToolTip(rb, f"Vial {vial_id}")

                idx += 1

    def _build(self):
        """
        Construit deux groupes de vials en quinconce, compacts :
          - groupe E* à gauche (E1, E2, E3)
          - groupe F* à droite (F1, F2, F3)
        """
        # Groupe E* : colonnes 0,1,2
        self._build_group(
            base_col=0,
            layout=self.vials_layout_c,
            var_index=self.var_vial_index_c,
            ids_list=self._vial_ids_c,
            btn_list=self._vial_buttons_c,
        )

        # Séparateur vertical en colonne 3
        # On le fait partir de row=0 jusqu'à row=8 (ça couvre largement tous les ronds).
        sep = ttk.Separator(self, orient="vertical")
        sep.grid(row=0, column=3, rowspan=8, sticky="ns", padx=5)

        # Groupe F* : colonnes 4,5,6 (on laisse la colonne 3 comme espace visuel)
        self._build_group(
            base_col=4,
            layout=self.vials_layout_f,
            var_index=self.var_vial_index_f,
            ids_list=self._vial_ids_f,
            btn_list=self._vial_buttons_f,
        )

    def _reset_selection(self):
        """
        Force l'état initial : aucune vial sélectionnée dans les deux groupes.
        """
        self.var_vial_index_c.set(-1)
        self.var_vial_index_f.set(-1)
        for rb in self._vial_buttons_c:
            rb.deselect()
        for rb in self._vial_buttons_f:
            rb.deselect()

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------
    def get_selected_vial_e(self) -> str | None:
        """
        Retourne la vial sélectionnée dans le groupe E* (ex: 'E2-3') ou None.
        """
        idx = self.var_vial_index_c.get()
        if 0 <= idx < len(self._vial_ids_c):
            return self._vial_ids_c[idx]
        return None

    def get_selected_vial_f(self) -> str | None:
        """
        Retourne la vial sélectionnée dans le groupe F* (ex: 'F1-2') ou None.
        """
        idx = self.var_vial_index_f.get()
        if 0 <= idx < len(self._vial_ids_f):
            return self._vial_ids_f[idx]
        return None

    # Pour compatibilité avec ton ancienne API : on retourne le groupe E par défaut
    def get_selected_vial(self) -> str | None:
        return self.get_selected_vial_e()

    def set_selected_vial_c(self, vial_id: str) -> None:
        """
        Force une sélection dans le groupe E*.
        """
        try:
            idx = self._vial_ids_c.index(vial_id)
        except ValueError:
            return
        self.var_vial_index_c.set(idx)

    def set_selected_vial_f(self, vial_id: str) -> None:
        """
        Force une sélection dans le groupe F*.
        """
        try:
            idx = self._vial_ids_f.index(vial_id)
        except ValueError:
            return
        self.var_vial_index_f.set(idx)

    def log_selected(self):
        """
        Helper pour logger les sélections actuelles dans la fenêtre d'info.
        """
        if not self.info:
            return
        vc = self.get_selected_vial_e()
        vf = self.get_selected_vial_f()
        self.info.add(f"Vial E*: {vc if vc else 'Aucune'}")
        self.info.add(f"Vial F*: {vf if vf else 'Aucune'}")
