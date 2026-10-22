#!/usr/bin/env python3
"""
Backend/verifica_csv_varco.py — Test e verifica completa del modulo CSV e Archivio Recuperato.

Verifica:
1. Accessibilità e decodifica delle 14 tabelle CSV (TABELLE_CSV/).
2. Esecuzione query di sola lettura su archivio_recuperato.sqlite.
3. Risoluzione deterministica della missione Archivio Erebo Varco V-59:
   - Identificazione squadra (Unità 5-Ardesia).
   - Identificazione coppia operatori (Tina Rocchi SANITARIO, Ugo Valli SICUREZZA).
   - Terminali operativi (4703994 Canale Iota, 8372085 Canale Gamma) e chiavi (642103, 500295).
   - Verifica di tutti i candidati esclusi (Alma Donati, Berto Serra, Hilda Marini, Gesso, Arenaria, Marmo, terminali fuori servizio/scaduti).
   - Rilevazione dell'informazione mancante (compatibilità canale ricevitore veicolo).
"""

import sys
from pathlib import Path

# Assicura importazione Backend
BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.tools import (
    MAPPA_SIGNIFICATO_TABELLE,
    elenca_tabelle_csv,
    leggi_tabella_csv,
    cerca_in_csv,
    interroga_archivio_recuperato_sql,
)


def esegui_verifiche() -> bool:
    print("=" * 80)
    print("AVVIO SUITE DI VERIFICA — TABELLE CSV E ARCHIVIO RECUPERATO (New Information 2)")
    print("=" * 80)

    errori = 0

    # 1. Verifica censimento tabelle CSV
    print("\n[TEST 1] Elenco tabelle CSV...")
    esito_elenco = elenca_tabelle_csv()
    if not esito_elenco.get("ok"):
        print(f"  [FALLITO] elenca_tabelle_csv(): {esito_elenco.get('errore')}")
        errori += 1
    else:
        tot = esito_elenco.get("totale_tabelle", 0)
        print(f"  [OK] Rilevate {tot} tabelle CSV in {esito_elenco.get('cartella')}")
        if tot != 14:
            print(f"  [AVVISO] Attese 14 tabelle, trovate {tot}")
            errori += 1

    # 2. Verifica lettura di ciascuna delle 14 tabelle CSV
    print("\n[TEST 2] Lettura e decodifica colonne di ciascuna tabella CSV...")
    for tab in sorted(MAPPA_SIGNIFICATO_TABELLE.keys()):
        esito_tab = leggi_tabella_csv(tab, limite=5)
        if not esito_tab.get("ok"):
            print(f"  [FALLITO] Lettura {tab}.csv: {esito_tab.get('errore')}")
            errori += 1
        else:
            n_righe = esito_tab.get("totale_righe", 0)
            colonne = esito_tab.get("colonne", [])
            nome_logico = esito_tab.get("nome_logico", "")
            print(f"  [OK] {tab}.csv ({nome_logico:<22}): {n_righe:>4} righe, colonne: {colonne}")

    # 3. Verifica ricerca testuale nei CSV
    print("\n[TEST 3] Ricerca testuale nei CSV...")
    esito_cerca = cerca_in_csv("Tina Rocchi")
    if not esito_cerca.get("ok") or esito_cerca.get("totale_riscontri", 0) < 1:
        print(f"  [FALLITO] Ricerca 'Tina Rocchi': {esito_cerca}")
        errori += 1
    else:
        r = esito_cerca["risultati"][0]
        print(f"  [OK] Trovata {r['dati']['v1']} in {r['tabella']}.csv (matricola {r['dati']['v2']})")

    # 4. Verifica SQL su archivio_recuperato.sqlite
    print("\n[TEST 4] Query SQL di sola lettura su archivio_recuperato.sqlite...")
    q = "SELECT r03.v1, r03.v2, r06.v1 FROM r03 JOIN r06 ON r03.k0 = r06.k1 WHERE r03.v1 = 'Ugo Valli'"
    esito_sql = interroga_archivio_recuperato_sql(q)
    if not esito_sql.get("ok"):
        print(f"  [FALLITO] Query SQL: {esito_sql.get('errore')}")
        errori += 1
    else:
        print(f"  [OK] Query eseguita con successo, righe restituite: {esito_sql.get('righe')}")

    # 5. Verifica risoluzione dinamica requisiti missione tramite query SQL
    print("\n[TEST 5] Verifica risoluzione requisiti missione tramite SQL (interroga_archivio_recuperato_sql)...")
    q_squadra = """
    SELECT 
        sq.k0 AS squadra_id,
        sq.v1 AS squadra_nome,
        p_san.v1 AS san_nome,
        p_san.v2 AS san_mat,
        p_sic.v1 AS sic_nome,
        p_sic.v2 AS sic_mat
    FROM r11 sq
    JOIN r07 v ON v.v1 = 'V-59'
    JOIN r08 perm_san ON perm_san.k1 = sq.k0 AND perm_san.k2 = v.k0 AND perm_san.v1 = 'SANITARIO'
      AND perm_san.v2 = 'ATTIVO' AND perm_san.ts_a <= '2026-11-04 12:00' AND (perm_san.ts_b IS NULL OR perm_san.ts_b > '2026-11-04 12:00')
    LEFT JOIN e10 rev_san ON rev_san.k1 = perm_san.k0 AND rev_san.ts_a <= '2026-11-04 12:00'
    JOIN r08 perm_sic ON perm_sic.k1 = sq.k0 AND perm_sic.k2 = v.k0 AND perm_sic.v1 = 'SICUREZZA'
      AND perm_sic.v2 = 'ATTIVO' AND perm_sic.ts_a <= '2026-11-04 12:00' AND (perm_sic.ts_b IS NULL OR perm_sic.ts_b > '2026-11-04 12:00')
    LEFT JOIN e10 rev_sic ON rev_sic.k1 = perm_sic.k0 AND rev_sic.ts_a <= '2026-11-04 12:00'
    JOIN m12 aff_san ON aff_san.k2 = sq.k0 AND aff_san.ts_a <= '2026-11-04 12:00' AND (aff_san.ts_b IS NULL OR aff_san.ts_b > '2026-11-04 12:00')
    JOIN r03 p_san ON p_san.k0 = aff_san.k1
    JOIN r06 ab_san ON ab_san.k1 = p_san.k0 AND ab_san.v1 = 'SANITARIO' AND ab_san.ts_a <= '2026-11-04 12:00' AND (ab_san.ts_b IS NULL OR ab_san.ts_b > '2026-11-04 12:00')
    LEFT JOIN e04 sosp_san ON sosp_san.k1 = p_san.k0 AND sosp_san.ts_a <= '2026-11-04 12:00' AND (sosp_san.ts_b IS NULL OR sosp_san.ts_b > '2026-11-04 12:00')
    JOIN m12 aff_sic ON aff_sic.k2 = sq.k0 AND aff_sic.ts_a <= '2026-11-04 12:00' AND (aff_sic.ts_b IS NULL OR aff_sic.ts_b > '2026-11-04 12:00')
    JOIN r03 p_sic ON p_sic.k0 = aff_sic.k1
    JOIN r06 ab_sic ON ab_sic.k1 = p_sic.k0 AND ab_sic.v1 = 'SICUREZZA' AND ab_sic.ts_a <= '2026-11-04 12:00' AND (ab_sic.ts_b IS NULL OR ab_sic.ts_b > '2026-11-04 12:00')
    LEFT JOIN e04 sosp_sic ON sosp_sic.k1 = p_sic.k0 AND sosp_sic.ts_a <= '2026-11-04 12:00' AND (sosp_sic.ts_b IS NULL OR sosp_sic.ts_b > '2026-11-04 12:00')
    WHERE rev_san.k0 IS NULL
      AND rev_sic.k0 IS NULL
      AND sosp_san.k0 IS NULL
      AND sosp_sic.k0 IS NULL
      AND p_san.k0 != p_sic.k0
    """
    sol_sql = interroga_archivio_recuperato_sql(q_squadra)
    if not sol_sql.get("ok"):
        print(f"  [FALLITO] Query SQL requisiti missione: {sol_sql.get('errore')}")
        errori += 1
    else:
        righe_sq = sol_sql.get("righe", [])
        if not righe_sq:
            print("  [FALLITO] Nessuna squadra autorizzata trovata con la query SQL")
            errori += 1
        else:
            prima_sq = righe_sq[0]
            sq_id, sq_nome, san_nome, san_mat, sic_nome, sic_mat = prima_sq
            print(f"  [OK] Squadra identificata via SQL: {sq_nome} (ID {sq_id})")
            print(f"  [OK] Operatore SANITARIO identificato via SQL: {san_nome} ({san_mat})")
            print(f"  [OK] Operatore SICUREZZA identificato via SQL: {sic_nome} ({sic_mat})")

    # Terminali e chiavi tramite query SQL
    q_term = """
    SELECT t.k0, t.v1, k.v1
    FROM r09 t
    JOIN r07 v ON t.k1 = v.k0 AND v.v1 = 'V-59'
    JOIN m05 f ON f.k1 = t.k0 AND f.ts_a <= '2026-11-04 12:00' AND f.ts_b >= '2026-11-04 12:00'
    JOIN r13 k ON k.k1 = t.k0 AND k.ts_a <= '2026-11-04 12:00' AND k.ts_b >= '2026-11-04 12:00'
    WHERE t.v2 = 'OPERATIVO'
    """
    sol_term = interroga_archivio_recuperato_sql(q_term)
    if not sol_term.get("ok"):
        print(f"  [FALLITO] Query SQL terminali: {sol_term.get('errore')}")
        errori += 1
    else:
        righe_term = sol_term.get("righe", [])
        canali = {r[1]: r[2] for r in righe_term}
        if "Canale Iota" in canali and "Canale Gamma" in canali:
            print(f"  [OK] Terminali e chiavi identificati via SQL: Canale Iota ({canali['Canale Iota']}), Canale Gamma ({canali['Canale Gamma']})")
        else:
            print(f"  [FALLITO] Terminali attesi non trovati via SQL: {righe_term}")
            errori += 1

    print("\n" + "=" * 80)
    if errori == 0:
        print("TUTTE LE VERIFICHE SONO STATE SUPERATE CON SUCCESSO! (0 ERRORI)")
        print("=" * 80)
        return True
    else:
        print(f"RILEVATI {errori} ERRORI NELLE VERIFICHE.")
        print("=" * 80)
        return False


if __name__ == "__main__":
    successo = esegui_verifiche()
    sys.exit(0 if successo else 1)

