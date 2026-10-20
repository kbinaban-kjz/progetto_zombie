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
    from Backend.config import DOMANDA_ESEMPIO, COMANDO_USCITA
    from Backend.database import salva_con_instradamento
    from Backend.sources import carica_fonti
    from Backend.router import genera_risposta_ibrida
    from Backend.tools import (
        STRUMENTI_REGISTRATI,
        statistiche_missione,
        ottieni_dettaglio_nodo,
        cerca_fonti,
    )
except ImportError:
    from config import DOMANDA_ESEMPIO, COMANDO_USCITA
    from database import salva_con_instradamento
    from sources import carica_fonti
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
    print("  /nodo <id>      : Intelligence dettagliata su un nodo (es. /nodo ferri)")
    print("  /cerca <testo>  : Cerca nei documenti senza interrogare il modello")
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

        # Invia la richiesta al router ibrido
        try:
            esito = genera_risposta_ibrida(domanda, fonti)
            etichetta = (
                f"[LOCALE • {esito['modello_usato']}]"
                if esito["motore"] == "locale"
                else f"[CLOUD • {esito['modello_usato']}]"
            )
            print(f"\n{etichetta} ({esito['complessita']} — {esito['motivo_routing']}, {esito['durata_ms']} ms)")
            print(f"Risposta:\n{esito['risposta']}")
            salva_con_instradamento(domanda, [nome for nome, _ in fonti], esito)
        except Exception as exc:
            print(f"\nErrore durante l'elaborazione: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(avvia_cli())

