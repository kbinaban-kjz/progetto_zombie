"""
Backend/db_config.py — Configurazione del database SQLite.

Re-esporta le variabili di configurazione dal modulo centralizzato config.py
per garantire piena retrocompatibilità.
"""

from pathlib import Path
try:
    from Backend.config import DB_PATH, BACKEND_DIR, ROOT_DIR, ENV_PATH as ENV_FILE
except ImportError:
    from config import DB_PATH, BACKEND_DIR, ROOT_DIR, ENV_PATH as ENV_FILE

__all__ = ["DB_PATH", "BACKEND_DIR", "ROOT_DIR", "ENV_FILE"]
