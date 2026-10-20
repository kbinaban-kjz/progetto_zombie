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
import re
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
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        get_gemini_api_key,
    )
    from Backend.sources import (
        formatta_blocco_openai,
        carica_fonti,
        formatta_timeline_giorni,
        seleziona_fonti_per_giorno,
    )
    from Backend.tools import (
        STRUMENTI_REGISTRATI,
        esegui_tool,
        cerca_fonti,
        leggi_fonte,
        elenca_fonti,
        ottieni_nodi_mappa,
        ottieni_dettaglio_nodo,
        cerca_cronologia,
        statistiche_missione,
    )
    from Backend.prompts import formatta_messaggio_cloud
except ImportError:
    from config import (
        MODELLO_GEMINI_DEFAULT,
        MODELLI_GEMINI_RISERVA,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        get_gemini_api_key,
    )
    from sources import (
        formatta_blocco_openai,
        carica_fonti,
        formatta_timeline_giorni,
        seleziona_fonti_per_giorno,
    )
    from tools import (
        STRUMENTI_REGISTRATI,
        esegui_tool,
        cerca_fonti,
        leggi_fonte,
        elenca_fonti,
        ottieni_nodi_mappa,
        ottieni_dettaglio_nodo,
        cerca_cronologia,
        statistiche_missione,
    )
    from prompts import formatta_messaggio_cloud

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

# Mappatura retrocompatibile per versioni ritirate o deprecate dell'API Google Gemini
ALIAS_MODELLI: dict[str, str] = {
    "gemini-3.8-flash-lite": "gemini-flash-lite-latest",
    "3.8-flash-lite": "gemini-flash-lite-latest",
    "3.8 flash lite": "gemini-flash-lite-latest",
    "gemini-flash-lite": "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite": "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite": "gemini-flash-lite-latest",
    "gemini-2.5-flash": "gemini-3.8-flash",
    "gemini-2.0-flash": "gemini-3.8-flash",
    "gemini-1.5-flash": "gemini-3.8-flash",
    "gemini-1.5-pro": "gemini-3.1-pro-preview",
    "gemini-2.5-pro": "gemini-3.1-pro-preview",
    "gemini-pro": "gemini-3.8-flash",
}


def ottieni_client(api_key: str) -> Any:
    """Restituisce un'istanza client google.genai.Client memorizzata nella cache."""
    if not GOOGLE_GENAI_DISPONIBILE or genai is None:
        return None
    chiave_pulita = api_key.strip()
    client = _client_cache.get(chiave_pulita)
    if client is None:
        client = genai.Client(api_key=chiave_pulita)
        _client_cache[chiave_pulita] = client
    return client


def _genera_risposta_rest(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    api_key: str,
    modello: str,
    timeline_giorni: str,
) -> str:
    """
    Fallback REST nativo via urllib: esegue la chiamata a Gemini senza librerie esterne.
    Utilizza l'endpoint generateContent ufficiale di Google Generative Language API.
    """
    global ULTIMO_MODELLO_USATO
    contenuto_fonti = formatta_blocco_openai(fonti)
    messaggio_completo = formatta_messaggio_cloud(
        contenuto_fonti, domanda, timeline_giorni
    )

    # Assicura formato corretto del modello per la REST API
    id_modello = modello.split("/")[-1] if "/" in modello else modello
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{id_modello}:generateContent?key={api_key.strip()}"

    payload = {
        "system_instruction": {
            "parts": [{"text": ISTRUZIONI}]
        },
        "contents": [
            {
                "parts": [{"text": messaggio_completo}]
            }
        ],
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
        with urllib.request.urlopen(req, timeout=30) as resp:
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
) -> str:
    """
    Invia la richiesta al modello Google Gemini.
    - Se usa_tools è True, abilita i tools definiti in tools.py.
    - Gestisce il fallback automatico tra i modelli Gemini configurati.
    - Utilizza google.genai se installato, altrimenti ripiega sulla REST API nativa.
    """
    global _ultimo_modello_gemini_valido, ULTIMO_MODELLO_USATO

    domanda = domanda.strip()
    if not domanda:
        raise ValueError("La domanda non può essere vuota.")
    if not re.search(r"\w", domanda, flags=re.UNICODE):
        return (
            "Non ho capito la richiesta. Puoi formulare una domanda o indicare "
            "quale aspetto del dossier vuoi analizzare?"
        )
    if not fonti:
        raise ValueError("Fornisci almeno una fonte.")
    timeline_giorni = formatta_timeline_giorni(fonti)
    fonti, giorni_richiesti = seleziona_fonti_per_giorno(domanda, fonti)
    if giorni_richiesti and not fonti:
        giorni = ", ".join(str(giorno) for giorno in sorted(giorni_richiesti))
        raise ValueError(f"Non sono disponibili fonti del Giorno {giorni} nel dossier caricato.")
    usa_tools = usa_tools and not giorni_richiesti

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
    messaggio_utente = formatta_messaggio_cloud(
        contenuto_fonti, domanda, timeline_giorni
    )

    # --------------------------------------------------------------------------
    # PERCORSO 1: google-genai SDK (se disponibile)
    # --------------------------------------------------------------------------
    if GOOGLE_GENAI_DISPONIBILE and genai is not None:
        client = ottieni_client(chiave)

        # Preparazione lista funzioni tools
        funzioni_tools: list[Any] = []
        if usa_tools:
            funzioni_tools = [
                cerca_fonti,
                leggi_fonte,
                elenca_fonti,
                ottieni_nodi_mappa,
                ottieni_dettaglio_nodo,
                cerca_cronologia,
                statistiche_missione,
            ]

        ultimo_errore: Exception | None = None

        for indice, modello_corrente in enumerate(modelli):
            try:
                config_kwargs: dict[str, Any] = {
                    "system_instruction": ISTRUZIONI,
                    "temperature": 0.0,
                }
                if funzioni_tools:
                    config_kwargs["tools"] = funzioni_tools

                config = types.GenerateContentConfig(**config_kwargs)

                # Se ci sono tools, usa Chat con Automatic Function Calling (raccomandato da Google)
                if funzioni_tools:
                    chat = client.chats.create(model=modello_corrente, config=config)
                    risultato = chat.send_message(messaggio_utente)
                else:
                    risultato = client.models.generate_content(
                        model=modello_corrente,
                        contents=messaggio_utente,
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

                    # Secondo turno con l'esito dei tool
                    completamento = client.models.generate_content(
                        model=modello_corrente,
                        contents=[
                            types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=messaggio_utente)],
                            ),
                            risultato.candidates[0].content,
                            types.Content(role="tool", parts=parti_risposte),
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=ISTRUZIONI,
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

                # Se è l'ultimo modello disponibile, rilancia l'errore
                if indice == len(modelli) - 1:
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
                domanda, fonti, chiave, m, timeline_giorni
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
