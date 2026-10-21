"""
Backend/Investigatore.py — Entry point principale per l'Investigatore AI (Protocollo Lazzaro).

Questo modulo connette e coordina l'architettura a responsabilità singola:
- config.py         -> Configurazione centralizzata, variabili d'ambiente (.env) e costanti.
- database.py       -> Persistenza SQLite (cronologia_chat, instradamento_chat).
- sources.py        -> Caricamento e formattazione dei documenti del dossier (dati/*.txt).
- tools.py          -> Strumenti invocabili dall'AI e dall'investigatore (fonti, mappa, nodi, stats).
- modello_locale.py -> Modello Qwen2.5-0.5B-Instruct locale con fallback deterministico.
- modello_gemini.py -> Client Google Gemini (google-genai / REST) con fallback automatico e tools.
- modello_openai.py -> Client per modelli cloud OpenAI e NVIDIA NIM con fallback automatico.
- router.py         -> Classificazione di complessità e instradamento ibrido Locale vs Cloud.
- server.py         -> Server HTTP e API REST per il Frontend.
- cli.py            -> Interfaccia a riga di comando interattiva da terminale.

Modalità di avvio:
    Avvio Server Web (Frontend + API REST):
        python Backend/Investigatore.py

    Avvio Chat Interattiva da Terminale (CLI):
        python Backend/Investigatore.py --cli
"""

import os
import sys

# Inizializza la configurazione e il path
try:
    from Backend.config import (
        BACKEND_DIR,
        ROOT_DIR,
        MODELLO_LOCALE,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        stato_chiavi_api,
    )
    from Backend.database import (
        inizializza_db,
        salva_messaggio,
        leggi_cronologia,
        leggi_ultimi_messaggi,
        formatta_memoria_chat,
        formatta_memoria_testo,
        salva_con_instradamento,
        leggi_cronologia_con_instradamento,
        cancella_cronologia,
        get_connection,
    )
    from Backend.sources import (
        carica_archivio_completo,
        carica_fonti,
        costruisci_indice_rag,
        formatta_fonte,
        read_document,
        risolvi_cartella_dati,
        scegli_fonti,
        scegli_fonti_dettagliato,
    )
    from Backend.tools import (
        STRUMENTI_REGISTRATI,
        TOOLS_OPENAI_SCHEMA,
        esegui_tool,
        cerca_fonti,
        recupera_rag,
        leggi_fonte,
        elenca_fonti,
        ottieni_nodi_mappa,
        ottieni_dettaglio_nodo,
        statistiche_missione,
    )
    from Backend.prompts import (
        PROMPT_SISTEMA,
        formatta_messaggio_cloud,
        formatta_messaggio_locale,
    )
    from Backend.modello_locale import (
        carica_modello_locale,
        genera_risposta_locale,
    )
    from Backend.router import (
        valuta_complessita,
        genera_risposta_ibrida,
        PAROLE_COMPLESSE,
    )
    from Backend.server import (
        InvestigatoreHTTPHandler,
        ModelloOpenAIHandler,
        avvia_server,
    )
    from Backend.cli import avvia_cli
    import Backend.modello_gemini as modello_gemini
    import Backend.modello_openai as modello_openai
except ImportError:
    from config import (
        BACKEND_DIR,
        ROOT_DIR,
        MODELLO_LOCALE,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        stato_chiavi_api,
    )
    from database import (
        inizializza_db,
        salva_messaggio,
        leggi_cronologia,
        leggi_ultimi_messaggi,
        formatta_memoria_chat,
        formatta_memoria_testo,
        salva_con_instradamento,
        leggi_cronologia_con_instradamento,
        cancella_cronologia,
        get_connection,
    )
    from sources import (
        carica_archivio_completo,
        carica_fonti,
        costruisci_indice_rag,
        formatta_fonte,
        read_document,
        risolvi_cartella_dati,
        scegli_fonti,
        scegli_fonti_dettagliato,
    )
    from tools import (
        STRUMENTI_REGISTRATI,
        TOOLS_OPENAI_SCHEMA,
        esegui_tool,
        cerca_fonti,
        recupera_rag,
        leggi_fonte,
        elenca_fonti,
        ottieni_nodi_mappa,
        ottieni_dettaglio_nodo,
        statistiche_missione,
    )
    from modello_locale import (
        carica_modello_locale,
        genera_risposta_locale,
    )
    from router import (
        valuta_complessita,
        genera_risposta_ibrida,
        PAROLE_COMPLESSE,
    )
    from server import (
        InvestigatoreHTTPHandler,
        ModelloOpenAIHandler,
        avvia_server,
    )
    from cli import avvia_cli
    import modello_gemini
    import modello_openai

# Inizializza il database SQLite all'importazione
inizializza_db()

# Alias retrocompatibili
formatta_fonte_locale = formatta_fonte
_ha_chiave_configurata = stato_chiavi_api


def main():
    """Punto di ingresso principale dell'applicazione."""
    if "--cli" in sys.argv:
        sys.exit(avvia_cli())

    porta = int(valore_env("PORT", "8000"))
    avvia_server(port=porta)


if __name__ == "__main__":
    main()
