"""
Backend/schema_inspector.py — Ispezione dinamica dello schema dei database SQLite:
- accessi.sqlite (Teatro Operativo — 3 tabelle: operatori, depositi, accessi)
- archivio_recuperato.sqlite (Archivio Erebo & Varco V-59 — 14 tabelle decodificate)

Fornisce funzioni per estrarre in modo dinamico e completo:
- Elenco tabelle, colonne, tipi di dato, vincoli NOT NULL e PRIMARY KEY.
- Relazioni di chiave esterna (FOREIGN KEY) e cardinalità relazionale.
- Conteggio record in tempo reale e anteprima righe di esempio.
- DDL completo (CREATE TABLE) generato da SQLite.
- Generazione automatica del diagramma Mermaid ER unificato o per database.
- Query di lettura sicure (SELECT) con paginazione per l'anteprima nel Frontend.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

try:
    from Backend.config import risolvi_accessi_db, risolvi_archivio_recuperato_db
except ImportError:
    from config import risolvi_accessi_db, risolvi_archivio_recuperato_db


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


# Metadati e descrizioni semantiche delle tabelle per entrambi i database
METADATI_TABELLE_NOTE: dict[str, dict[str, Any]] = {
    # Tabelle accessi.sqlite
    "operatori": {
        "nome_logico": "operatori",
        "database": "accessi.sqlite",
        "descrizione": "Anagrafica personale autorizzato con nome e matricola nel teatro operativo.",
    },
    "depositi": {
        "nome_logico": "depositi",
        "database": "accessi.sqlite",
        "descrizione": "Strutture logistiche, depositi rifornimenti e bunker suddivisi per settore.",
    },
    "accessi": {
        "nome_logico": "accessi",
        "database": "accessi.sqlite",
        "descrizione": "Registro transiti, pratiche autorizzative, codici di sblocco e scadenze.",
    },
    # Tabelle archivio_recuperato.sqlite (Archivio Erebo / Varco V-59)
    "r02": {
        "nome_logico": "archivi",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Sedi archivi clinici e rifugi protetti (es. Archivio Erebo).",
    },
    "r03": {
        "nome_logico": "operatori",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Anagrafica personale di missione e codici matricola (PX).",
    },
    "r06": {
        "nome_logico": "abilitazioni_ruolo",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Qualifiche operative certificate per operatore (SANITARIO / SICUREZZA).",
    },
    "r07": {
        "nome_logico": "varchi",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Varchi d'accesso fisici alle strutture cliniche (es. Varco V-59).",
    },
    "r08": {
        "nome_logico": "permessi_squadre_varco",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Autorizzazioni squadrarie per specifico varco e ruolo con validità temporale.",
    },
    "r09": {
        "nome_logico": "terminali",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Terminali di autenticazione varco e canali radio (Iota, Gamma, Quarzo, ecc.).",
    },
    "r11": {
        "nome_logico": "squadre",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Anagrafica squadre operative d'emergenza (Unità 5-Ardesia, Unità 5-Tufo, ecc.).",
    },
    "r13": {
        "nome_logico": "chiavi_terminali",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Codici chiave e PIN crittografici di sblocco validi per ciascun terminale.",
    },
    "r14": {
        "nome_logico": "repliche_storiche_permessi",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Backup e repliche storiche dei permessi del turno precedente.",
    },
    "r15": {
        "nome_logico": "log_transiti_accessi",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Registro cronologico degli accessi ed esiti transito sui terminali.",
    },
    "e04": {
        "nome_logico": "sospensioni_operatori",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Eventi disciplinari o sanitari di sospensione temporanea operatori.",
    },
    "e10": {
        "nome_logico": "revoche_permessi",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Revoche anticipate e blocchi dei permessi di transito al varco.",
    },
    "m05": {
        "nome_logico": "finestre_operative_terminali",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Finestre orarie di operatività e accensione dei terminali di varco.",
    },
    "m12": {
        "nome_logico": "membri_squadra",
        "database": "archivio_recuperato.sqlite",
        "descrizione": "Assegnazione degli operatori alle rispettive squadre con intervallo temporale.",
    },
}

# Relazioni relazionali verificate per archivio_recuperato.sqlite
RELAZIONI_NOTE_RECUPERATE: list[dict[str, Any]] = [
    {"tabella_da": "r07", "colonna_da": "k1", "tabella_a": "r02", "colonna_a": "k0", "descrizione": "r07.k1 ➔ r02.k0 (Varchi ➔ Archivi)"},
    {"tabella_da": "m12", "colonna_da": "k1", "tabella_a": "r03", "colonna_a": "k0", "descrizione": "m12.k1 ➔ r03.k0 (Membri ➔ Operatori)"},
    {"tabella_da": "m12", "colonna_da": "k2", "tabella_a": "r11", "colonna_a": "k0", "descrizione": "m12.k2 ➔ r11.k0 (Membri ➔ Squadre)"},
    {"tabella_da": "r06", "colonna_da": "k1", "tabella_a": "r03", "colonna_a": "k0", "descrizione": "r06.k1 ➔ r03.k0 (Abilitazioni ➔ Operatori)"},
    {"tabella_da": "e04", "colonna_da": "k1", "tabella_a": "r03", "colonna_a": "k0", "descrizione": "e04.k1 ➔ r03.k0 (Sospensioni ➔ Operatori)"},
    {"tabella_da": "r08", "colonna_da": "k1", "tabella_a": "r11", "colonna_a": "k0", "descrizione": "r08.k1 ➔ r11.k0 (Permessi ➔ Squadre)"},
    {"tabella_da": "r08", "colonna_da": "k2", "tabella_a": "r07", "colonna_a": "k0", "descrizione": "r08.k2 ➔ r07.k0 (Permessi ➔ Varchi)"},
    {"tabella_da": "e10", "colonna_da": "k1", "tabella_a": "r08", "colonna_a": "k0", "descrizione": "e10.k1 ➔ r08.k0 (Revoche ➔ Permessi)"},
    {"tabella_da": "r09", "colonna_da": "k1", "tabella_a": "r07", "colonna_a": "k0", "descrizione": "r09.k1 ➔ r07.k0 (Terminali ➔ Varchi)"},
    {"tabella_da": "m05", "colonna_da": "k1", "tabella_a": "r09", "colonna_a": "k0", "descrizione": "m05.k1 ➔ r09.k0 (Finestre ➔ Terminali)"},
    {"tabella_da": "r13", "colonna_da": "k1", "tabella_a": "r09", "colonna_a": "k0", "descrizione": "r13.k1 ➔ r09.k0 (Chiavi ➔ Terminali)"},
    {"tabella_da": "r14", "colonna_da": "k1", "tabella_a": "r11", "colonna_a": "k0", "descrizione": "r14.k1 ➔ r11.k0 (Repliche ➔ Squadre)"},
    {"tabella_da": "r14", "colonna_da": "k2", "tabella_a": "r07", "colonna_a": "k0", "descrizione": "r14.k2 ➔ r07.k0 (Repliche ➔ Varchi)"},
    {"tabella_da": "r15", "colonna_da": "k1", "tabella_a": "r09", "colonna_a": "k0", "descrizione": "r15.k1 ➔ r09.k0 (Log ➔ Terminali)"},
    {"tabella_da": "r15", "colonna_da": "k2", "tabella_a": "r03", "colonna_a": "k0", "descrizione": "r15.k2 ➔ r03.k0 (Log ➔ Operatori)"},
]

# Dizionario semantico delle descrizioni di dominio per entrambe le basi di dati
DESCRIZIONI_COLONNE_NOTE: dict[tuple[str, str], str] = {
    # accessi.sqlite
    ("operatori", "id"): "Identificativo progressivo univoco dell'operatore autorizzato (Chiave Primaria).",
    ("operatori", "nome"): "Nome in codice o matricola identificativa dell'operatore autorizzato (es. Operatore 098).",
    ("depositi", "id"): "Identificativo progressivo univoco del deposito o struttura logistica (Chiave Primaria).",
    ("depositi", "nome"): "Denominazione identificativa o codice del deposito (es. Deposito 030, Forte Cenere).",
    ("depositi", "settore"): "Settore geografico o zona perimetrale di appartenenza del deposito (es. Z3, D6, Z8).",
    ("accessi", "id"): "Identificativo progressivo univoco della registrazione dell'accesso (Chiave Primaria).",
    ("accessi", "operatore_id"): "Chiave esterna (FK): riferimento all'operatore che ha effettuato l'accesso (operatori.id).",
    ("accessi", "deposito_id"): "Chiave esterna (FK): riferimento alla struttura/deposito di destinazione (depositi.id).",
    ("accessi", "pratica"): "Codice identificativo alfanumerico del fascicolo o pratica autorizzativa (es. RV753).",
    ("accessi", "codice"): "Codice di sicurezza o PIN crittografico numerico di sblocco varco (es. 057284).",
    ("accessi", "stato"): "Stato di validità dell'accesso: 'attivo' (transito autorizzato) oppure 'revocato'.",
    ("accessi", "valido_fino"): "Data e ora limite di validità dell'autorizzazione al transito (YYYY-MM-DD HH:MM).",

    # archivio_recuperato.sqlite
    ("r02", "k0"): "Identificativo progressivo univoco della sede archivio/rifugio protetto (Chiave Primaria).",
    ("r02", "v1"): "Denominazione identificativa dell'archivio (es. Archivio Erebo, Archivio Distretto 5-31).",
    ("r02", "v2"): "Codice alfanumerico identificativo della struttura (es. AR-ERE-7685).",
    ("r03", "k0"): "Identificativo progressivo univoco dell'operatore autorizzato (Chiave Primaria).",
    ("r03", "v1"): "Nome completo dell'operatore o del personale (es. Tina Rocchi, Ugo Valli).",
    ("r03", "v2"): "Codice matricola identificativo dell'operatore (es. PX-803574, PX-250896).",
    ("r06", "k0"): "Identificativo progressivo dell'abilitazione di ruolo (Chiave Primaria).",
    ("r06", "k1"): "Chiave esterna (FK): riferimento all'operatore qualificato (r03.k0).",
    ("r06", "v1"): "Ruolo operativo certificato: 'SANITARIO' o 'SICUREZZA'.",
    ("r06", "ts_a"): "Data e ora di inizio validità della certificazione di ruolo.",
    ("r06", "ts_b"): "Data e ora di termine/scadenza della certificazione di ruolo.",
    ("r07", "k0"): "Identificativo progressivo univoco del varco d'accesso (Chiave Primaria).",
    ("r07", "k1"): "Chiave esterna (FK): riferimento all'archivio/struttura di appartenenza (r02.k0).",
    ("r07", "v1"): "Codice identificativo del varco (es. V-59, V-12).",
    ("r08", "k0"): "Identificativo progressivo del permesso squadrario (Chiave Primaria).",
    ("r08", "k1"): "Chiave esterna (FK): riferimento alla squadra autorizzata (r11.k0).",
    ("r08", "k2"): "Chiave esterna (FK): riferimento al varco autorizzato (r07.k0).",
    ("r08", "v1"): "Ruolo operativo previsto dal permesso: 'SANITARIO' o 'SICUREZZA'.",
    ("r08", "ts_a"): "Inizio validità temporale del permesso d'accesso al varco.",
    ("r08", "ts_b"): "Termine di validità temporale del permesso d'accesso al varco.",
    ("r08", "v2"): "Stato di validità del permesso: 'ATTIVO' o 'REVOCATO'.",
    ("r09", "k0"): "Identificativo progressivo univoco del terminale varco (Chiave Primaria).",
    ("r09", "k1"): "Chiave esterna (FK): riferimento al varco d'installazione (r07.k0).",
    ("r09", "v1"): "Canale di comunicazione / frequenza radio (es. Iota, Gamma, Quarzo, Rame, Ferro).",
    ("r09", "v2"): "Stato operativo del terminale: 'OPERATIVO' o 'FUORI_SERVIZIO'.",
    ("r11", "k0"): "Identificativo progressivo univoco della squadra (Chiave Primaria).",
    ("r11", "v1"): "Nome identificativo della squadra operativa (es. Unità 5-Ardesia, Unità 5-Tufo).",
    ("r13", "k0"): "Identificativo progressivo del codice chiave (Chiave Primaria).",
    ("r13", "k1"): "Chiave esterna (FK): riferimento al terminale associato (r09.k0).",
    ("r13", "v1"): "Codice chiave / PIN crittografico di sblocco (es. 642103, 500295).",
    ("r13", "ts_a"): "Data e ora di inizio validità del codice chiave.",
    ("r13", "ts_b"): "Data e ora di scadenza del codice chiave.",
    ("r14", "k0"): "Identificativo progressivo della replica storica (Chiave Primaria).",
    ("r14", "k1"): "Chiave esterna (FK): riferimento alla squadra (r11.k0).",
    ("r14", "k2"): "Chiave esterna (FK): riferimento al varco (r07.k0).",
    ("r14", "k3"): "Codice progressivo del turno o blocco replica.",
    ("r14", "v1"): "Ruolo operativo associato alla replica.",
    ("r14", "ts_a"): "Inizio validità del turno precedente.",
    ("r14", "ts_b"): "Termine validità del turno precedente.",
    ("r14", "v2"): "Stato del permesso storico.",
    ("r14", "ts_c"): "Timestamp di sincronizzazione della replica.",
    ("r14", "v3"): "Annotazione o causale di replica (es. REPLICA_TURNO_PRECEDENTE).",
    ("r15", "k0"): "Identificativo progressivo dell'evento di log transito (Chiave Primaria).",
    ("r15", "k1"): "Chiave esterna (FK): riferimento al terminale interessato (r09.k0).",
    ("r15", "k2"): "Chiave esterna (FK): riferimento all'operatore transitato (r03.k0).",
    ("r15", "ts_a"): "Timestamp dell'evento di transito registrato.",
    ("r15", "v1"): "Esito del tentativo di transito (es. 'OK', 'NEGATO').",
    ("r15", "v2"): "Codice o esito di autenticazione del transito.",
    ("e04", "k0"): "Identificativo evento di sospensione (Chiave Primaria).",
    ("e04", "k1"): "Chiave esterna (FK): riferimento all'operatore sospeso (r03.k0).",
    ("e04", "ts_a"): "Data e ora di inizio della sospensione.",
    ("e04", "ts_b"): "Data e ora di fine della sospensione.",
    ("e04", "v1"): "Motivazione o tipologia dell'evento di sospensione.",
    ("e10", "k0"): "Identificativo evento di revoca permesso (Chiave Primaria).",
    ("e10", "k1"): "Chiave esterna (FK): riferimento al permesso revocato (r08.k0).",
    ("e10", "ts_a"): "Data e ora esatta dell'avvenuta revoca del permesso.",
    ("e10", "v1"): "Motivo o causale della revoca immediata.",
    ("m05", "k0"): "Identificativo finestra temporale (Chiave Primaria).",
    ("m05", "k1"): "Chiave esterna (FK): riferimento al terminale abilitato (r09.k0).",
    ("m05", "ts_a"): "Apertura della finestra oraria di operatività del terminale.",
    ("m05", "ts_b"): "Chiusura della finestra oraria di operatività del terminale.",
    ("m12", "k0"): "Identificativo assegnazione operatore-squadra (Chiave Primaria).",
    ("m12", "k1"): "Chiave esterna (FK): riferimento all'operatore membro (r03.k0).",
    ("m12", "k2"): "Chiave esterna (FK): riferimento alla squadra assegnata (r11.k0).",
    ("m12", "ts_a"): "Inizio del periodo di assegnazione alla squadra.",
    ("m12", "ts_b"): "Termine del periodo di assegnazione alla squadra.",
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
    """Restituisce una descrizione esaustiva per la colonna."""
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
    if any(k in c_low for k in ["data", "date", "created_at", "updated_at", "timestamp", "scadenza", "valido_fino", "ts_a", "ts_b", "ts_c"]):
        return "Riferimento temporale (data/ora) registrato in formato standard."
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


def ispeziona_database_singolo(path: Path) -> dict[str, Any]:
    """Introspezione completa di un singolo file SQLite."""
    if not path.is_file():
        return {
            "ok": False,
            "error": f"Database non trovato nel percorso: {path}",
            "database": path.name,
            "tabelle": {},
            "relazioni": [],
            "totale_tabelle": 0,
            "totale_record": 0,
            "totale_relazioni": 0,
            "dimensione_bytes": 0,
            "dimensione_formattata": "0 B",
        }

    dimensione = path.stat().st_size
    is_recuperato = "archivio_recuperato" in path.name.lower()

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
            "dimensione_bytes": dimensione,
            "dimensione_formattata": formatta_dimensione(dimensione),
        }

    try:
        cur = con.cursor()
        cur.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC"
        )
        tabelle_raw = cur.fetchall()

        tabelle_info: dict[str, dict[str, Any]] = {}
        tutte_relazioni: list[dict[str, Any]] = []
        totale_record = 0

        # Se archivio_recuperato, pre-popola la mappa delle relazioni verificate
        relazioni_note_per_tab: dict[str, list[dict[str, Any]]] = {}
        if is_recuperato:
            for rel in RELAZIONI_NOTE_RECUPERATE:
                relazioni_note_per_tab.setdefault(rel["tabella_da"], []).append(rel)

        for nome_tab, sql_ddl in tabelle_raw:
            meta_tab = METADATI_TABELLE_NOTE.get(nome_tab, {
                "nome_logico": nome_tab,
                "database": path.name,
                "descrizione": f"Tabella {nome_tab} di {path.name}",
            })

            cur.execute(f'PRAGMA table_info("{nome_tab}")')
            colonne_raw = cur.fetchall()

            cur.execute(f'PRAGMA foreign_key_list("{nome_tab}")')
            fks_raw = cur.fetchall()

            try:
                cur.execute(f'SELECT COUNT(*) FROM "{nome_tab}"')
                count_righe = cur.fetchone()[0]
            except Exception:
                count_righe = 0
            totale_record += count_righe

            anteprima_righe = []
            try:
                cur.execute(f'SELECT * FROM "{nome_tab}" LIMIT 5')
                campi = [d[0] for d in cur.description] if cur.description else []
                for row in cur.fetchall():
                    anteprima_righe.append(dict(zip(campi, row)))
            except Exception:
                campi = []

            colonne_fk_map: dict[str, list[dict[str, Any]]] = {}
            fks_tabella: list[dict[str, Any]] = []

            for fk in fks_raw:
                fk_id, seq, target_table, from_col, to_col, on_upd, on_del, _ = fk
                fk_obj = {
                    "id": fk_id,
                    "seq": seq,
                    "tabella_destinazione": target_table,
                    "colonna_sorgente": from_col,
                    "colonna_destinazione": to_col,
                    "on_update": on_upd or "NO ACTION",
                    "on_delete": on_del or "NO ACTION",
                }
                fks_tabella.append(fk_obj)
                colonne_fk_map.setdefault(from_col, []).append(fk_obj)

                tutte_relazioni.append({
                    "id": f"{nome_tab}_{from_col}_{target_table}_{to_col}",
                    "database": path.name,
                    "tabella_da": nome_tab,
                    "colonna_da": from_col,
                    "tabella_a": target_table,
                    "colonna_a": to_col,
                    "on_update": on_upd or "NO ACTION",
                    "on_delete": on_del or "NO ACTION",
                    "cardinalita": "N:1",
                    "descrizione": f"{nome_tab}.{from_col} ➔ {target_table}.{to_col}",
                })

            # Integra relazioni note per archivio_recuperato se PRAGMA vuoto
            if is_recuperato and not fks_raw and nome_tab in relazioni_note_per_tab:
                for idx_rel, r_not in enumerate(relazioni_note_per_tab[nome_tab]):
                    fk_obj = {
                        "id": idx_rel,
                        "seq": 0,
                        "tabella_destinazione": r_not["tabella_a"],
                        "colonna_sorgente": r_not["colonna_da"],
                        "colonna_destinazione": r_not["colonna_a"],
                        "on_update": "CASCADE",
                        "on_delete": "RESTRICT",
                    }
                    fks_tabella.append(fk_obj)
                    colonne_fk_map.setdefault(r_not["colonna_da"], []).append(fk_obj)
                    tutte_relazioni.append({
                        "id": f"{nome_tab}_{r_not['colonna_da']}_{r_not['tabella_a']}_{r_not['colonna_a']}",
                        "database": path.name,
                        "tabella_da": nome_tab,
                        "colonna_da": r_not["colonna_da"],
                        "tabella_a": r_not["tabella_a"],
                        "colonna_a": r_not["colonna_a"],
                        "on_update": "CASCADE",
                        "on_delete": "RESTRICT",
                        "cardinalita": "N:1",
                        "descrizione": r_not.get("descrizione") or f"{nome_tab}.{r_not['colonna_da']} ➔ {r_not['tabella_a']}.{r_not['colonna_a']}",
                    })

            cur.execute(f'PRAGMA index_list("{nome_tab}")')
            indici_raw = cur.fetchall()
            indici = [{"nome": idx[1], "unique": bool(idx[2]), "origine": idx[3]} for idx in indici_raw]

            colonne_dettaglio = []
            chiavi_primarie = []
            for col in colonne_raw:
                cid, col_name, col_type, notnull, dflt, pk = col
                is_pk = bool(pk)
                if is_pk:
                    chiavi_primarie.append(col_name)

                fks_colonna = colonne_fk_map.get(col_name, [])
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

                colonne_dettaglio.append({
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
                })

            tabelle_info[nome_tab] = {
                "nome": nome_tab,
                "nome_logico": meta_tab.get("nome_logico", nome_tab),
                "database": path.name,
                "descrizione_tabella": meta_tab.get("descrizione", ""),
                "record_count": count_righe,
                "colonne": colonne_dettaglio,
                "chiavi_primarie": chiavi_primarie,
                "chiavi_esterne": fks_tabella,
                "indici": indici,
                "sql_ddl": sql_ddl or "",
                "anteprima_righe": anteprima_righe,
            }

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
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Errore ispezione {path.name}: {exc}",
            "database": path.name,
            "tabelle": {},
            "relazioni": [],
            "totale_tabelle": 0,
            "totale_record": 0,
            "totale_relazioni": 0,
            "dimensione_bytes": dimensione,
            "dimensione_formattata": formatta_dimensione(dimensione),
        }
    finally:
        con.close()


def _genera_codice_mermaid(tabelle_info: dict[str, Any], tutte_relazioni: list[dict[str, Any]]) -> str:
    """Genera codice Mermaid ER per le tabelle e relazioni fornite."""
    mermaid_lines = ["erDiagram"]
    if tutte_relazioni:
        for rel in tutte_relazioni:
            parent = rel["tabella_a"]
            child = rel["tabella_da"]
            label = f"{rel['colonna_da']} -> {rel['colonna_a']}"
            mermaid_lines.append(f'    {parent} ||--o{{ {child} : "{label}"')
    else:
        mermaid_lines.append("    %% Nessuna foreign key rilevata")

    for nome_tab, t_info in tabelle_info.items():
        mermaid_lines.append(f"    {nome_tab} {{")
        for c in t_info.get("colonne", []):
            san_tipo = _sanifica_tipo_mermaid(c["tipo"])
            san_nome = re.sub(r"[^a-zA-Z0-9_]", "_", c["nome"])
            tags = []
            if c.get("pk"):
                tags.append("PK")
            if c.get("fk"):
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

    return "\n".join(mermaid_lines)


def estrai_schema_database(
    db_target: str | Path | None = None, db_path: str | Path | None = None
) -> dict[str, Any]:
    """
    Introspezione completa e dinamica dei database SQLite (accessi.sqlite e archivio_recuperato.sqlite).
    Se db_target/db_path è None o 'all', restituisce lo schema unificato di entrambi i database (17 tabelle).
    Se specificato 'accessi', restituisce solo accessi.sqlite (3 tabelle).
    Se specificato 'archivio_recuperato' o 'recuperato', restituisce solo archivio_recuperato.sqlite (14 tabelle).
    """
    target = str(db_target or db_path or "all").strip().lower()

    path_acc = risolvi_accessi_db()
    path_rec = risolvi_archivio_recuperato_db()

    # Richiesta specifica per singolo file
    if target in {"accessi", "accessi.sqlite"}:
        schema = ispeziona_database_singolo(path_acc)
        schema["mermaid"] = _genera_codice_mermaid(schema["tabelle"], schema["relazioni"])
        schema["database_selezionato"] = "accessi.sqlite"
        schema["databases"] = [{
            "id": "accessi",
            "nome": "accessi.sqlite",
            "etichetta": "accessi.sqlite (Teatro Operativo)",
            "totale_tabelle": schema["totale_tabelle"],
            "totale_record": schema["totale_record"],
            "dimensione": schema["dimensione_formattata"],
        }]
        return schema

    if target in {"archivio_recuperato", "archivio_recuperato.sqlite", "recuperato", "erebo"}:
        schema = ispeziona_database_singolo(path_rec)
        schema["mermaid"] = _genera_codice_mermaid(schema["tabelle"], schema["relazioni"])
        schema["database_selezionato"] = "archivio_recuperato.sqlite"
        schema["databases"] = [{
            "id": "archivio_recuperato",
            "nome": "archivio_recuperato.sqlite",
            "etichetta": "archivio_recuperato.sqlite (Archivio Erebo - Varco V-59)",
            "totale_tabelle": schema["totale_tabelle"],
            "totale_record": schema["totale_record"],
            "dimensione": schema["dimensione_formattata"],
        }]
        return schema

    if db_path and Path(db_path).is_file():
        schema = ispeziona_database_singolo(Path(db_path))
        schema["mermaid"] = _genera_codice_mermaid(schema["tabelle"], schema["relazioni"])
        schema["database_selezionato"] = Path(db_path).name
        return schema

    # Schema unificato predefinito (tutti i database: accessi + archivio_recuperato)
    schema_acc = ispeziona_database_singolo(path_acc)
    schema_rec = ispeziona_database_singolo(path_rec)

    tutte_tabelle: dict[str, dict[str, Any]] = {}
    if schema_acc.get("ok"):
        tutte_tabelle.update(schema_acc.get("tabelle", {}))
    if schema_rec.get("ok"):
        tutte_tabelle.update(schema_rec.get("tabelle", {}))

    tutte_relazioni: list[dict[str, Any]] = []
    if schema_acc.get("ok"):
        tutte_relazioni.extend(schema_acc.get("relazioni", []))
    if schema_rec.get("ok"):
        tutte_relazioni.extend(schema_rec.get("relazioni", []))

    tot_bytes = (schema_acc.get("dimensione_bytes", 0)) + (schema_rec.get("dimensione_bytes", 0))
    tot_rec = (schema_acc.get("totale_record", 0)) + (schema_rec.get("totale_record", 0))

    codice_mermaid = _genera_codice_mermaid(tutte_tabelle, tutte_relazioni)

    return {
        "ok": True,
        "database": "Tutti i Database (accessi.sqlite + archivio_recuperato.sqlite)",
        "database_selezionato": "all",
        "percorso": f"{path_acc.name} & {path_rec.name}",
        "dimensione_bytes": tot_bytes,
        "dimensione_formattata": formatta_dimensione(tot_bytes),
        "totale_tabelle": len(tutte_tabelle),
        "totale_record": tot_rec,
        "totale_relazioni": len(tutte_relazioni),
        "databases": [
            {
                "id": "accessi",
                "nome": "accessi.sqlite",
                "etichetta": "accessi.sqlite (Teatro Operativo)",
                "percorso": str(path_acc),
                "totale_tabelle": schema_acc.get("totale_tabelle", 0),
                "totale_record": schema_acc.get("totale_record", 0),
                "dimensione": schema_acc.get("dimensione_formattata", "0 B"),
                "tabelle": list(schema_acc.get("tabelle", {}).keys()),
            },
            {
                "id": "archivio_recuperato",
                "nome": "archivio_recuperato.sqlite",
                "etichetta": "archivio_recuperato.sqlite (Archivio Erebo - Varco V-59)",
                "percorso": str(path_rec),
                "totale_tabelle": schema_rec.get("totale_tabelle", 0),
                "totale_record": schema_rec.get("totale_record", 0),
                "dimensione": schema_rec.get("dimensione_formattata", "0 B"),
                "tabelle": list(schema_rec.get("tabelle", {}).keys()),
            },
        ],
        "tabelle": tutte_tabelle,
        "relazioni": tutte_relazioni,
        "mermaid": codice_mermaid,
    }


def leggi_dati_tabella(
    nome_tabella: str,
    limite: int = 50,
    offset: int = 0,
    db_path: str | Path | None = None,
    db_target: str | Path | None = None,
) -> dict[str, Any]:
    """
    Legge righe paginate da una tabella specifica in modo sicuro (read-only).
    Risolve automaticamente se la tabella appartiene ad accessi.sqlite o ad archivio_recuperato.sqlite.
    """
    if not nome_tabella or not isinstance(nome_tabella, str):
        return {"ok": False, "error": "Nome tabella non valido."}

    nome_clean = nome_tabella.strip()
    nome_low = nome_clean.lower()

    # Risoluzione del database opportuno
    path: Path
    if db_path and Path(db_path).is_file():
        path = Path(db_path).resolve()
    elif db_target in {"archivio_recuperato", "recuperato", "archivio_recuperato.sqlite"}:
        path = risolvi_archivio_recuperato_db()
    elif db_target in {"accessi", "accessi.sqlite"}:
        path = risolvi_accessi_db()
    else:
        # Auto-routing basato sul nome tabella
        tabelle_rec = {"e04", "e10", "m05", "m12", "r02", "r03", "r06", "r07", "r08", "r09", "r11", "r13", "r14", "r15"}
        if nome_low in tabelle_rec:
            path = risolvi_archivio_recuperato_db()
        elif nome_low in {"operatori", "depositi", "accessi"}:
            path = risolvi_accessi_db()
        else:
            # Fallback: controlla prima accessi poi recuperato
            p_acc = risolvi_accessi_db()
            p_rec = risolvi_archivio_recuperato_db()
            path = p_acc

    if not path.is_file():
        return {"ok": False, "error": f"Database non trovato: {path}"}

    limite = max(1, min(int(limite), 100))
    offset = max(0, int(offset))

    meta_tab = METADATI_TABELLE_NOTE.get(nome_low, {
        "nome_logico": nome_clean,
        "database": path.name,
        "descrizione": "",
    })

    try:
        con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except Exception as exc:
        return {"ok": False, "error": f"Impossibile aprire il database in sola lettura: {exc}"}

    try:
        cur = con.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (nome_clean,)
        )
        row = cur.fetchone()
        if not row:
            # Se non trovato nel primo DB, prova nel secondo se non esplicitamente specificato
            if not db_path and not db_target:
                p_altro = risolvi_archivio_recuperato_db() if path.name == "accessi.sqlite" else risolvi_accessi_db()
                if p_altro.is_file():
                    con.close()
                    con = sqlite3.connect(f"{p_altro.as_uri()}?mode=ro", uri=True)
                    cur = con.cursor()
                    cur.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (nome_clean,)
                    )
                    row = cur.fetchone()
                    if row:
                        path = p_altro

        if not row:
            return {"ok": False, "error": f"Tabella '{nome_clean}' non trovata in {path.name}."}

        cur.execute(f'SELECT COUNT(*) FROM "{nome_clean}"')
        totale = cur.fetchone()[0]

        cur.execute(f'SELECT * FROM "{nome_clean}" LIMIT ? OFFSET ?', (limite, offset))
        colonne = [d[0] for d in cur.description] if cur.description else []
        righe = [list(r) for r in cur.fetchall()]

        return {
            "ok": True,
            "tabella": nome_clean,
            "nome_logico": meta_tab.get("nome_logico", nome_clean),
            "database": path.name,
            "descrizione": meta_tab.get("descrizione", ""),
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
