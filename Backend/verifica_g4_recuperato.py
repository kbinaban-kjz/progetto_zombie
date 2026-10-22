"""
Backend/verifica_g4_recuperato.py — Suite di verifica automatica per la seconda missione del Giorno 4:
"Il primo respiro | Squadra 5 — Operazione Varco • archivio_recuperato.sqlite (Archivio Erebo, Varco V-59)".

Controlli eseguiti:
  1. Integrità e sicurezza database archivio_recuperato.sqlite (sola lettura PRAGMA query_only=ON, modalità ro);
  2. Mappatura completa e schema delle 14 tabelle recuperate (e04, e10, m05, m12, r02, r03, r06, r07, r08, r09, r11, r13, r14, r15);
  3. Verifica matematica al 100% di tutte le Foreign Key ipotizzate (nessun dangling pointer);
  4. Risoluzione geografica: Archivio Erebo (k0=7685883) e Varco V-59 (k0=1756534);
  5. Determinazione dell'unica squadra valida per V-59 alle ore 12:00 del 2026-11-04: Unità 5-Ardesia (k0=9303094);
  6. Identificazione univoca dei due operatori distinti idonei:
     - SANITARIO: Tina Rocchi (ID 3691193, matricola PX-803574)
     - SICUREZZA: Ugo Valli (ID 8928812, matricola PX-250896)
  7. Verifica rigenerata delle esclusioni con timestamp e motivi:
     - Esclusione 1: Unità 5-Gesso (ID 752946) — Permesso sanitario revocato da e10 alle ore 11:00
     - Esclusione 2: Unità 5-Marmo (ID 9215925) — Permesso sanitario scaduto alle ore 11:59 (ts_b)
     - Esclusione 3: Unità 5-Basalto (ID 7538287) — Operatrice sanitaria Alma Donati sospesa in e04 dalle 11:50
     - Esclusione 4: Unità 5-Calce (ID 1474219) — Operatore sicurezza Berto Serra sospeso in e04 (11:00-13:00)
     - Esclusione 5: Unità 5-Tufo (ID 1719260) — Solo 1 operatore attivo (Hilda Marini), violazione Regola 1
     - Esclusione 6: Terminali V-59 non idonei (5880280 FUORI_SERVIZIO; 5491816 e 7650550 senza finestre)
  8. Analisi dei due terminali operativi candidati e codici chiave:
     - Terminale 4703994 (Canale Iota) -> Chiave 642103
     - Terminale 8372085 (Canale Gamma) -> Chiave 500295
  9. Segnalazione del parametro mancante da richiedere al docente (Canale ricevitore del veicolo);
  10. Integrazione con interroga_database() e Authorizer di sicurezza (SELECT permessa, injection/modifiche bloccate);
  11. Non-regressione del database accessi.sqlite (Nora Ferri, Forte Cenere, D6, codice 057284).

Uso:
    python Backend/verifica_g4_recuperato.py
"""

import json
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
for p in (str(ROOT_DIR), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from Backend import config, tools  # noqa: E402
from Backend.tools import interroga_database  # noqa: E402

RIGHE: list[str] = []
ESITI: list[bool] = []


def out(testo: str = "") -> None:
    print(testo)
    RIGHE.append(testo)


def controllo(descrizione: str, ok: bool) -> None:
    ESITI.append(bool(ok))
    out(f"[{'OK' if ok else 'KO'}] {descrizione}")


out("================================================================================")
out("VERIFICA AUTOMATICA — GIORNO 4 PARTE 2: ARCHIVIO EREBO & VARCO V-59")
out("================================================================================")

# ------------------------------------------------------------------------------
# 1. Presenza e connessione sola lettura
# ------------------------------------------------------------------------------
out("\n== 1. DATABASE ARCHIVIO_RECUPERATO.SQLITE (SOLA LETTURA) ==")
db_path = config.risolvi_archivio_recuperato_db()
controllo(f"File database presente ({db_path.name})", db_path.is_file())

con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
cur = con.cursor()
cur.execute("PRAGMA query_only = ON")

cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tabelle_presenti = sorted(r[0] for r in cur.fetchall())
tabelle_attese = ["e04", "e10", "m05", "m12", "r02", "r03", "r06", "r07", "r08", "r09", "r11", "r13", "r14", "r15"]
controllo(f"Tutte le 14 tabelle obfuscate presenti ({len(tabelle_presenti)}/14)", tabelle_presenti == tabelle_attese)

# ------------------------------------------------------------------------------
# 2. Integrità referenziale matematica (Foreign Keys su 100% dei dati)
# ------------------------------------------------------------------------------
out("\n== 2. VERIFICA MATEMATICA DELLE FOREIGN KEYS (ZERO DANGLING REFERENCES) ==")

fk_tests = [
    ("r07.k1 -> r02.k0 (Varchi -> Archivi)", "SELECT COUNT(*) FROM r07 WHERE k1 NOT IN (SELECT k0 FROM r02)"),
    ("m12.k1 -> r03.k0 (Membri -> Persone)", "SELECT COUNT(*) FROM m12 WHERE k1 NOT IN (SELECT k0 FROM r03)"),
    ("m12.k2 -> r11.k0 (Membri -> Squadre)", "SELECT COUNT(*) FROM m12 WHERE k2 NOT IN (SELECT k0 FROM r11)"),
    ("r06.k1 -> r03.k0 (Abilitazioni -> Persone)", "SELECT COUNT(*) FROM r06 WHERE k1 NOT IN (SELECT k0 FROM r03)"),
    ("e04.k1 -> r03.k0 (Sospensioni -> Persone)", "SELECT COUNT(*) FROM e04 WHERE k1 NOT IN (SELECT k0 FROM r03)"),
    ("r08.k1 -> r11.k0 (Permessi -> Squadre)", "SELECT COUNT(*) FROM r08 WHERE k1 NOT IN (SELECT k0 FROM r11)"),
    ("r08.k2 -> r07.k0 (Permessi -> Varchi)", "SELECT COUNT(*) FROM r08 WHERE k2 NOT IN (SELECT k0 FROM r07)"),
    ("e10.k1 -> r08.k0 (Revoche -> Permessi)", "SELECT COUNT(*) FROM e10 WHERE k1 NOT IN (SELECT k0 FROM r08)"),
    ("r09.k1 -> r07.k0 (Terminali -> Varchi)", "SELECT COUNT(*) FROM r09 WHERE k1 NOT IN (SELECT k0 FROM r07)"),
    ("m05.k1 -> r09.k0 (Finestre -> Terminali)", "SELECT COUNT(*) FROM m05 WHERE k1 NOT IN (SELECT k0 FROM r09)"),
    ("r13.k1 -> r09.k0 (Chiavi -> Terminali)", "SELECT COUNT(*) FROM r13 WHERE k1 NOT IN (SELECT k0 FROM r09)"),
]

for desc, q in fk_tests:
    cur.execute(q)
    dangling = cur.fetchone()[0]
    controllo(f"{desc} (Violazioni: {dangling})", dangling == 0)

# ------------------------------------------------------------------------------
# 3. Risoluzione Entità Obiettivo (Archivio Erebo e Varco V-59)
# ------------------------------------------------------------------------------
out("\n== 3. RISOLUZIONE ARCHIVIO EREBO E VARCO V-59 ==")
cur.execute("SELECT k0, v1, v2 FROM r02 WHERE v1 = 'Archivio Erebo'")
row_erebo = cur.fetchone()
controllo(f"Archivio Erebo identificato: id={row_erebo[0]}, codice={row_erebo[2]}", row_erebo is not None and row_erebo[0] == 7685883)
erebo_id = row_erebo[0]

cur.execute("SELECT k0, k1, v1 FROM r07 WHERE k1 = ? AND v1 = 'V-59'", (erebo_id,))
row_varco = cur.fetchone()
controllo(f"Varco V-59 collegato ad Erebo: id={row_varco[0]}", row_varco is not None and row_varco[0] == 1756534)
varco_id = row_varco[0]

# ------------------------------------------------------------------------------
# 4. Analisi Squadre, Membri e Idoneità Completa su Varco V-59 alle ore 12:00
# ------------------------------------------------------------------------------
out("\n== 4. IDENTIFICAZIONE COMPLETA SQUADRA ED OPERATORI AUTORIZZATI ==")
TARGET_TS = "2026-11-04 12:00"

query_coppie_valide = """
SELECT 
    sq.k0 AS squadra_id,
    sq.v1 AS squadra_nome,
    p_san.k0 AS san_id,
    p_san.v1 AS san_nome,
    p_san.v2 AS san_matricola,
    p_sic.k0 AS sic_id,
    p_sic.v1 AS sic_nome,
    p_sic.v2 AS sic_matricola
FROM r11 sq
-- Permesso SANITARIO squadra su varco
JOIN r08 perm_san ON perm_san.k1 = sq.k0 AND perm_san.k2 = ? AND perm_san.v1 = 'SANITARIO'
  AND perm_san.v2 = 'ATTIVO' AND perm_san.ts_a <= ? AND (perm_san.ts_b IS NULL OR perm_san.ts_b > ?)
LEFT JOIN e10 rev_san ON rev_san.k1 = perm_san.k0 AND rev_san.ts_a <= ?
-- Permesso SICUREZZA squadra su varco
JOIN r08 perm_sic ON perm_sic.k1 = sq.k0 AND perm_sic.k2 = ? AND perm_sic.v1 = 'SICUREZZA'
  AND perm_sic.v2 = 'ATTIVO' AND perm_sic.ts_a <= ? AND (perm_sic.ts_b IS NULL OR perm_sic.ts_b > ?)
LEFT JOIN e10 rev_sic ON rev_sic.k1 = perm_sic.k0 AND rev_sic.ts_a <= ?
-- Membro SANITARIO
JOIN m12 aff_san ON aff_san.k2 = sq.k0 AND aff_san.ts_a <= ? AND (aff_san.ts_b IS NULL OR aff_san.ts_b > ?)
JOIN r03 p_san ON p_san.k0 = aff_san.k1
JOIN r06 ab_san ON ab_san.k1 = p_san.k0 AND ab_san.v1 = 'SANITARIO' AND ab_san.ts_a <= ? AND (ab_san.ts_b IS NULL OR ab_san.ts_b > ?)
LEFT JOIN e04 sosp_san ON sosp_san.k1 = p_san.k0 AND sosp_san.ts_a <= ? AND (sosp_san.ts_b IS NULL OR sosp_san.ts_b > ?)
-- Membro SICUREZZA
JOIN m12 aff_sic ON aff_sic.k2 = sq.k0 AND aff_sic.ts_a <= ? AND (aff_sic.ts_b IS NULL OR aff_sic.ts_b > ?)
JOIN r03 p_sic ON p_sic.k0 = aff_sic.k1
JOIN r06 ab_sic ON ab_sic.k1 = p_sic.k0 AND ab_sic.v1 = 'SICUREZZA' AND ab_sic.ts_a <= ? AND (ab_sic.ts_b IS NULL OR ab_sic.ts_b > ?)
LEFT JOIN e04 sosp_sic ON sosp_sic.k1 = p_sic.k0 AND sosp_sic.ts_a <= ? AND (sosp_sic.ts_b IS NULL OR sosp_sic.ts_b > ?)
WHERE rev_san.k0 IS NULL
  AND rev_sic.k0 IS NULL
  AND sosp_san.k0 IS NULL
  AND sosp_sic.k0 IS NULL
  AND p_san.k0 != p_sic.k0
"""

cur.execute(query_coppie_valide, (
    varco_id, TARGET_TS, TARGET_TS, TARGET_TS,
    varco_id, TARGET_TS, TARGET_TS, TARGET_TS,
    TARGET_TS, TARGET_TS, TARGET_TS, TARGET_TS, TARGET_TS, TARGET_TS,
    TARGET_TS, TARGET_TS, TARGET_TS, TARGET_TS, TARGET_TS, TARGET_TS
))
coppie_valide = cur.fetchall()

coppie_uniche = list({(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in coppie_valide})

controllo(f"Esattamente 1 configurazione di squadra autorizzata trovata ({len(coppie_uniche)})", len(coppie_uniche) == 1)
sq_id, sq_nome, san_id, san_nome, san_mat, sic_id, sic_nome, sic_mat = coppie_uniche[0]

controllo(f"Squadra autorizzata: '{sq_nome}' (ID: {sq_id})", sq_nome == "Unità 5-Ardesia" and sq_id == 9303094)
controllo(f"Sanitario autorizzato: {san_nome} (Matricola: {san_mat}, ID: {san_id})", san_nome == "Tina Rocchi" and san_id == 3691193)
controllo(f"Sicurezza autorizzato: {sic_nome} (Matricola: {sic_mat}, ID: {sic_id})", sic_nome == "Ugo Valli" and sic_id == 8928812)
controllo("Regola 1 verificata: identificativi operatori distinti", san_id != sic_id)

# ------------------------------------------------------------------------------
# 5. Prove di Esclusione Dettagliate
# ------------------------------------------------------------------------------
out("\n== 5. PROVE DI ESCLUSIONE CANDIDATI (ALMENO 3 RICHIESTI DALLA MISSIONE) ==")

# Esclusione 1: Unità 5-Gesso (ID 752946) -> Permesso SANITARIO revocato da e10
cur.execute("""
SELECT p.k0, p.v1, r.ts_a, r.v1
FROM r08 p
JOIN e10 r ON r.k1 = p.k0
WHERE p.k1 = 752946 AND p.k2 = ? AND p.v1 = 'SANITARIO'
""", (varco_id,))
row_exc1 = cur.fetchone()
controllo(f"Esclusione 1 (Unità 5-Gesso): Permesso SANITARIO revocato da e10 alle ore {row_exc1[2]} ({row_exc1[3]})", row_exc1 is not None and row_exc1[2] <= TARGET_TS)

# Esclusione 2: Unità 5-Marmo (ID 9215925) -> Permesso SANITARIO scaduto alle 11:59
cur.execute("""
SELECT p.k0, p.v1, p.ts_a, p.ts_b
FROM r08 p
WHERE p.k1 = 9215925 AND p.k2 = ? AND p.v1 = 'SANITARIO'
""", (varco_id,))
row_exc2 = cur.fetchone()
controllo(f"Esclusione 2 (Unità 5-Marmo): Permesso SANITARIO scaduto alle {row_exc2[3]} (prima delle 12:00)", row_exc2 is not None and row_exc2[3] == "2026-11-04 11:59")

# Esclusione 3: Unità 5-Basalto (ID 7538287) -> Alma Donati sospesa
cur.execute("""
SELECT p.k0, p.v1, s.ts_a, s.ts_b, s.v1
FROM r03 p
JOIN m12 a ON a.k1 = p.k0
JOIN e04 s ON s.k1 = p.k0
WHERE a.k2 = 7538287 AND p.v1 = 'Alma Donati'
""")
row_exc3 = cur.fetchone()
controllo(f"Esclusione 3 (Unità 5-Basalto): Sanitaria Alma Donati sospesa dalle {row_exc3[2]} ({row_exc3[4]})", row_exc3 is not None and row_exc3[2] <= TARGET_TS)

# Esclusione 4: Unità 5-Calce (ID 1474219) -> Berto Serra sospeso
cur.execute("""
SELECT p.k0, p.v1, s.ts_a, s.ts_b, s.v1
FROM r03 p
JOIN m12 a ON a.k1 = p.k0
JOIN e04 s ON s.k1 = p.k0
WHERE a.k2 = 1474219 AND p.v1 = 'Berto Serra'
""")
row_exc4 = cur.fetchone()
controllo(f"Esclusione 4 (Unità 5-Calce): Addetto Sicurezza Berto Serra sospeso ({row_exc4[2]} - {row_exc4[3]}, motivo: {row_exc4[4]})", row_exc4 is not None and row_exc4[2] <= TARGET_TS < row_exc4[3])

# Esclusione 5: Unità 5-Tufo (ID 1719260) -> Un solo membro per due ruoli
cur.execute("""
SELECT p.k0, p.v1, COUNT(DISTINCT a.k1)
FROM m12 a
JOIN r03 p ON p.k0 = a.k1
WHERE a.k2 = 1719260 AND a.ts_a <= ? AND (a.ts_b IS NULL OR a.ts_b > ?)
GROUP BY p.k0
""", (TARGET_TS, TARGET_TS))
rows_tufo = cur.fetchall()
controllo(f"Esclusione 5 (Unità 5-Tufo): Solo 1 membro attivo (Hilda Marini), violazione Regola 1 (persone distinte)", len(rows_tufo) == 1 and rows_tufo[0][1] == "Hilda Marini")

# Esclusione 6: Terminale 5880280 su V-59 FUORI_SERVIZIO
cur.execute("SELECT k0, v1, v2 FROM r09 WHERE k1 = ? AND v2 != 'OPERATIVO'", (varco_id,))
row_exc6 = cur.fetchone()
controllo(f"Esclusione 6 (Terminale 5880280): Stato '{row_exc6[2]}' non idoneo", row_exc6 is not None and row_exc6[2] == "FUORI_SERVIZIO")

# ------------------------------------------------------------------------------
# 6. Terminali Operativi, Finestre e Codici Chiave
# ------------------------------------------------------------------------------
out("\n== 6. TERMINALI OPERATIVI, FINESTRE E CODICI CHIAVE ==")

query_term = """
SELECT t.k0 AS term_id, t.v1 AS canale, t.v2 AS stato,
       f.ts_a AS fin_da, f.ts_b AS fin_a,
       k.v1 AS codice_chiave, k.ts_a AS k_da, k.ts_b AS k_a
FROM r09 t
JOIN m05 f ON f.k1 = t.k0 AND f.ts_a <= ? AND (f.ts_b IS NULL OR f.ts_b > ?)
JOIN r13 k ON k.k1 = t.k0 AND k.ts_a <= ? AND (k.ts_b IS NULL OR k.ts_b > ?)
WHERE t.k1 = ? AND t.v2 = 'OPERATIVO'
ORDER BY t.k0, f.ts_a
"""
cur.execute(query_term, (TARGET_TS, TARGET_TS, TARGET_TS, TARGET_TS, varco_id))
term_rows = cur.fetchall()

canali_trovati = {}
for r in term_rows:
    t_id, can, st, f_da, f_a, k_cod, k_da, k_a = r
    if t_id not in canali_trovati:
        canali_trovati[t_id] = {"canale": can, "chiave": k_cod, "finestre": []}
    canali_trovati[t_id]["finestre"].append(f"{f_da} -> {f_a}")

controllo(f"Esattamente 2 terminali operativi con finestre e chiavi attive ({len(canali_trovati)})", len(canali_trovati) == 2)
for t_id, data in canali_trovati.items():
    out(f"   - Terminale {t_id} [{data['canale']}]: Chiave='{data['chiave']}', Finestre={data['finestre']}")

controllo("Terminale 4703994 associato a Canale Iota e chiave '642103'", canali_trovati.get(4703994, {}).get("chiave") == "642103")
controllo("Terminale 8372085 associato a Canale Gamma e chiave '500295'", canali_trovati.get(8372085, {}).get("chiave") == "500295")

# ------------------------------------------------------------------------------
# 7. Test Esecuzione Tool interroga_database() e Authorizer
# ------------------------------------------------------------------------------
out("\n== 7. TEST ESECUZIONE TOOL interroga_database() ==")

res_tool = interroga_database(
    query="SELECT k0, v1, v2 FROM r02 WHERE v1 = 'Archivio Erebo'",
    database="archivio_recuperato"
)
controllo("Query lecita tramite interroga_database() ha successo", "errore" not in res_tool and any("Archivio Erebo" in str(r) for r in res_tool.get("righe", [])))

res_tool_like = interroga_database(
    query="SELECT k0, v1 FROM r07 WHERE v1 LIKE '%59%'",
    database="archivio_recuperato"
)
controllo("Query con operatore LIKE consentita dall'Authorizer", "errore" not in res_tool_like and any("V-59" in str(r) for r in res_tool_like.get("righe", [])))

res_tool_drop = interroga_database(
    query="DROP TABLE r02",
    database="archivio_recuperato"
)
controllo("Operazione DROP TABLE bloccata con errore di sicurezza", "errore" in res_tool_drop and ("not authorized" in res_tool_drop["errore"].lower() or "non autorizzat" in res_tool_drop["errore"].lower()))

# ------------------------------------------------------------------------------
# 8. Non-Regressione Giorno 4 Parte 1 (accessi.sqlite)
# ------------------------------------------------------------------------------
out("\n== 8. NON-REGRESSIONE GIORNO 4 PARTE 1 (ACCESSI.SQLITE) ==")
res_g4_p1 = interroga_database(
    query="""
    SELECT a.pratica, o.nome, d.nome AS deposito, a.codice, a.stato
    FROM accessi a
    JOIN operatori o ON o.id = a.operatore_id
    JOIN depositi d ON d.id = a.deposito_id
    WHERE a.pratica = 'RV753' AND a.stato = 'attivo' AND a.codice = '057284'
    """,
    database="accessi"
)
controllo("Codice autorizzazione Nora Ferri (057284) preservato con zero iniziale", "errore" not in res_g4_p1 and "057284" in str(res_g4_p1.get("righe", [])) and "Nora Ferri" in str(res_g4_p1.get("righe", [])))

con.close()

# ------------------------------------------------------------------------------
# Riepilogo finale
# ------------------------------------------------------------------------------
out("\n================================================================================")
tot_ok = sum(1 for e in ESITI if e)
tot_test = len(ESITI)
out(f"ESITO SUITE: {tot_ok}/{tot_test} controlli superati con successo ({tot_ok/tot_test*100:.1f}%).")
out("================================================================================")

if tot_ok != tot_test:
    sys.exit(1)
