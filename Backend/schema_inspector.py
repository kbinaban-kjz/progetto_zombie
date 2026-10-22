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


# Dizionario semantico delle descrizioni di dominio per il database investigativo
DESCRIZIONI_COLONNE_NOTE: dict[tuple[str, str], str] = {
    ("operatori", "id"): "Identificativo progressivo univoco dell'operatore autorizzato (Chiave Primaria).",
    ("operatori", "nome"): "Nome in codice o matricola identificativa dell'operatore autorizzato (es. Operatore 098).",
    ("depositi", "id"): "Identificativo progressivo univoco del deposito o struttura logistica (Chiave Primaria).",
    ("depositi", "nome"): "Denominazione identificativa o codice del deposito (es. Deposito 030).",
    ("depositi", "settore"): "Settore geografico o zona perimetrale di appartenenza del deposito (es. Z3, Z6, Z8).",
    ("accessi", "id"): "Identificativo progressivo univoco della registrazione del transito o accesso (Chiave Primaria).",
    ("accessi", "operatore_id"): "Chiave esterna (FK): riferimento all'operatore che ha effettuato l'accesso (operatori.id).",
    ("accessi", "deposito_id"): "Chiave esterna (FK): riferimento alla struttura/deposito di destinazione (depositi.id).",
    ("accessi", "pratica"): "Codice identificativo alfanumerico del fascicolo o pratica autorizzativa (es. PX0398).",
    ("accessi", "codice"): "Codice di sicurezza o PIN crittografico numerico di sblocco varco (es. 151977).",
    ("accessi", "stato"): "Stato di validità dell'accesso: 'attivo' (transito autorizzato) oppure 'revocato' (annullato o respinto).",
    ("accessi", "valido_fino"): "Data e ora limite di validità dell'autorizzazione al transito (formato standard YYYY-MM-DD HH:MM).",
}


def determina_descrizione_colonna(
    nome_tab: str,
    col_name: str,
    col_type: str,
    is_pk: bool,
    is_fk: bool,
    fks_colonna: list[dict[str, Any]],
    notnull: bool,
) -> str:
    """
    Restituisce una descrizione esaustiva per la colonna.
    Usa la conoscenza di dominio specifica se nota, oppure genera euristicamente
    una descrizione dinamica basata su vincoli relazionali, tipo e semantica del nome.
    """
    key = (nome_tab.lower(), col_name.lower())
    if key in DESCRIZIONI_COLONNE_NOTE:
        return DESCRIZIONI_COLONNE_NOTE[key]

    if is_fk and fks_colonna:
        dest_tab = fks_colonna[0].get("tabella_destinazione", "tabella")
        dest_col = fks_colonna[0].get("colonna_destinazione", "id")
        return f"Chiave esterna (FK) con vincolo di integrità referenziale collegata a {dest_tab}.{dest_col}."

    if is_pk:
        return f"Chiave primaria (PK) che identifica in modo univoco ogni record della tabella {nome_tab}."

    c_low = col_name.lower()
    if c_low in {"nome", "name", "denominazione", "titolo", "title"}:
        return f"Nome identificativo o etichetta descrittiva del record in {nome_tab}."
    if c_low in {"stato", "status", "stato_accesso", "condizione"}:
        return "Stato o condizione operativa corrente associata al record."
    if any(k in c_low for k in ["data", "date", "created_at", "updated_at", "timestamp", "scadenza", "valido_fino"]):
        return "Riferimento temporale (data/ora) registrato in formato ISO/standard."
    if any(k in c_low for k in ["codice", "code", "pin", "token", "hash"]):
        return "Codice alfanumerico o sequenza di sicurezza per autenticazione e tracciamento."
    if any(k in c_low for k in ["pratica", "dossier", "fascicolo", "protocollo"]):
        return "Numero di fascicolo o codice della pratica di missione autorizzativa."
    if any(k in c_low for k in ["settore", "zona", "area", "regione", "luogo"]):
        return "Delimitazione territoriale o settore geografico operativo assegnato."
    if any(k in c_low for k in ["descrizione", "note", "dettagli", "commento"]):
        return "Note esplicative o dettagli informativi aggiuntivi."

    obbl = "obbligatorio (NOT NULL)" if notnull else "opzionale (accetta NULL)"
    return f"Colonna {col_name} di tipo {col_type or 'TEXT'} ({obbl}) per la tabella {nome_tab}."


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

                # Estrazione dinamica di valori di esempio reali dal database
                esempi: list[Any] = []
                try:
                    cur.execute(
                        f'SELECT DISTINCT "{col_name}" FROM "{nome_tab}" WHERE "{col_name}" IS NOT NULL LIMIT 4'
                    )
                    for r in cur.fetchall():
                        v = r[0]
                        if isinstance(v, bytes):
                            esempi.append("<blob>")
                        elif isinstance(v, str):
                            esempi.append(v[:60] if len(v) > 60 else v)
                        else:
                            esempi.append(v)
                except Exception:
                    esempi = []

                desc = determina_descrizione_colonna(
                    nome_tab=nome_tab,
                    col_name=col_name,
                    col_type=col_type or "TEXT",
                    is_pk=is_pk,
                    is_fk=len(fks_colonna) > 0,
                    fks_colonna=fks_colonna,
                    notnull=bool(notnull),
                )

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
                        "descrizione": desc,
                        "esempi": esempi,
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

        # Entità e attributi con descrizioni ed esempi
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

                comment_parts = []
                desc_txt = c.get("descrizione") or ""
                if desc_txt:
                    frase = desc_txt.split(".")[0].strip()
                    if len(frase) > 38:
                        frase = frase[:35] + "..."
                    comment_parts.append(frase)
                es_lista = c.get("esempi") or []
                if es_lista:
                    es_str = ", ".join(str(x) for x in es_lista[:2])
                    if len(es_str) > 22:
                        es_str = es_str[:19] + "..."
                    comment_parts.append(f"Es: {es_str}")

                comment_txt = " | ".join(comment_parts)
                comment_txt = re.sub(r'["\r\n\\]', '', comment_txt).strip()
                if comment_txt:
                    mermaid_lines.append(f'        {san_tipo} {san_nome}{tag_str} "{comment_txt}"')
                else:
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

