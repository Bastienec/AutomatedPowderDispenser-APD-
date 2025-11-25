'''Module that creates and manages the different windows of the GUI'''
#!/usr/bin/env python3
# pylint:disable=no-member,missing-docstring,invalid-name

# BEC - November 2025 
# Python GUI (Tkinter) for the APD
#-------------------------------------------------------------------------------
import os
import datetime as dt
import logging
import tkinter as tk
import tkinter.scrolledtext as tst
import config
#-------------------------------------------------------------------------------
# Configure logging
log_directory = os.path.join(config.APP_CONFIG['log_app_directory'])    # Chemin du dossier de log
os.makedirs(log_directory, exist_ok=True)  # Crée le dossier s'il n'existe pas

# Nom du fichier de log avec la date du jour
log_file_path = os.path.join(log_directory, f"journal_{dt.datetime.now().strftime('%Y-%m-%d')}.log")

try:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s -- %(levelname)s: %(message)s',
        datefmt='%d %B %Y -- %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file_path, encoding="utf-8"),   # Ecriture dans un fichier
            logging.StreamHandler()                                # Ecriture dans la console
        ]
    )
    logger = logging.getLogger(__name__)    # Crée un logger avec le nom du module

    # Test de l'existence du fichier log après configuration
    if os.path.exists(log_file_path):
        print(f"Le fichier de log a bien été créé à : {log_file_path}")
    else:
        print(f"Le fichier de log n'a pas pu être créé à : {log_file_path}")
        
except Exception as e:
    print(f"Erreur lors de la configuration du logging : {e}")

#-------------------------------------------------------------------------------
# CLASS
class WinInfo(tk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="Info")
        self.parent = parent
        self.setup_layout()
        self.configure_text_widget()

    def setup_layout(self):
        """Configure the layout of the main window."""        
        self.parent.columnconfigure(0, weight=1)
        self.parent.rowconfigure(0, weight=1)
        # # ... and the scrolledText will follow as well

        # Assure que le frame redimensionne correctement avec la fenêtre parente
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def configure_text_widget(self):
        """Create and configure the scrolled text widget."""
        self.text = tst.ScrolledText(self,
                                     wrap = tk.WORD,
                                     state = 'disabled',
                                     width = 50,
                                     height = 3,
                                     font = ("Courrier", 11))

        self.text.grid(row = 0, column = 0, pady = 5, padx = 5, sticky=tk.EW)
        self.text.focus()           # Placing cursor in the text area

    def add(self, message, level="info"):
        """Add a message to the text widget and log it to a file."""
        timestamp = dt.datetime.now().strftime("%d %B %Y -- %H:%M:%S: ")
        formatted_message = f"{timestamp}{message}\n"

        self.append_message_to_widget(formatted_message)

        # Log the message depending on wich level
        if level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        elif level == "debug":
            logger.debug(message)
        else:
            logger.info(message)

    def append_message_to_widget(self, message):
        """Append a message to the scrolled text widget."""
        self.text.configure(state='normal')
        self.text.insert('1.0', message)
        # Ajuste la longueur du tag en fonction de la longueur du timestamp
        timestamp_length = len(dt.datetime.now().strftime("%d %B %Y -- %H:%M:%S: "))
        self.text.tag_add('time', '1.0', f'1.{timestamp_length}')
        self.text.tag_config('time', foreground='green')
        self.text.configure(state='disabled')

    def doWhenExiting(self):
        """Handle tasks when the application is closing."""
        self.cleanup_old_logs()

    def cleanup_old_logs(self):
        """Remove the oldest log files if there are more than 10."""
        try:
            log_files = [
                os.path.join(log_directory, f)
                for f in os.listdir(log_directory)
                if os.path.isfile(os.path.join(log_directory, f)) and f.startswith("journal_") and f.endswith(".log")
            ]

            # Trier les fichiers par nom (i.e : un tri par date)
            log_files_sorted = sorted(log_files)

            # Définir le nombre maximum de fichiers de log à conserver
            max_log_files = 10

            # Calculer combien de fichiers doivent être supprimés
            files_to_delete = log_files_sorted[:-max_log_files] if len(log_files_sorted) > max_log_files else []

            for file_path in files_to_delete:
                try:
                    os.remove(file_path)
                    logger.info(f"Old log file {file_path} removed.")
                except Exception as e:
                    logger.error(f"Error removing old log file {file_path}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error during cleanup of old logs: {e}", exc_info=True)

