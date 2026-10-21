"""
Backend/cli.py — Interfaccia interattiva a riga di comando (CLI) per l'Investigatore AI.

Responsabilità:
- Gestione del ciclo di interazione da terminale (input/output).
- Instradamento automatico tra motore Locale (richieste semplici) e Cloud (richieste complesse).
- Supporto a comandi speciali (/tools, /fonti, /stats, /nodo, /cerca, esci).
- Salvataggio automatico della sessione nel database SQLite.
"""

import sys
from typing import Any

try:
    from Backend.config import DOMANDA_ESEMPIO, COMANDO_USCITA, stato_chiavi_api
    from Backend.database import (
        salva_con_instradamento,
        cancella_cronologia,
        leggi_ultimi_messaggi,
    )
    from Backend.sources import carica_fonti, scegli_fonti_dettagliato
    from Backend.router import genera_risposta_ibrida
    from Backend.tools import (
        STRUMENTI_REGISTRATI,
        statistiche_missione,
        ottieni_dettaglio_nodo,
        cerca_fonti,
    )
except ImportError:
    from config import DOMANDA_ESEMPIO, COMANDO_USCITA, stato_chiavi_api
    from database import (
        salva_con_instradamento,
        cancella_cronologia,
        leggi_ultimi_messaggi,
    )
    from sources import carica_fonti, scegli_fonti_dettagliato
    from router import genera_risposta_ibrida
    from tools import (
        STRUMENTI_REGISTRATI,
        statistiche_missione,
        ottieni_dettaglio_nodo,
        cerca_fonti,
    )


def stampa_guida_comandi() -> None:
    """Mostra i comandi rapidi disponibili nella CLI."""
    print("\n--- Comandi rapidi CLI ---")
    print("  /tools          : Elenca tutti gli strumenti investigativi dell'AI")
    print("  /fonti          : Mostra i file del dossier attualmente caricati")
    print("  /stats          : Statistiche operative della missione e del database")
    print("  /memoria        : Visualizza gli ultimi 10 messaggi nella memoria del database SQLite")
    print("  /nodo <id>      : Intelligence dettagliata su un nodo (es. /nodo ferri)")
    print("  /cerca <testo>  : Cerca nei documenti senza interrogare il modello")
    print("  /rag <domanda>  : Recupera i pezzi e i file dall'archivio tramite RAG")
    print("  /clear-history  : Rimuove tutta la cronologia salvata nel database SQLite")
    print(f"  {COMANDO_USCITA}            : Esci dal programma\n")


def avvia_cli() -> int:
    """Avvia la sessione interattiva da terminale con routing ibrido."""
    fonti = carica_fonti()
    if not fonti:
        print("Impossibile avviare la chat: Nessun file .txt trovato in dati/.")
        return 1

    print("================================================================================")
    print("=== Investigatore AI — Protocollo Lazzaro (Locale / Cloud / Tools)           ===")
    print("================================================================================")
    ha_chiavi, prov_str = stato_chiavi_api()
    print(f"Stato Provider Cloud : {'Attivo (' + prov_str + ')' if ha_chiavi else 'Non configurato (solo Locale)'}")
    print(f"Scrivi una domanda alla volta. Digita '{COMANDO_USCITA}' per terminare o '/help' per i comandi.")
    print(f"Esempio rapido: {DOMANDA_ESEMPIO}")

    while True:
        try:
            domanda = input("\nDomanda: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nProgramma terminato.")
            return 0

        if not domanda:
            print("La domanda è vuota: scrivi una domanda oppure digita 'esci'.")
            continue

        cmd_lower = domanda.lower()

        if cmd_lower in {COMANDO_USCITA, "exit", "quit"}:
            print("Programma terminato.")
            return 0

        if cmd_lower in {"/help", "help", "/aiuto"}:
            stampa_guida_comandi()
            continue

        if cmd_lower == "/tools":
            print("\nStrumenti (Tools) AI disponibili:")
            for nome, fn in STRUMENTI_REGISTRATI.items():
                doc = (fn.__doc__ or "").strip().splitlines()[0]
                print(f"  • {nome}: {doc}")
            continue

        if cmd_lower == "/fonti":
            print(f"\nFonti caricate ({len(fonti)} file):")
            for nome, _ in fonti:
                print(f"  - {nome}")
            continue

        if cmd_lower == "/stats":
            stats = statistiche_missione()
            print("\nStatistiche Operative:")
            for k, v in stats.items():
                print(f"  {k}: {v}")
            continue

        if cmd_lower in {"/memoria", "/memory"}:
            ultimi = leggi_ultimi_messaggi(10)
            print(f"\nMemoria dell'agente (ultimi {len(ultimi)} messaggi nel database SQLite):")
            if not ultimi:
                print("  (Nessun messaggio salvato nel database)")
            else:
                for idx, r in enumerate(ultimi, 1):
                    d_breve = (r['domanda'][:80] + '...') if len(r['domanda']) > 80 else r['domanda']
                    r_breve = (r['risposta'][:80] + '...') if len(r['risposta']) > 80 else r['risposta']
                    print(f"  {idx}. [ID {r['id']}] {r.get('created_at', '')}")
                    print(f"     Utente : {d_breve}")
                    print(f"     Armando: {r_breve}")
            continue

        if cmd_lower in {"/clear-history", "/pulisci-cronologia", "/elimina-cronologia", "/reset-cronologia"}:
            eliminati = cancella_cronologia()
            print(f"\nCronologia rimossa con successo ({eliminati} record eliminati dal database SQLite).")
            continue

        if cmd_lower.startswith("/nodo"):
            parti = domanda.split(maxsplit=1)
            nodo_id = parti[1].strip() if len(parti) > 1 else ""
            if not nodo_id:
                print("Uso: /nodo <id_o_codice> (es. /nodo laz01, /nodo ferri, /nodo echo)")
            else:
                info = ottieni_dettaglio_nodo(nodo_id)
                if info.get("ok"):
                    n = info["nodo"]
                    print(f"\n[{n['code']}] {n['name']} ({n['place']}, {n['region']})")
                    print(f"  Tipo: {n['type'].upper()} | Minaccia: {n['threat']}/5 | Stato: {n['status']}")
                    print(f"  Superstiti: {n['survivors']} | Ultimo contatto: {n['contact']} | Fonte: {n['source']}")
                    print(f"  Dettagli: {n['desc']}")
                else:
                    print(info.get("error"))
            continue

        if cmd_lower.startswith("/cerca"):
            parti = domanda.split(maxsplit=1)
            query = parti[1].strip() if len(parti) > 1 else ""
            if not query:
                print("Uso: /cerca <testo>")
            else:
                esito = cerca_fonti(query)
                print(f"\nRisultati ricerca per '{query}' ({esito['trovati']} trovati):")
                for r in esito["risultati"]:
                    print(f"  [{r['file']}] {r['titolo']}: {r['estratto']}")
            continue

        if cmd_lower.startswith("/rag"):
            parti = domanda.split(maxsplit=1)
            query = parti[1].strip() if len(parti) > 1 else ""
            if not query:
                print("Uso: /rag <domanda>")
            else:
                esito_rag = scegli_fonti_dettagliato(query)
                print(
                    f"\nRecupero RAG su {esito_rag['totale_archivio']} file "
                    f"({esito_rag['totale_blocchi_indicizzati']} blocchi indicizzati):"
                )
                print(f"File recuperati ({len(esito_rag['file_recuperati'])}): {esito_rag['file_recuperati']}")
                for d_f in esito_rag["dettagli_file"]:
                    print(f"  - [{d_f['id']}] {d_f['file']} ({d_f['formato'].upper()} | {d_f['fase']}) -> {d_f['titolo']}: {d_f['estratto']}")
            continue

        # Invia la richiesta al router ibrido
        try:
            esito = genera_risposta_ibrida(domanda, fonti)
            etichetta = (
                f"[LOCALE • {esito['modello_usato']}]"
                if esito["motore"] == "locale"
                else f"[CLOUD • {esito['modello_usato']}]"
            )
            print(
                f"\n{etichetta} ({esito['complessita']} — {esito['motivo_routing']}, "
                f"memoria: {esito.get('memoria_usata', 0)} msg, {esito['durata_ms']} ms)"
            )
            if esito.get("file_recuperati_rag"):
                print(f"File recuperati dal programma (RAG): {', '.join(esito['file_recuperati_rag'])}")
            if esito.get("fonti_citate"):
                print(f"Fonti citate nella risposta: {', '.join(esito['fonti_citate'])}")
            print(f"Risposta:\n{esito['risposta']}")
            salva_con_instradamento(domanda, [nome for nome, _ in fonti], esito)
        except Exception as exc:
            print(f"\nErrore durante l'elaborazione: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(avvia_cli())

