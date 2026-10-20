"""
Backend/database.py — Gestione completa del database SQLite per l'Investigatore AI.

Responsabilità:
- Creazione e inizializzazione dello schema SQLite (cronologia_chat, instradamento_chat).
- Salvataggio e lettura della cronologia di domande, risposte e fonti.
- Salvataggio e lettura dei metadati di instradamento del routing ibrido (locale vs cloud).
- Ricerca testuale all'interno delle domande e risposte passate.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from Backend.config import DB_PATH
except ImportError:
    from config import DB_PATH

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"

SCHEMA_FALLBACK = """
CREATE TABLE IF NOT EXISTS cronologia_chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domanda TEXT NOT NULL,
    risposta TEXT NOT NULL,
    fonti TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS instradamento_chat (
    id_messaggio INTEGER PRIMARY KEY,
    motore TEXT NOT NULL,
    modello_usato TEXT NOT NULL,
    complessita TEXT NOT NULL,
    motivo_routing TEXT NOT NULL,
    durata_ms INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (id_messaggio) REFERENCES cronologia_chat(id) ON DELETE CASCADE
);
"""


def get_connection() -> sqlite3.Connection:
    """Restituisce una connessione al database SQLite con row_factory attivo."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def inizializza_db() -> None:
    """Crea le tabelle cronologia_chat e instradamento_chat se non esistono."""
    sql = SCHEMA_FILE.read_text(encoding="utf-8") if SCHEMA_FILE.exists() else SCHEMA_FALLBACK
    with get_connection() as conn:
        conn.executescript(sql)
        conn.commit()


def salva_messaggio(domanda: str, risposta: str, fonti: list[str] | None = None) -> dict[str, Any]:
    """Salva una domanda e la relativa risposta nella tabella cronologia_chat."""
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


def leggi_cronologia() -> list[dict[str, Any]]:
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


def salva_con_instradamento(domanda: str, fonti_nomi: list[str], esito: dict[str, Any]) -> dict[str, Any]:
    """
    Salva il messaggio in cronologia_chat e i metadati del motore usato in instradamento_chat.
    Restituisce il record completo arricchito.
    """
    inizializza_db()
    riga = salva_messaggio(domanda, esito["risposta"], fonti_nomi)
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO instradamento_chat
                    (id_messaggio, motore, modello_usato, complessita, motivo_routing, durata_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    riga["id"],
                    esito["motore"],
                    esito["modello_usato"],
                    esito["complessita"],
                    esito["motivo_routing"],
                    esito.get("durata_ms", 0),
                ),
            )
            conn.commit()
    except Exception as exc:
        print(f"(Avviso salvataggio instradamento SQLite: {exc})")

    riga.update(
        {k: esito[k] for k in ("motore", "modello_usato", "complessita", "motivo_routing", "durata_ms") if k in esito}
    )
    return riga


def leggi_cronologia_con_instradamento() -> list[dict[str, Any]]:
    """Restituisce le voci di cronologia arricchite con i dettagli del motore usato."""
    inizializza_db()
    righe = leggi_cronologia()
    try:
        with get_connection() as conn:
            meta = {
                r["id_messaggio"]: dict(r)
                for r in conn.execute("SELECT * FROM instradamento_chat").fetchall()
            }
    except Exception:
        meta = {}

    for r in righe:
        m = meta.get(r["id"])
        if m:
            r.update(
                {
                    "motore": m["motore"],
                    "modello_usato": m["modello_usato"],
                    "complessita": m["complessita"],
                    "motivo_routing": m["motivo_routing"],
                    "durata_ms": m["durata_ms"],
                }
            )
        else:
            r["motore"] = None
    return righe


def cerca_in_cronologia(termine: str) -> list[dict[str, Any]]:
    """Cerca messaggi passati che contengono una specifica parola o frase."""
    inizializza_db()
    termine_clean = f"%{termine.strip().lower()}%"
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT c.id, c.domanda, c.risposta, c.fonti, c.created_at,
                   i.motore, i.modello_usato, i.complessita, i.motivo_routing, i.durata_ms
            FROM cronologia_chat c
            LEFT JOIN instradamento_chat i ON c.id = i.id_messaggio
            WHERE LOWER(c.domanda) LIKE ? OR LOWER(c.risposta) LIKE ?
            ORDER BY c.id DESC
            """,
            (termine_clean, termine_clean),
        )
        righe = [dict(r) for r in cur.fetchall()]

    for r in righe:
        if isinstance(r.get("fonti"), str):
            try:
                r["fonti"] = json.loads(r["fonti"])
            except json.JSONDecodeError:
                r["fonti"] = []
    return righe


def cancella_cronologia() -> int:
    """
    Cancella l'intera cronologia di chat e metadati di instradamento dal database SQLite.
    Ripristina inoltre il contatore autoincrementale (sqlite_sequence).
    Restituisce il numero di record rimossi dalla cronologia.
    """
    inizializza_db()
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("DELETE FROM instradamento_chat")
        cur = conn.execute("DELETE FROM cronologia_chat")
        eliminati = cur.rowcount
        try:
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('cronologia_chat', 'instradamento_chat')"
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
    return eliminati


if __name__ == "__main__":
    inizializza_db()
    cronologia = leggi_cronologia_con_instradamento()
    print(f"Database SQLite pronto in: {DB_PATH}")
    print(f"Voci totali registrate: {len(cronologia)}")
