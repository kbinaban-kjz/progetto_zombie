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
    from Backend.evidenze import risposta_imprevisti
    from Backend.tools import (
        STRUMENTI_REGISTRATI,
        statistiche_missione,
        ottieni_dettaglio_nodo,
        cerca_fonti,
        interroga_database,
        agente_sql,
        elenca_tabelle_csv,
        leggi_tabella_csv,
        cerca_in_csv,
        interroga_archivio_recuperato_sql,
        risolvi_missione_varco,
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
    from evidenze import risposta_imprevisti
    from tools import (
        STRUMENTI_REGISTRATI,
        statistiche_missione,
        ottieni_dettaglio_nodo,
        cerca_fonti,
        interroga_database,
        agente_sql,
        elenca_tabelle_csv,
        leggi_tabella_csv,
        cerca_in_csv,
        interroga_archivio_recuperato_sql,
        risolvi_missione_varco,
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
    print("  /catena <testo> : Analisi evidenze (copie vs misure dirette) e catena multi-documento")
    print("  /sql <domanda>  : Esegue l'agente SQL mostrando QUERY, RISULTATO e SPIEGAZIONE")
    print("  /csv [sottocmd] : Accesso tabelle CSV e archivio recuperato (/csv elenca, /csv leggi, /csv cerca, /csv sql, /csv varco)")
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
                    print(
                        f"  - [{d_f['id']}] {d_f['file']} ({d_f['formato'].upper()} | {d_f['fase']} | "
                        f"{d_f['provenienza']}) -> {d_f['titolo']}: {d_f['estratto']}"
                    )
                print("Brani recuperati (blocchi con punteggio):")
                for b in esito_rag["blocchi_recuperati"]:
                    brano = " ".join(b["blocco"].split())
                    print(f"  * {b['file']} [{b['id']}] score={b['score']}: {brano[:260]}")
                if esito_rag.get("copie_collassate"):
                    print(
                        f"Copie inoltrate non mostrate ({len(esito_rag['copie_collassate'])}): "
                        "ripetono la stessa origine, non sono conferme indipendenti."
                    )
            continue

        if cmd_lower.startswith(("/catena", "/evidenze")):
            parti = domanda.split(maxsplit=1)
            query = parti[1].strip() if len(parti) > 1 else ""
            if not query:
                print("Uso: /catena <domanda> (es. /catena Dove si trova il modulo consegnato dal corriere Nebbia?)")
            else:
                print()
                print(risposta_imprevisti(query) or "Domanda non pertinente al pacchetto imprevisti.")
            continue

        if cmd_lower.startswith("/sql"):
            parti = domanda.split(maxsplit=1)
            param = parti[1].strip() if len(parti) > 1 else ""
            if not param:
                print("Uso: /sql <domanda con gli indizi OPPURE query SQL diretta>")
                print("  Es. 1: /sql Qual è il codice di autorizzazione per Nora Ferri al deposito Forte Cenere, settore D6, pratica RV753?")
                print("  Es. 2: /sql SELECT a.codice, a.stato, a.valido_fino FROM accessi a WHERE a.pratica = 'RV753'")
            else:
                if param.strip().upper().startswith("SELECT"):
                    esito = interroga_database(param)
                    print("\nQUERY ESEGUITA:")
                    print(f"  {param}")
                    print("\nRISULTATO:")
                    import json
                    print(f"  {json.dumps(esito, ensure_ascii=False, indent=2)}")
                else:
                    print("\n" + agente_sql(param))
            continue

        if cmd_lower.startswith("/csv"):
            parti = domanda.split(maxsplit=2)
            subcmd = parti[1].lower() if len(parti) > 1 else "guida"
            resto = parti[2].strip() if len(parti) > 2 else ""

            if subcmd in ("elenca", "ls", "list"):
                esito = elenca_tabelle_csv()
                print("\n=== TABELLE CSV RECUPERATE (Terminale Danneggiato) ===")
                print(f"Cartella: {esito.get('cartella')}")
                print(f"{'TABELLA':<10} {'RIGHE':<8} {'NOME LOGICO':<25} {'DESCRIZIONE'}")
                print("-" * 80)
                for tab_k, tab_v in esito.get("tabelle", {}).items():
                    print(f"{tab_k:<10} {tab_v.get('num_righe', 0):<8} {tab_v.get('nome_logico', ''):<25} {tab_v.get('descrizione', '')}")
                print()
            elif subcmd in ("leggi", "read", "cat", "view"):
                if not resto:
                    print("Uso: /csv leggi <tabella> [limite] (es. /csv leggi r03 10)")
                else:
                    parti_leggi = resto.split()
                    tab_nome = parti_leggi[0]
                    lim = int(parti_leggi[1]) if len(parti_leggi) > 1 and parti_leggi[1].isdigit() else 20
                    esito = leggi_tabella_csv(tab_nome, limite=lim)
                    if not esito.get("ok"):
                        print(f"\nErrore: {esito.get('errore')}")
                    else:
                        print(f"\n=== Tabella CSV '{esito['tabella']}' ({esito['nome_logico']}) ===")
                        print(f"Descrizione: {esito['descrizione']}")
                        print(f"Campi decodificati: {esito.get('campi_decodificati')}")
                        print(f"Mostrate {len(esito['righe'])} righe su {esito['totale_righe']}:\n")
                        import json
                        for r in esito["righe"]:
                            print(" ", json.dumps(r, ensure_ascii=False))
                        print()
            elif subcmd in ("cerca", "search", "grep"):
                if not resto:
                    print("Uso: /csv cerca <termine> (es. /csv cerca 'Tina Rocchi' oppure /csv cerca 'V-59')")
                else:
                    esito = cerca_in_csv(resto)
                    print(f"\n=== Ricerca CSV per '{resto}' (Trovati: {esito.get('totale_riscontri')}) ===")
                    for h in esito.get("risultati", []):
                        print(f"  [{h['tabella']}.csv (riga {h['riga_num']}) - {h['nome_logico']}]: {h['dati']}")
                    print()
            elif subcmd == "sql":
                if not resto:
                    print("Uso: /csv sql <SELECT ...> (es. /csv sql SELECT r03.v1, r03.v2, r06.v1 FROM r03 JOIN r06 ON r03.k0 = r06.k1)")
                else:
                    esito = interroga_archivio_recuperato_sql(resto)
                    if not esito.get("ok"):
                        print(f"\nErrore SQL: {esito.get('errore')}")
                    else:
                        print("\nQUERY ESEGUITA:")
                        print(f"  {resto}")
                        print(f"\nRISULTATI ({esito.get('totale_righe')} righe):")
                        colonne = esito.get("colonne", [])
                        if colonne:
                            print(" | ".join(f"{c:<20}" for c in colonne))
                            print("-" * (22 * len(colonne)))
                            for row in esito.get("righe", []):
                                print(" | ".join(f"{str(v):<20}" for v in row))
                        print()
            elif subcmd in ("varco", "risolvi", "missione"):
                esito = risolvi_missione_varco()
                if not esito.get("ok"):
                    print(f"\nErrore: {esito.get('errore')}")
                else:
                    print("\n================================================================================")
                    print("RAPPORTINO MISSIONE — ARCHIVIO EREBO VARCO V-59 (04/11/2026 ORE 12:00)")
                    print("================================================================================")
                    dest = esito["destinazione"]
                    print(f"Destinazione: {dest['archivio_nome']} (ID {dest['archivio_id']}) -> Varco {dest['varco_codice']} (ID {dest['varco_id']})")
                    sq = esito["squadra_autorizzata"]
                    print(f"Squadra Autorizzata: {sq['nome_squadra']} (ID {sq['squadra_id']}) [Ruoli: {', '.join(sq['ruoli_confermati'])}]")
                    ops = esito["operatori_autorizzati"]
                    san = ops["sanitario"]
                    sic = ops["sicurezza"]
                    print(f"Operatore SANITARIO: {san['nome']} (Matricola: {san['matricola']}, ID: {san['id']})")
                    print(f"Operatore SICUREZZA: {sic['nome']} (Matricola: {sic['matricola']}, ID: {sic['id']})")
                    print("\nTerminali Operativi Convalidati:")
                    for t in esito["terminali_operativi_convalidati"]:
                        print(f"  - Terminale {t['terminale_id']} ({t['canale']}): Chiave {t['chiave_valida']} (Finestra: {t['finestra_aperta']})")
                    print("\nCandidati ed Elementi Esclusi:")
                    for esc in esito["candidati_ed_elementi_esclusi"]:
                        print(f"  - {esc['candidato']}: {esc['motivo']}")
                    print("\nInformazione Mancante da Chiedere:")
                    print(f"  {esito['informazione_mancante_da_chiedere']}\n")
            else:
                print("Sottocomandi disponibili per /csv:")
                print("  /csv elenca                 : Elenca tutte le 14 tabelle CSV decodificate")
                print("  /csv leggi <tabella> [lim]  : Legge i record di una tabella CSV (es. /csv leggi r03 10)")
                print("  /csv cerca <termine>        : Cerca un nome o codice su tutte le tabelle CSV")
                print("  /csv sql <query>            : Esegue query SQL SELECT su archivio_recuperato.sqlite")
                print("  /csv varco                  : Risoluzione e verifica vincoli per Archivio Erebo V-59")
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

