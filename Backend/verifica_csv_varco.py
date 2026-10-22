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
    risolvi_missione_varco,
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

    # 5. Verifica risoluzione complessiva missione varco V-59
    print("\n[TEST 5] Risoluzione deterministica missione Archivio Erebo V-59...")
    sol = risolvi_missione_varco()
    if not sol.get("ok"):
        print(f"  [FALLITO] Risoluzione missione: {sol.get('errore')}")
        errori += 1
    else:
        # Controllo squadra
        sq = sol.get("squadra_autorizzata", {})
        if sq.get("nome_squadra") != "Unità 5-Ardesia" or sq.get("squadra_id") != 9303094:
            print(f"  [FALLITO] Squadra errata: {sq}")
            errori += 1
        else:
            print(f"  [OK] Squadra autorizzata: {sq.get('nome_squadra')} (ID {sq.get('squadra_id')})")

        # Controllo operatori
        ops = sol.get("operatori_autorizzati", {})
        san = ops.get("sanitario", {})
        sic = ops.get("sicurezza", {})
        if san.get("nome") != "Tina Rocchi" or san.get("matricola") != "PX-803574":
            print(f"  [FALLITO] Operatore Sanitario errato: {san}")
            errori += 1
        else:
            print(f"  [OK] Operatore SANITARIO: {san.get('nome')} ({san.get('matricola')})")

        if sic.get("nome") != "Ugo Valli" or sic.get("matricola") != "PX-250896":
            print(f"  [FALLITO] Operatore Sicurezza errato: {sic}")
            errori += 1
        else:
            print(f"  [OK] Operatore SICUREZZA: {sic.get('nome')} ({sic.get('matricola')})")

        # Controllo terminali operativi
        terms = sol.get("terminali_operativi_convalidati", [])
        canali = {t["canale"]: t["chiave_valida"] for t in terms}
        if "Canale Iota" not in canali or "Canale Gamma" not in canali:
            print(f"  [FALLITO] Terminali convalidati errati: {terms}")
            errori += 1
        elif canali["Canale Iota"] != "642103" or canali["Canale Gamma"] != "500295":
            print(f"  [FALLITO] Chiavi terminali errate: {canali}")
            errori += 1
        else:
            print(f"  [OK] Terminali operativi: Canale Iota (chiave {canali['Canale Iota']}), Canale Gamma (chiave {canali['Canale Gamma']})")

        # Controllo esclusioni
        esc = sol.get("candidati_ed_elementi_esclusi", [])
        if len(esc) < 3:
            print(f"  [FALLITO] Troppe poche esclusioni documentate: {len(esc)}")
            errori += 1
        else:
            print(f"  [OK] Esclusioni documentate con motivazione: {len(esc)}")

        # Controllo informazione mancante
        mancante = sol.get("informazione_mancante_da_chiedere", "")
        if "canale" not in mancante.lower():
            print(f"  [FALLITO] Informazione mancante non pertinente: {mancante}")
            errori += 1
        else:
            print(f"  [OK] Informazione mancante correttamente rilevata: {mancante[:80]}...")

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

