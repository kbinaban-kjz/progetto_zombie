"""
Backend/modello_openai.py — Chiamata ai modelli Cloud (OpenAI e NVIDIA NIM) con supporto strumenti.

Responsabilità:
- Connessione e gestione dei client API OpenAI e NVIDIA NIM.
- Meccanismo di fallback automatico sui modelli di riserva NVIDIA in caso di errori o saturazione quota.
- Supporto opzionale agli strumenti (Function Calling) definiti in tools.py.
- Gestione resiliente dell'importazione della libreria openai.
"""

import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from Backend.config import (
        NVIDIA_BASE_URL,
        MODELLO_NVIDIA_DEFAULT,
        MODELLI_NVIDIA_RISERVA,
        MODELLO_OPENAI_DEFAULT,
        TIMEOUT_SECONDI,
        STATI_RIPROVABILI,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
    )
    from Backend.sources import formatta_blocco_openai, carica_fonti
    from Backend.tools import TOOLS_OPENAI_SCHEMA, esegui_tool
    from Backend.prompts import formatta_messaggio_cloud
except ImportError:
    from config import (
        NVIDIA_BASE_URL,
        MODELLO_NVIDIA_DEFAULT,
        MODELLI_NVIDIA_RISERVA,
        MODELLO_OPENAI_DEFAULT,
        TIMEOUT_SECONDI,
        STATI_RIPROVABILI,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
    )
    from sources import formatta_blocco_openai, carica_fonti
    from tools import TOOLS_OPENAI_SCHEMA, esegui_tool
    from prompts import formatta_messaggio_cloud

# Gestione tollerante dell'importazione di OpenAI
try:
    from openai import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        AuthenticationError,
        OpenAI,
        OpenAIError,
    )
    OPENAI_DISPONIBILE = True
except ImportError:
    OPENAI_DISPONIBILE = False

    class OpenAIError(Exception):
        """Classe di fallback per errori OpenAI se il modulo non è installato."""
        pass

    class AuthenticationError(OpenAIError):
        pass

    class APIConnectionError(OpenAIError):
        pass

    class APITimeoutError(OpenAIError):
        pass

    class APIStatusError(OpenAIError):
        def __init__(self, message: str, status_code: int = 500):
            super().__init__(message)
            self.status_code = status_code

    OpenAI = None

_client_cache: dict[tuple[str, str | None, int], Any] = {}
_ultimo_modello_nvidia_valido: str | None = None
ULTIMO_MODELLO_USATO: str | None = None


def _valore_env_file(nome: str) -> str | None:
    """Funzione helper per retrocompatibilità."""
    return valore_env(nome)


def ottieni_client(api_key: str, base_url: str | None, max_retries: int) -> Any:
    """Restituisce un'istanza client OpenAI memorizzata nella cache."""
    if not OPENAI_DISPONIBILE or OpenAI is None:
        raise RuntimeError(
            "La libreria 'openai' non è installata. Installa i requisiti con: pip install -r requirements.txt"
        )
    chiave_cache = (api_key, base_url, max_retries)
    client = _client_cache.get(chiave_cache)
    if client is None:
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            timeout=TIMEOUT_SECONDI,
        )
        _client_cache[chiave_cache] = client
    return client


def genera_risposta(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    *,
    api_key: str | None = None,
    modello: str | None = None,
    usa_tools: bool = False,
    memoria: list[dict[str, Any]] | None = None,
) -> str:
    """
    Invia la richiesta al modello Cloud (NVIDIA NIM o OpenAI).
    Se usa_tools è True, abilita gli schemi di function calling definiti in tools.py.
    Supporta la memoria conversazionale degli ultimi messaggi scambiati.
    """
    global _ultimo_modello_nvidia_valido, ULTIMO_MODELLO_USATO

    domanda = domanda.strip()
    if not domanda:
        raise ValueError("La domanda non può essere vuota.")
    if not fonti:
        raise ValueError("Fornisci almeno una fonte.")

    if not OPENAI_DISPONIBILE:
        raise RuntimeError(
            "Modulo 'openai' non installato. Per le richieste Cloud esegui: pip install -r requirements.txt"
        )

    chiave_nvidia = os.environ.get("NVIDIA_API_KEY") or valore_env("NVIDIA_API_KEY")
    chiave_openai = os.environ.get("OPENAI_API_KEY") or valore_env("OPENAI_API_KEY")

    usa_nvidia = (api_key is not None and api_key.startswith("nvapi-")) or (
        api_key is None and bool(chiave_nvidia)
    )
    chiave = api_key or chiave_nvidia or chiave_openai
    if not chiave:
        raise ValueError(
            "Configura NVIDIA_API_KEY oppure OPENAI_API_KEY nel file .env o nelle variabili d'ambiente."
        )

    contenuto_fonti = formatta_blocco_openai(fonti)
    base_url = None
    if usa_nvidia:
        base_url = os.environ.get("NVIDIA_BASE_URL", NVIDIA_BASE_URL)
    elif api_key is None:
        base_url = os.environ.get("OPENAI_BASE_URL")

    modello_env = (
        os.environ.get("NVIDIA_MODEL") or valore_env("NVIDIA_MODEL")
        if usa_nvidia
        else os.environ.get("OPENAI_MODEL") or valore_env("OPENAI_MODEL")
    )
    modello_principale = modello or modello_env or (
        (_ultimo_modello_nvidia_valido or MODELLO_NVIDIA_DEFAULT)
        if usa_nvidia
        else MODELLO_OPENAI_DEFAULT
    )
    modelli = [modello_principale]
    if usa_nvidia:
        modelli.extend(
            modello_riserva
            for modello_riserva in MODELLI_NVIDIA_RISERVA
            if modello_riserva not in modelli
        )

    client = ottieni_client(
        api_key=chiave.strip(),
        base_url=base_url,
        max_retries=0 if usa_nvidia else 1,
    )
    messaggi: list[dict[str, Any]] = [{"role": "system", "content": ISTRUZIONI}]

    # Inietta i turni della memoria passata
    if memoria:
        for m in memoria:
            d = (m.get("domanda") or "").strip()
            r = (m.get("risposta") or "").strip()
            if d:
                messaggi.append({"role": "user", "content": d})
            if r:
                messaggi.append({"role": "assistant", "content": r})

    messaggi.append(
        {
            "role": "user",
            "content": formatta_messaggio_cloud(contenuto_fonti, domanda, memoria=memoria),
        }
    )

    risultato = None
    for indice, modello_corrente in enumerate(modelli):
        try:
            kwargs_chiamata: dict[str, Any] = {
                "model": modello_corrente,
                "messages": messaggi,
                "temperature": 0,
            }
            if "gemini" in modello_corrente.lower():
                kwargs_chiamata["reasoning_effort"] = "low"
            if usa_tools and TOOLS_OPENAI_SCHEMA:
                kwargs_chiamata["tools"] = TOOLS_OPENAI_SCHEMA

            risultato = client.chat.completions.create(**kwargs_chiamata)
            ULTIMO_MODELLO_USATO = modello_corrente
            if usa_nvidia and modello is None:
                _ultimo_modello_nvidia_valido = modello_corrente
            break
        except AuthenticationError:
            raise
        except (APIConnectionError, APITimeoutError):
            if not usa_nvidia or indice == len(modelli) - 1:
                raise
        except APIStatusError as errore:
            if (
                not usa_nvidia
                or getattr(errore, "status_code", None) not in STATI_RIPROVABILI
                or indice == len(modelli) - 1
            ):
                raise

    if risultato is None:
        raise RuntimeError("Nessun modello ha restituito una risposta.")

    messaggio_risposta = risultato.choices[0].message

    # Gestione di eventuali Tool Calls emesse dal modello
    if getattr(messaggio_risposta, "tool_calls", None):
        messaggi.append(messaggio_risposta)
        for tool_call in messaggio_risposta.tool_calls:
            nome_tool = tool_call.function.name
            argomenti_raw = tool_call.function.arguments
            esito_tool = esegui_tool(nome_tool, argomenti_raw)
            messaggi.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(esito_tool, ensure_ascii=False),
                }
            )

        # Secondo passo di completamento con i dati restituiti dal tool
        completamento_finale = client.chat.completions.create(
            model=ULTIMO_MODELLO_USATO or modello_principale,
            messages=messaggi,
            temperature=0,
        )
        risposta_testo = completamento_finale.choices[0].message.content
        if not risposta_testo:
            raise RuntimeError("Il modello cloud ha restituito una risposta finale vuota.")
        return risposta_testo

    risposta = messaggio_risposta.content
    if not risposta:
        raise RuntimeError("Il modello cloud ha restituito una risposta vuota.")
    return risposta


def main() -> int:
    """Interfaccia autonoma da terminale per testare direttamente il modello cloud."""
    fonti = carica_fonti()
    if not fonti:
        print("Nessun file .txt trovato nella cartella dati.")
        return 1

    print("=== Test Modello Cloud (modello_openai.py) ===")
    print(f"Scrivi una domanda alla volta. Digita '{COMANDO_USCITA}' per terminare.")

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
            print(f"\nRisposta:\n{risposta}")
            from Backend.database import salva_messaggio
            salva_messaggio(domanda, risposta, [nome for nome, _ in fonti])
        except Exception as exc:
            print(f"Errore: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
