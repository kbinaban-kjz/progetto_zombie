"""
Backend/database.py — Creazione dello schema SQLite e gestione di domande e risposte.

Puoi eseguire questo file direttamente per creare/verificare il database SQLite:
    python Backend/database.py
"""

import json
import sqlite3
from pathlib import Path

try:
    from Backend.db_config import DB_PATH
except ImportError:
    from db_config import DB_PATH

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cronologia_chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domanda TEXT NOT NULL,
    risposta TEXT NOT NULL,
    fonti TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection() -> sqlite3.Connection:
    """Restituisce una connessione al database SQLite definito in Backend/db_config.py."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def inizializza_db():
    """Crea la tabella cronologia_chat (id, domanda, risposta, fonti, created_at) se non esiste."""
    sql = SCHEMA_FILE.read_text(encoding="utf-8") if SCHEMA_FILE.exists() else SCHEMA_SQL
    with get_connection() as conn:
        conn.executescript(sql)
        conn.commit()


def salva_messaggio(domanda: str, risposta: str, fonti: list[str] | None = None) -> dict:
    """Salva una domanda e la relativa risposta nella tabella SQLite cronologia_chat."""
    lista_fonti = list(fonti or [])
    inizializza_db()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO cronologia_chat (domanda, risposta, fonti)
            VALUES (?, ?, ?)
            """,
            (domanda, risposta, json.dumps(lista_fonti, ensure_ascii=False)),
        )
        row_id = cur.lastrowid
        conn.commit()
        cur = conn.execute(
            "SELECT id, domanda, risposta, fonti, created_at FROM cronologia_chat WHERE id = ?",
            (row_id,),
        )
        riga = dict(cur.fetchone())
    try:
        riga["fonti"] = json.loads(riga["fonti"]) if isinstance(riga.get("fonti"), str) else lista_fonti
    except json.JSONDecodeError:
        riga["fonti"] = lista_fonti
    return riga


def leggi_cronologia() -> list[dict]:
    """Legge tutta la cronologia di domande e risposte dal database SQLite."""
    inizializza_db()
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT id, domanda, risposta, fonti, created_at
            FROM cronologia_chat
            ORDER BY id ASC
            """
        )
        righe = [dict(r) for r in cur.fetchall()]
    for r in righe:
        if isinstance(r.get("fonti"), str):
            try:
                r["fonti"] = json.loads(r["fonti"])
            except json.JSONDecodeError:
                r["fonti"] = []
    return righe


if __name__ == "__main__":
    inizializza_db()
    print(f"Database SQLite pronto in: {DB_PATH}")
    print(f"Voci presenti in 'cronologia_chat': {len(leggi_cronologia())}")
