#!/usr/bin/env python3
"""
Backend/verifica_dati_4.py — Suite di test e verifica dinamica per la cartella dati_4 (Giorno 5).

Verifica:
1. Rilevamento dinamico della cartella dati_4 tramite risolvi_cartelle_dati_disponibili().
2. Caricamento fonti: G5-01.txt, G5-02.txt, G5-03.txt presenti in carica_fonti().
3. Metadati e classificazione di fase (Giorno 5) senza hardcoding.
4. Indicizzazione RAG e recupero contestualizzato.
5. Estrazione entità e catena di collegamenti (Forte Cenere, LUME, Nora Ferri, ECO, Torre Alta).
6. Scheda intelligence del nodo Presidio Torre Alta (torrealta).
7. Routing e risposta corretta con citazione puntuale [G5-xx].
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.config import risolvi_cartelle_dati_disponibili
from Backend.sources import carica_fonti, estrai_metadati_fonte, costruisci_indice_rag
from Backend.collegamenti import estrai_entita, analizza_collegamenti
from Backend.tools import recupera_rag, cerca_fonti, leggi_fonte, ottieni_dettaglio_nodo, statistiche_missione
from Backend.router import genera_risposta_ibrida


def esegui_verifiche() -> bool:
    print("=" * 80)
    print("AVVIO SUITE DI VERIFICA — CARTELLA DATI_4 (GIORNO 5 - EPILOGO)")
    print("=" * 80)

    errori = 0

    # 1. Rilevamento dinamico cartelle dati
    print("\n[TEST 1] Rilevamento dinamico cartelle dati (no hardcoding)...")
    cartelle = risolvi_cartelle_dati_disponibili()
    nomi_cartelle = [c.name for c in cartelle]
    print(f"  Cartelle rilevate: {nomi_cartelle}")
    if "dati_4" not in nomi_cartelle:
        print("  [FALLITO] La cartella dati_4 non è stata rilevata dinamicamente.")
        errori += 1
    else:
        print("  [OK] Cartella dati_4 rilevata correttamente.")

    # 2. Caricamento fonti primarie
    print("\n[TEST 2] Caricamento fonti primarie...")
    fonti = carica_fonti()
    mappa_fonti = dict(fonti)
    attesi = ["G5-01.txt", "G5-02.txt", "G5-03.txt"]
    for f in attesi:
        if f not in mappa_fonti:
            print(f"  [FALLITO] File {f} non presente nelle fonti caricate.")
            errori += 1
        else:
            print(f"  [OK] File {f} caricato ({len(mappa_fonti[f])} caratteri)")

    # 3. Estrazione metadati e classificazione di fase
    print("\n[TEST 3] Estrazione metadati dinamici dei file G5...")
    for f in attesi:
        testo = mappa_fonti.get(f, "")
        meta = estrai_metadati_fonte(f, testo)
        if meta.get("fase") != "Giorno 5":
            print(f"  [FALLITO] {f}: fase '{meta.get('fase')}' diversa da 'Giorno 5'")
            errori += 1
        elif not meta.get("id") or not meta.get("titolo"):
            print(f"  [FALLITO] {f}: metadati incompleti: {meta}")
            errori += 1
        else:
            print(f"  [OK] {f} -> ID: {meta['id']}, Titolo: '{meta['titolo']}', Fase: {meta['fase']}")

    # 4. Statistiche missione
    print("\n[TEST 4] Verifica statistiche globali della missione...")
    stats = statistiche_missione()
    file_dossier = stats.get("file_dossier", [])
    if not all(f in file_dossier for f in attesi):
        print(f"  [FALLITO] Documenti G5 non presenti nelle statistiche della missione: {file_dossier}")
        errori += 1
    else:
        print(f"  [OK] Statistiche aggiornate: {stats.get('fonti_dossier')} fonti totali nel dossier")

    # 5. Estrazione entità e cross-linking
    print("\n[TEST 5] Estrazione entità e cross-linking con il resto del corpus...")
    e3 = estrai_entita(mappa_fonti.get("G5-03.txt", ""))
    nomi3 = e3.get("nomi", set())
    codici3 = e3.get("codici", set())
    print(f"  Entità G5-03: codici={codici3}, nomi={nomi3}")
    if "lume" not in nomi3 or "forte cenere" not in nomi3 or "torre alta" not in nomi3:
        print("  [FALLITO] Entità chiave mancanti in G5-03.")
        errori += 1
    else:
        print("  [OK] Entità chiave (LUME, Forte Cenere, Torre Alta, ECO) estratte con successo.")

    link_res = analizza_collegamenti("Come si collegano LUME e Torre Alta?", fonti)
    if not link_res.get("ok"):
        print("  [FALLITO] Nessun collegamento trovato tra LUME e Torre Alta.")
        errori += 1
    else:
        print(f"  [OK] Catena di collegamento generata: {link_res.get('testo', '')[:120]}...")

    # 6. Scheda intelligence nodo Torre Alta
    print("\n[TEST 6] Verifica nodo mappa tattica Presidio Torre Alta...")
    nodo_res = ottieni_dettaglio_nodo("torrealta")
    if not nodo_res.get("ok"):
        print(f"  [FALLITO] Nodo torrealta non trovato: {nodo_res}")
        errori += 1
    else:
        nodo = nodo_res.get("nodo", {})
        print(f"  [OK] Nodo trovato: {nodo.get('code')} - {nodo.get('name')} ({nodo.get('place')})")

    # 7. Risoluzione query integrata con il router
    print("\n[TEST 7] Generazione risposta integrata con router e RAG...")
    q = "Qual è la differenza tra l'ordine in G5-01 e la direttiva di Nora Ferri in G5-03?"
    resp_ibrida = genera_risposta_ibrida(q, fonti)
    risposta_testo = resp_ibrida.get("risposta", "")
    fonti_citate = resp_ibrida.get("fonti_citate", [])
    print(f"  Motore: {resp_ibrida.get('motore')} ({resp_ibrida.get('modello_usato')})")
    print(f"  Fonti citate: {fonti_citate}")
    print(f"  Risposta sintetica:\n  {risposta_testo[:220]}...")

    if not any("G5" in str(fc) for fc in fonti_citate) and "G5" not in risposta_testo:
        print("  [FALLITO] La risposta non cita i documenti G5.")
        errori += 1
    else:
        print("  [OK] Risposta generata con citazioni corrette delle fonti G5.")

    print("\n" + "=" * 80)
    if errori == 0:
        print("TUTTE LE VERIFICHE SU DATI_4 SONO STATE SUPERATE CON SUCCESSO! (0 ERRORI)")
        print("=" * 80)
        return True
    else:
        print(f"RILEVATI {errori} ERRORI NELLE VERIFICHE.")
        print("=" * 80)
        return False


if __name__ == "__main__":
    successo = esegui_verifiche()
    sys.exit(0 if successo else 1)
