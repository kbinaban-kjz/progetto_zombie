"""
Backend/modello_gemini.py — Chiamata ai modelli Google Gemini con supporto strumenti (Tools).

Responsabilità:
- Connessione e gestione del client Google GenAI SDK (google-genai).
- Supporto al fallback automatico sui modelli Gemini di riserva in caso di modello non disponibile (404) o quota saturata (429).
- Integrazione con gli strumenti operativi (Function Calling) definiti in tools.py.
- Fallback universale via REST (urllib) nel caso la libreria google-genai non sia installata.
- Interfaccia CLI autonoma per testare direttamente il modello da terminale.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from Backend.config import (
        MODELLO_GEMINI_DEFAULT,
        MODELLI_GEMINI_RISERVA,
        TIMEOUT_SECONDI,
        STATI_RIPROVABILI,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        get_gemini_api_key,
    )
    from Backend.sources import formatta_blocco_openai, carica_fonti
    from Backend.tools import (
        STRUMENTI_REGISTRATI,
        esegui_tool,
        recupera_rag,
        cerca_fonti,
        leggi_fonte,
        leggi_dossier_excel,
        collega_documenti,
        analizza_evidenze,
        elenca_fonti,
        verifica_sicurezza_fonti,
        ottieni_nodi_mappa,
        ottieni_dettaglio_nodo,
        cerca_cronologia,
        statistiche_missione,
        interroga_accessi_sql,
        elenca_tabelle_csv,
        leggi_tabella_csv,
        cerca_in_csv,
        interroga_archivio_recuperato_sql,
        cerca_personale,
        elenca_personaggi_e_operatori,
        elenca_squadre,
    )
    from Backend.prompts import costruisci_istruzioni_con_fonti, formatta_messaggio_cloud
except ImportError:
    from config import (
        MODELLO_GEMINI_DEFAULT,
        MODELLI_GEMINI_RISERVA,
        TIMEOUT_SECONDI,
        STATI_RIPROVABILI,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        get_gemini_api_key,
    )
    from sources import formatta_blocco_openai, carica_fonti
    from tools import (
        STRUMENTI_REGISTRATI,
        esegui_tool,
        recupera_rag,
        cerca_fonti,
        leggi_fonte,
        leggi_dossier_excel,
        collega_documenti,
        analizza_evidenze,
        elenca_fonti,
        verifica_sicurezza_fonti,
        ottieni_nodi_mappa,
        ottieni_dettaglio_nodo,
        cerca_cronologia,
        statistiche_missione,
        interroga_accessi_sql,
        elenca_tabelle_csv,
        leggi_tabella_csv,
        cerca_in_csv,
        interroga_archivio_recuperato_sql,
        cerca_personale,
        elenca_personaggi_e_operatori,
        elenca_squadre,
    )
    from prompts import costruisci_istruzioni_con_fonti, formatta_messaggio_cloud

# ==============================================================================
# GESTIONE ECCEZIONI GEMINI
# ==============================================================================
class GeminiError(Exception):
    """Classe base per tutti gli errori legati all'API di Google Gemini."""
    pass


class GeminiAuthError(GeminiError):
    """Sollevata quando la chiave API di Gemini è errata o non autorizzata (401/403)."""
    pass


class GeminiQuotaError(GeminiError):
    """Sollevata quando la quota o il rate-limit di Gemini sono esauriti (429)."""
    pass


class GeminiConnectionError(GeminiError):
    """Sollevata in caso di mancata connessione di rete verso i server di Google Gemini."""
    pass


# ==============================================================================
# IMPORTAZIONE RESILIENTE DI GOOGLE GENAI SDK
# ==============================================================================
try:
    from google import genai
    from google.genai import types, errors
    GOOGLE_GENAI_DISPONIBILE = True
except ImportError:
    GOOGLE_GENAI_DISPONIBILE = False
    genai = None  # type: ignore
    types = None  # type: ignore
    errors = None  # type: ignore

# Cache client e telemetria
_client_cache: dict[str, Any] = {}
_ultimo_modello_gemini_valido: str | None = None
ULTIMO_MODELLO_USATO: str | None = None

# Mappatura retrocompatibile per versioni ritirate, preview o alias dell'API Google Gemini
ALIAS_MODELLI: dict[str, str] = {
    "gemini-3.8-flash-lite": "gemini-flash-lite-latest",
    "3.8-flash-lite": "gemini-flash-lite-latest",
    "3.8 flash lite": "gemini-flash-lite-latest",
    "gemini-flash-lite": "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite": "gemini-flash-lite-latest",
    "gemini-3.8-flash": "gemini-flash-latest",
    "gemini-3.5-flash": "gemini-flash-latest",
    "gemini-1.5-flash": "gemini-flash-latest",
    "gemini-pro": "gemini-flash-latest",
    "gemini-1.5-pro": "gemini-2.5-pro",
    "gemini-3.1-pro-preview": "gemini-2.5-pro",
}


def ottieni_client(api_key: str) -> Any:
    """Restituisce un'istanza client google.genai.Client memorizzata nella cache con timeout configurato."""
    if not GOOGLE_GENAI_DISPONIBILE or genai is None:
        return None
    chiave_pulita = api_key.strip()
    client = _client_cache.get(chiave_pulita)
    if client is None:
        try:
            client = genai.Client(
                api_key=chiave_pulita,
                http_options={"timeout": int(TIMEOUT_SECONDI * 1000)},
            )
        except Exception:
            client = genai.Client(api_key=chiave_pulita)
        _client_cache[chiave_pulita] = client
    return client


def _genera_risposta_rest(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    api_key: str,
    modello: str,
    memoria: list[dict[str, Any]] | None = None,
    contesto_collegamenti: str = "",
) -> str:
    """
    Fallback REST nativo via urllib: esegue la chiamata a Gemini senza librerie esterne.
    Utilizza l'endpoint generateContent ufficiale di Google Generative Language API.
    """
    global ULTIMO_MODELLO_USATO
    contenuto_fonti = formatta_blocco_openai(fonti)
    istruzioni_sistema = costruisci_istruzioni_con_fonti(contenuto_fonti, contesto_collegamenti)

    # Assicura formato corretto del modello per la REST API
    id_modello = modello.split("/")[-1] if "/" in modello else modello
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{id_modello}:generateContent?key={api_key.strip()}"

    contents_rest: list[dict[str, Any]] = []
    if memoria:
        for m in memoria[-10:]:
            d = (m.get("domanda") or "").strip()
            r = (m.get("risposta") or "").strip()
            if d:
                contents_rest.append({"role": "user", "parts": [{"text": d}]})
            if r:
                contents_rest.append({"role": "model", "parts": [{"text": r}]})
    contents_rest.append({"role": "user", "parts": [{"text": domanda}]})

    payload = {
        "system_instruction": {
            "parts": [{"text": istruzioni_sistema}]
        },
        "contents": contents_rest,
        "generationConfig": {
            "temperature": 0.0
        }
    }

    dati = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=dati,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=int(TIMEOUT_SECONDI)) as resp:
            risultato = json.loads(resp.read().decode("utf-8"))
            ULTIMO_MODELLO_USATO = modello
            candidati = risultato.get("candidates", [])
            if not candidati:
                raise GeminiError("Gemini non ha restituito candidati validi.")
            parti = candidati[0].get("content", {}).get("parts", [])
            testi = [p.get("text", "") for p in parti if "text" in p]
            risposta = "".join(testi).strip()
            if not risposta:
                raise GeminiError("Gemini ha restituito un testo vuoto.")
            return risposta
    except urllib.error.HTTPError as err:
        codice = err.code
        corpo = err.read().decode("utf-8", errors="ignore")
        if codice in (401, 403) or "API_KEY_INVALID" in corpo:
            raise GeminiAuthError(f"Chiave Gemini non valida (HTTP {codice}): {corpo}") from err
        if codice == 429 or "RESOURCE_EXHAUSTED" in corpo:
            raise GeminiQuotaError(f"Quota o rate limit superato per Gemini (HTTP {codice})") from err
        raise GeminiError(f"Errore HTTP {codice} da Gemini: {corpo}") from err
    except urllib.error.URLError as err:
        raise GeminiConnectionError(f"Impossibile raggiungere l'API di Gemini: {err}") from err


def genera_risposta(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    *,
    api_key: str | None = None,
    modello: str | None = None,
    usa_tools: bool = False,
    memoria: list[dict[str, Any]] | None = None,
    contesto_collegamenti: str = "",
) -> str:
    """
    Invia la richiesta al modello Google Gemini.
    - Se usa_tools è True, abilita i tools definiti in tools.py.
    - Gestisce il fallback automatico tra i modelli Gemini configurati.
    - Utilizza google.genai se installato, altrimenti ripiega sulla REST API nativa.
    - Supporta la memoria conversazionale degli ultimi messaggi scambiati.
    """
    global _ultimo_modello_gemini_valido, ULTIMO_MODELLO_USATO

    domanda = domanda.strip()
    if not domanda:
        raise ValueError("La domanda non può essere vuota.")
    if not fonti:
        raise ValueError("Fornisci almeno una fonte.")

    chiave = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API") or get_gemini_api_key()
    if not chiave:
        raise ValueError(
            "Configura GEMINI_API_KEY (o GEMINI_API) nel file .env o nelle variabili d'ambiente. "
            "Puoi ottenere una chiave gratuita su https://aistudio.google.com/app/apikey"
        )

    # Risoluzione modello principale e lista di modelli da provare con fallback
    modello_env = os.environ.get("GEMINI_MODEL") or valore_env("GEMINI_MODEL")
    modello_richiesto = modello or modello_env or (_ultimo_modello_gemini_valido or MODELLO_GEMINI_DEFAULT)
    modello_principale = ALIAS_MODELLI.get(modello_richiesto, modello_richiesto)

    modelli: list[str] = [modello_principale]
    for m in MODELLI_GEMINI_RISERVA:
        m_risolto = ALIAS_MODELLI.get(m, m)
        if m_risolto not in modelli:
            modelli.append(m_risolto)

    contenuto_fonti = formatta_blocco_openai(fonti)
    istruzioni_sistema = costruisci_istruzioni_con_fonti(contenuto_fonti, contesto_collegamenti)

    # --------------------------------------------------------------------------
    # PERCORSO 1: google-genai SDK (se disponibile)
    # --------------------------------------------------------------------------
    if GOOGLE_GENAI_DISPONIBILE and genai is not None:
        client = ottieni_client(chiave)

        # Preparazione lista completa delle funzioni investigative (Tools):
        # Permette all'agente di interrogare l'archivio (RAG), cercare e leggere documenti,
        # collegare prove, verificare sicurezza, consultare la mappa e interrogare la cronologia.
        funzioni_tools: list[Any] = []
        if usa_tools:
            funzioni_tools = [
                cerca_fonti,
                cerca_personale,
                elenca_personaggi_e_operatori,
                elenca_squadre,
                cerca_in_csv,
                interroga_accessi_sql,
                interroga_archivio_recuperato_sql,
                leggi_tabella_csv,
                elenca_tabelle_csv,
                collega_documenti,
                analizza_evidenze,
                leggi_fonte,
                leggi_dossier_excel,
                elenca_fonti,
                ottieni_dettaglio_nodo,
                ottieni_nodi_mappa,
                cerca_cronologia,
                statistiche_missione,
                verifica_sicurezza_fonti,
                recupera_rag,
            ]

        # Costruzione cronologia messaggi per SDK google-genai (ultimi 10 scambi)
        gemini_history: list[Any] = []
        if memoria and types is not None:
            for m_item in memoria[-10:]:
                d = (m_item.get("domanda") or "").strip()
                r = (m_item.get("risposta") or "").strip()
                if d:
                    gemini_history.append(
                        types.Content(role="user", parts=[types.Part.from_text(text=d)])
                    )
                if r:
                    gemini_history.append(
                        types.Content(role="model", parts=[types.Part.from_text(text=r)])
                    )

        ultimo_errore: Exception | None = None

        for indice, modello_corrente in enumerate(modelli):
            try:
                config_kwargs: dict[str, Any] = {
                    "system_instruction": istruzioni_sistema,
                    "temperature": 0.0,
                }
                if funzioni_tools:
                    config_kwargs["tools"] = funzioni_tools

                config = types.GenerateContentConfig(**config_kwargs)

                # Se ci sono tools, usa Chat con Automatic Function Calling (raccomandato da Google)
                if funzioni_tools:
                    chat = client.chats.create(
                        model=modello_corrente, config=config, history=gemini_history
                    )
                    risultato = chat.send_message(domanda)
                else:
                    contents_sdk = list(gemini_history) + [
                        types.Content(
                            role="user", parts=[types.Part.from_text(text=domanda)]
                        )
                    ]
                    risultato = client.models.generate_content(
                        model=modello_corrente,
                        contents=contents_sdk,
                        config=config,
                    )

                # Estrazione del testo della risposta
                risposta_testo: str | None = None
                try:
                    risposta_testo = risultato.text
                except Exception:
                    risposta_testo = None

                # Se ci sono chiamate funzione manuali non risolte automaticamente
                if not risposta_testo and getattr(risultato, "function_calls", None):
                    chiamate = risultato.function_calls
                    parti_risposte = []
                    for call in chiamate:
                        nome_fn = call.name
                        argomenti = getattr(call, "args", {}) or {}
                        esito_tool = esegui_tool(nome_fn, argomenti)
                        parti_risposte.append(
                            types.Part.from_function_response(
                                name=nome_fn,
                                response={"result": esito_tool},
                            )
                        )

                    # Secondo turno con l'esito dei tool preservando la history conversazionale
                    completamento = client.models.generate_content(
                        model=modello_corrente,
                        contents=list(gemini_history)
                        + [
                            types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=domanda)],
                            ),
                            risultato.candidates[0].content,
                            types.Content(role="tool", parts=parti_risposte),
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=istruzioni_sistema,
                            temperature=0.0,
                        ),
                    )
                    risposta_testo = getattr(completamento, "text", None)

                # Fallback di estrazione parti testuali dai candidates
                if not risposta_testo and hasattr(risultato, "candidates") and risultato.candidates:
                    c = risultato.candidates[0]
                    if hasattr(c, "content") and hasattr(c.content, "parts"):
                        parti = [p.text for p in c.content.parts if getattr(p, "text", None)]
                        if parti:
                            risposta_testo = "".join(parti).strip()

                if not risposta_testo:
                    raise GeminiError("Il modello Gemini ha restituito una risposta vuota.")

                ULTIMO_MODELLO_USATO = modello_corrente
                if modello is None:
                    _ultimo_modello_gemini_valido = modello_corrente
                return risposta_testo

            except errors.APIError as api_err:
                ultimo_errore = api_err
                messaggio_err = str(api_err).upper()
                codice = getattr(api_err, "code", None)

                # Errori di autenticazione: non fare fallback, la chiave è errata
                if codice in (401, 403) or "API_KEY_INVALID" in messaggio_err or "PERMISSION_DENIED" in messaggio_err:
                    raise GeminiAuthError(
                        "Google Gemini non ha accettato la chiave API. Controlla GEMINI_API_KEY nel file .env."
                    ) from api_err

                # Non fare fallback su errori 400 (richiesta malformata, salvo modello non trovato)
                is_riprovabile = (
                    codice in STATI_RIPROVABILI
                    or "NOT_FOUND" in messaggio_err
                    or "RESOURCE_EXHAUSTED" in messaggio_err
                    or "UNAVAILABLE" in messaggio_err
                )
                if not is_riprovabile or indice == len(modelli) - 1:
                    if codice == 429 or "RESOURCE_EXHAUSTED" in messaggio_err:
                        raise GeminiQuotaError(
                            "Quota o rate limit superato per tutti i modelli Gemini configurati."
                        ) from api_err
                    raise GeminiError(f"Errore API Gemini ({codice}): {api_err}") from api_err
                continue

            except Exception as generico_err:
                ultimo_errore = generico_err
                err_str = str(generico_err)
                if "ConnectError" in type(generico_err).__name__ or "timeout" in err_str.lower():
                    if indice == len(modelli) - 1:
                        raise GeminiConnectionError(
                            f"Impossibile connettersi all'API di Google Gemini: {generico_err}"
                        ) from generico_err
                    continue
                if indice == len(modelli) - 1:
                    raise

        if ultimo_errore:
            raise ultimo_errore
        raise GeminiError("Nessun modello Gemini ha restituito una risposta.")

    # --------------------------------------------------------------------------
    # PERCORSO 2: REST nativa via urllib (se google-genai non è installato)
    # --------------------------------------------------------------------------
    ultimo_err_rest: Exception | None = None
    for indice, m in enumerate(modelli):
        try:
            return _genera_risposta_rest(
                domanda,
                fonti,
                chiave,
                m,
                memoria=memoria,
                contesto_collegamenti=contesto_collegamenti,
            )
        except (GeminiAuthError, GeminiQuotaError):
            raise
        except Exception as err:
            ultimo_err_rest = err
            if indice == len(modelli) - 1:
                raise

    if ultimo_err_rest:
        raise ultimo_err_rest
    raise GeminiError("Nessun modello Gemini ha risposto via REST.")


def main() -> int:
    """Interfaccia autonoma da terminale per testare direttamente il modello Google Gemini."""
    fonti = carica_fonti()
    if not fonti:
        print("Nessun file .txt trovato nella cartella dati.")
        return 1

    print("================================================================================")
    print("=== Test Modello Google Gemini (modello_gemini.py)                           ===")
    print("================================================================================")
    chiave = get_gemini_api_key()
    if not chiave:
        print("ATTENZIONE: GEMINI_API_KEY non trovata in .env!")
        chiave_inserita = input("Inserisci la tua chiave API Gemini (lascia vuoto per annullare): ").strip()
        if not chiave_inserita:
            print("Operazione annullata.")
            return 1
        os.environ["GEMINI_API_KEY"] = chiave_inserita

    modello_scelto = os.environ.get("GEMINI_MODEL") or valore_env("GEMINI_MODEL") or MODELLO_GEMINI_DEFAULT
    print(f"Modello Gemini predefinito: {modello_scelto}")
    print(f"Fonti caricate: {len(fonti)} file")
    print(f"Scrivi una domanda alla volta. Digita '{COMANDO_USCITA}' per terminare.\n")

    while True:
        try:
            domanda = input(f"\nDomanda (es. {DOMANDA_ESEMPIO}): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nProgramma terminato.")
            break

        if domanda.casefold() == COMANDO_USCITA:
            print("Programma terminato.")
            break
        if not domanda:
            print("La domanda è vuota: scrivi una domanda oppure digita 'esci'.")
            continue

        try:
            risposta = genera_risposta(domanda, fonti)
            print(f"\n[Gemini • {ULTIMO_MODELLO_USATO or modello_scelto}]:\n{risposta}")
            try:
                from Backend.database import salva_messaggio
                salva_messaggio(domanda, risposta, [nome for nome, _ in fonti])
            except Exception:
                pass
        except Exception as exc:
            print(f"Errore Gemini: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

