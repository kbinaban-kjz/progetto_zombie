"""
Backend/db_config.py — Configurazione del database SQLite.

Il database viene salvato automaticamente nel file locale Backend/cronologia.db
(oppure nel percorso indicato dalla variabile d'ambiente SQLITE_DB_PATH).
"""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
ENV_FILE = ROOT_DIR / ".env"

if ENV_FILE.is_file():
    for riga in ENV_FILE.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        chiave, valore = riga.split("=", 1)
        os.environ.setdefault(chiave.strip(), valore.strip().strip("\"'"))

# Percorso del file database SQLite
DB_PATH = Path(os.environ.get("SQLITE_DB_PATH", str(BACKEND_DIR / "cronologia.db")))
