"""
Backend/schema_inspector.py — Ispezione dinamica dello schema del database SQLite (accessi.sqlite).

Fornisce funzioni per estrarre in modo 100% dinamico e non hardcoded:
- Elenco tabelle, colonne, tipi di dato, vincoli NOT NULL e PRIMARY KEY.
- Relazioni di chiave esterna (FOREIGN KEY) e cardinalità relazionale.
- Conteggio record in tempo reale e anteprima righe di esempio.
- DDL completo (CREATE TABLE) generato da SQLite.
- Generazione automatica del diagramma Mermaid ER.
- Query di lettura sicure (SELECT) con paginazione per l'anteprima nel Frontend.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

try:
    from Backend.config import risolvi_accessi_db
except ImportError:
    from config import risolvi_accessi_db


def formatta_dimensione(bytes_totali: int) -> str:
    """Formatta i byte in formato leggibile (KB, MB)."""
    if bytes_totali < 1024:
        return f"{bytes_totali} B"
    elif bytes_totali < 1024 * 1024:
        return f"{bytes_totali / 1024:.1f} KB"
    else:
        return f"{bytes_totali / (1024 * 1024):.2f} MB"


def _sanifica_tipo_mermaid(tipo: str) -> str:
    """Sanifica il tipo di dato SQL per la sintassi Mermaid ER (nessuno spazio o parentesi)."""
    if not tipo:
        return "TEXT"
    t = tipo.strip().split("(")[0].strip()
    t = re.sub(r"[^a-zA-Z0-9_]", "_", t)
    return t or "TEXT"


def estrai_schema_database(db_path: str | Path | None = None) -> dict[str, Any]:
    """
    Introspezione completa e dinamica del database SQLite.
    Legge direttamente da sqlite_master, PRAGMA table_info e PRAGMA foreign_key_list.
    Non contiene alcun riferimento hardcoded a tabelle o colonne specifiche.
    """
    path = risolvi_accessi_db() if db_path is None else Path(db_path).resolve()
    if not path.is_file():
        return {
            "ok": False,
            "error": f"Database non trovato nel percorso: {path}",
            "database": path.name if path else "accessi.sqlite",
            "tabelle": {},
            "relazioni": [],
            "totale_tabelle": 0,
            "totale_record": 0,
            "totale_relazioni": 0,
            "mermaid": "",
        }

    dimensione = path.stat().st_size

    try:
        uri = f"{path.as_uri()}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Impossibile aprire il database in sola lettura: {exc}",
            "database": path.name,
            "tabelle": {},
            "relazioni": [],
            "totale_tabelle": 0,
            "totale_record": 0,
            "totale_relazioni": 0,
            "mermaid": "",
        }

    try:
        cur = con.cursor()

        # 1. Recupera tutte le tabelle utente (escluse quelle interne di SQLite)
        cur.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC"
        )
        tabelle_raw = cur.fetchall()

        tabelle_info: dict[str, dict[str, Any]] = {}
        tutte_relazioni: list[dict[str, Any]] = []
        totale_record = 0

        for nome_tab, sql_ddl in tabelle_raw:
            # Informazioni colonne tramite PRAGMA table_info
            cur.execute(f'PRAGMA table_info("{nome_tab}")')
            colonne_raw = cur.fetchall()

            # Informazioni chiavi esterne tramite PRAGMA foreign_key_list
            cur.execute(f'PRAGMA foreign_key_list("{nome_tab}")')
            fks_raw = cur.fetchall()

            # Conteggio record live
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{nome_tab}"')
                count_righe = cur.fetchone()[0]
            except Exception:
                count_righe = 0
            totale_record += count_righe

            # Anteprima prime 5 righe
            anteprima_righe = []
            try:
                cur.execute(f'SELECT * FROM "{nome_tab}" LIMIT 5')
                campi = [d[0] for d in cur.description] if cur.description else []
                for row in cur.fetchall():
                    anteprima_righe.append(dict(zip(campi, row)))
            except Exception:
                campi = []

            # Mappa delle chiavi esterne per colonna
            colonne_fk_map: dict[str, list[dict[str, Any]]] = {}
            fks_tabella: list[dict[str, Any]] = []
            for fk in fks_raw:
                # fk = (id, seq, table, from, to, on_update, on_delete, match)
                fk_id, seq, target_table, from_col, to_col, on_upd, on_del, _ = fk
                fk_obj = {
                    "id": fk_id,
                    "seq": seq,
                    "tabella_destinazione": target_table,
                    "colonna_sorgente": from_col,
                    "colonna_destinazione": to_col,
                    "on_update": on_upd,
                    "on_delete": on_del,
                }
                fks_tabella.append(fk_obj)
                colonne_fk_map.setdefault(from_col, []).append(fk_obj)

                tutte_relazioni.append(
                    {
                        "id": f"{nome_tab}_{from_col}_{target_table}_{to_col}",
                        "tabella_da": nome_tab,
                        "colonna_da": from_col,
                        "tabella_a": target_table,
                        "colonna_a": to_col,
                        "on_update": on_upd,
                        "on_delete": on_del,
                        "cardinalita": "N:1",
                        "descrizione": f"{nome_tab}.{from_col} ➔ {target_table}.{to_col}",
                    }
                )

            # Informazioni indici
            cur.execute(f'PRAGMA index_list("{nome_tab}")')
            indici_raw = cur.fetchall()
            indici = []
            for idx in indici_raw:
                # (seq, name, unique, origin, partial)
                indici.append(
                    {
                        "nome": idx[1],
                        "unique": bool(idx[2]),
                        "origine": idx[3],
                    }
                )

            colonne_dettaglio = []
            chiavi_primarie = []
            for col in colonne_raw:
                # col = (cid, name, type, notnull, dflt_value, pk)
                cid, col_name, col_type, notnull, dflt, pk = col
                is_pk = bool(pk)
                if is_pk:
                    chiavi_primarie.append(col_name)

                fks_colonna = colonne_fk_map.get(col_name, [])
                colonne_dettaglio.append(
                    {
                        "cid": cid,
                        "nome": col_name,
                        "tipo": col_type or "TEXT",
                        "notnull": bool(notnull),
                        "default": dflt,
                        "pk": is_pk,
                        "fk": len(fks_colonna) > 0,
                        "relazioni_fk": fks_colonna,
                    }
                )

            tabelle_info[nome_tab] = {
                "nome": nome_tab,
                "record_count": count_righe,
                "colonne": colonne_dettaglio,
                "chiavi_primarie": chiavi_primarie,
                "chiavi_esterne": fks_tabella,
                "indici": indici,
                "sql_ddl": sql_ddl or "",
                "anteprima_righe": anteprima_righe,
            }

        # 2. Generazione dinamica del diagramma Mermaid ER
        mermaid_lines = ["erDiagram"]
        # Relazioni
        if tutte_relazioni:
            for rel in tutte_relazioni:
                # In Mermaid: Parent ||--o{ Child (1 a molti)
                # target_table è il genitore (1), nome_tab è il figlio (N)
                parent = rel["tabella_a"]
                child = rel["tabella_da"]
                label = f"{rel['colonna_da']} -> {rel['colonna_a']}"
                mermaid_lines.append(f'    {parent} ||--o{{ {child} : "{label}"')
        else:
            mermaid_lines.append("    %% Nessuna foreign key definita esplicitamente")

        # Entità e attributi
        for nome_tab, t_info in tabelle_info.items():
            mermaid_lines.append(f"    {nome_tab} {{")
            for c in t_info["colonne"]:
                san_tipo = _sanifica_tipo_mermaid(c["tipo"])
                san_nome = re.sub(r"[^a-zA-Z0-9_]", "_", c["nome"])
                tags = []
                if c["pk"]:
                    tags.append("PK")
                if c["fk"]:
                    tags.append("FK")
                tag_str = (" " + ",".join(tags)) if tags else ""
                mermaid_lines.append(f"        {san_tipo} {san_nome}{tag_str}")
            mermaid_lines.append("    }")

        codice_mermaid = "\n".join(mermaid_lines)

        return {
            "ok": True,
            "database": path.name,
            "percorso": str(path),
            "dimensione_bytes": dimensione,
            "dimensione_formattata": formatta_dimensione(dimensione),
            "totale_tabelle": len(tabelle_info),
            "totale_record": totale_record,
            "totale_relazioni": len(tutte_relazioni),
            "tabelle": tabelle_info,
            "relazioni": tutte_relazioni,
            "mermaid": codice_mermaid,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": f"Errore durante l'ispezione dello schema: {exc}",
            "database": path.name,
            "tabelle": {},
            "relazioni": [],
            "totale_tabelle": 0,
            "totale_record": 0,
            "totale_relazioni": 0,
            "mermaid": "",
        }
    finally:
        con.close()


def leggi_dati_tabella(
    nome_tabella: str, limite: int = 50, offset: int = 0, db_path: str | Path | None = None
) -> dict[str, Any]:
    """
    Legge righe paginate da una tabella specifica in modo sicuro (read-only).
    Verifica che il nome della tabella sia effettivamente presente nel database.
    """
    path = risolvi_accessi_db() if db_path is None else Path(db_path).resolve()
    if not path.is_file():
        return {"ok": False, "error": "Database non trovato."}

    limite = max(1, min(int(limite), 100))
    offset = max(0, int(offset))

    try:
        con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    try:
        cur = con.cursor()
        # Verifica esistenza tabella
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (nome_tabella,)
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": f"Tabella '{nome_tabella}' non trovata nel database."}

        # Totale record
        cur.execute(f'SELECT COUNT(*) FROM "{nome_tabella}"')
        totale = cur.fetchone()[0]

        # Righe con limite e offset
        cur.execute(f'SELECT * FROM "{nome_tabella}" LIMIT ? OFFSET ?', (limite, offset))
        colonne = [d[0] for d in cur.description] if cur.description else []
        righe = [list(r) for r in cur.fetchall()]

        return {
            "ok": True,
            "tabella": nome_tabella,
            "colonne": colonne,
            "righe": righe,
            "totale": totale,
            "limite": limite,
            "offset": offset,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()

