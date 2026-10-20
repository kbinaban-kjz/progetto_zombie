"""
Backend/router.py — Classificatore di complessità e instradamento ibrido (Locale vs Cloud).

Responsabilità:
- Analisi linguistica della richiesta (valuta_complessita).
- Decisione della strategia di risposta (Locale Investigatore.py vs Cloud modello_openai.py).
- Misurazione dei tempi di risposta (telemetria).
"""

import os
import re
import time
from collections.abc import Sequence
from typing import Any

try:
    from Backend.config import (
        MODELLO_LOCALE,
        MODELLO_NVIDIA_DEFAULT,
        MODELLO_GEMINI_DEFAULT,
        valore_env,
        stato_chiavi_api,
        get_gemini_api_key,
        get_nvidia_api_key,
        get_openai_api_key,
    )
    from Backend.modello_locale import (
        genera_risposta_locale,
        is_modello_caricato,
        richiede_ordinamento_cronologico,
        risposta_locale_da_fonti,
    )
    import Backend.modello_openai as modello_openai
    import Backend.modello_gemini as modello_gemini
    from Backend.sources import id_fonte, seleziona_fonti_per_giorno
except ImportError:
    from config import (
        MODELLO_LOCALE,
        MODELLO_NVIDIA_DEFAULT,
        MODELLO_GEMINI_DEFAULT,
        valore_env,
        stato_chiavi_api,
        get_gemini_api_key,
        get_nvidia_api_key,
        get_openai_api_key,
    )
    from modello_locale import (
        genera_risposta_locale,
        is_modello_caricato,
        richiede_ordinamento_cronologico,
        risposta_locale_da_fonti,
    )
    import modello_openai
    import modello_gemini
    from sources import id_fonte, seleziona_fonti_per_giorno

PAROLE_COMPLESSE = {
    "confronta",
    "confronto",
    "analizza",
    "analisi",
    "riassumi",
    "riassunto",
    "sintetizza",
    "sintesi",
    "spiega",
    "perché",
    "perche",
    "come mai",
    "ipotesi",
    "differenza",
    "differenze",
    "collegamento",
    "collegamenti",
    "relazione",
    "relazioni",
    "contraddizione",
    "contraddizioni",
    "incoerenza",
    "incoerenze",
    "tutte le fonti",
    "tutti i documenti",
    "tra i documenti",
    "incrocia",
    "incrociando",
    "dedurre",
    "deduzione",
    "dimostra",
    "dimostrato",
    "prove",
    "valuta",
    "approfond",
    "cronologia",
    "elenca tutti",
}


def valuta_complessita(domanda: str) -> tuple[bool, str]:
    """
    Determina se la domanda è semplice (False -> modello locale)
    oppure complessa (True -> modello cloud).
    Restituisce (is_complessa, motivo).
    """
    testo = domanda.strip()
    testo_lower = testo.lower()
    parole = re.findall(r"\w+", testo_lower)
    num_parole = len(parole)

    # 1. Domande multiple nella stessa richiesta
    if testo.count("?") > 1:
        return True, "Domanda multipla (più quesiti nella stessa richiesta)"

    # 2. Riferimento esplicito a più fonti/documenti (es. G1-01 e G1-02)
    fonti_citate = re.findall(r"g\d+-\d+", testo_lower)
    if len(set(fonti_citate)) > 1:
        return True, "Confronto esplicito tra più documenti del dossier"

    # 3. Parole chiave di ragionamento complesso, analisi, confronto o sintesi
    for indicatore in PAROLE_COMPLESSE:
        if indicatore.strip() in testo_lower:
            return True, f"Richiesta di ragionamento/analisi ('{indicatore.strip()}')"

    # 4. Domande lunghe o strutturate in più frasi
    if num_parole > 14 or len(testo) > 95:
        return True, f"Domanda articolata ({num_parole} parole)"

    return False, f"Domanda diretta e concisa ({num_parole} parole)"


def genera_risposta_ibrida(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    *,
    api_key: str | None = None,
    modello: str | None = None,
    modalita: str = "auto",
    usa_tools: bool = False,
) -> dict[str, Any]:
    """
    Smista la richiesta tra:
    - Modello locale (per richieste semplici o modalita='locale')
    - Modello cloud (per richieste complesse o modalita='cloud')
    """
    fonti, giorni_richiesti = seleziona_fonti_per_giorno(domanda, fonti)
    is_complessa, motivo = valuta_complessita(domanda)
    modalita_norm = (modalita or "auto").strip().lower()

    if modalita_norm == "locale":
        usa_cloud = False
        motivo = "Scelta manuale: Modello Locale"
    elif modalita_norm in {"cloud", "gemini", "nvidia", "openai"}:
        usa_cloud = True
        motivo = f"Scelta manuale: Modello Cloud ({modalita_norm.capitalize()})"
    else:
        usa_cloud = is_complessa

    livello = "complessa" if is_complessa else "semplice"
    inizio = time.perf_counter()

    if not re.search(r"\w", domanda, flags=re.UNICODE):
        return {
            "risposta": "Non ho capito la richiesta. Puoi formulare una domanda o indicare quale aspetto del dossier vuoi analizzare?",
            "motore": "input",
            "modello_usato": "Validazione della richiesta",
            "complessita": livello,
            "motivo_routing": "Richiesta priva di testo significativo",
            "durata_ms": int((time.perf_counter() - inizio) * 1000),
        }

    if giorni_richiesti and not fonti:
        giorni = ", ".join(str(giorno) for giorno in sorted(giorni_richiesti))
        return {
            "risposta": f"Non sono disponibili fonti del Giorno {giorni} nel dossier caricato.",
            "motore": "fonti",
            "modello_usato": "Ricerca nel dossier",
            "complessita": livello,
            "motivo_routing": f"Nessuna fonte disponibile per il Giorno {giorni}",
            "durata_ms": int((time.perf_counter() - inizio) * 1000),
        }

    if richiede_ordinamento_cronologico(domanda):
        esito = {
            "risposta": risposta_locale_da_fonti(domanda, fonti),
            "motore": "locale",
            "modello_usato": "Ordinamento deterministico degli eventi documentati",
            "complessita": livello,
            "motivo_routing": "Cronologia ordinata per giorno e orario registrato",
            "durata_ms": int((time.perf_counter() - inizio) * 1000),
        }
        return esito

    usa_tools_richiesti = usa_tools and is_complessa and not giorni_richiesti

    if not usa_cloud:
        risposta = genera_risposta_locale(domanda, fonti)
        if is_modello_caricato():
            modello_effettivo = MODELLO_LOCALE
        else:
            modello_effettivo = "Estrattore locale sulle fonti (torch/transformers non disponibili)"

        esito = {
            "risposta": risposta,
            "motore": "locale",
            "modello_usato": modello_effettivo,
            "complessita": livello,
            "motivo_routing": motivo,
        }
    else:
        # Richiesta complessa o forzata -> Modello Cloud (Gemini vs NVIDIA vs OpenAI)
        chiave_gem = get_gemini_api_key()
        chiave_nvi = get_nvidia_api_key()

        # Rilevamento provider cloud target
        usa_gemini = False
        if modalita_norm == "gemini":
            usa_gemini = True
        elif modalita_norm in {"nvidia", "openai"}:
            usa_gemini = False
        elif modello and "gemini" in modello.lower():
            usa_gemini = True
        elif modello and any(p in modello.lower() for p in ("nvidia", "nemotron", "meta/", "llama")):
            usa_gemini = False
        elif api_key:
            if api_key.startswith("AIza") or api_key.startswith("AQ."):
                usa_gemini = True
            elif api_key.startswith("nvapi-") or api_key.startswith("sk-"):
                usa_gemini = False
            else:
                usa_gemini = bool(chiave_gem and not chiave_nvi)
        else:
            preferenza_cloud = (valore_env("CLOUD_PROVIDER") or "").lower()
            if preferenza_cloud == "gemini":
                usa_gemini = True
            elif preferenza_cloud in {"nvidia", "openai"}:
                usa_gemini = False
            elif chiave_gem and not chiave_nvi:
                usa_gemini = True
            elif chiave_nvi:
                usa_gemini = False
            elif chiave_gem:
                usa_gemini = True

        if usa_gemini:
            risposta = modello_gemini.genera_risposta(
                domanda,
                fonti,
                api_key=api_key,
                modello=modello,
                usa_tools=usa_tools_richiesti,
            )
            modello_cloud = (
                modello_gemini.ULTIMO_MODELLO_USATO
                or modello
                or os.environ.get("GEMINI_MODEL")
                or valore_env("GEMINI_MODEL")
                or MODELLO_GEMINI_DEFAULT
            )
            esito = {
                "risposta": risposta,
                "motore": "gemini",
                "modello_usato": f"Gemini • {modello_cloud}",
                "complessita": livello,
                "motivo_routing": motivo,
            }
        else:
            risposta = modello_openai.genera_risposta(
                domanda,
                fonti,
                api_key=api_key,
                modello=modello,
                usa_tools=usa_tools_richiesti,
            )
            _, provider = stato_chiavi_api()
            usa_nvidia = (api_key and api_key.startswith("nvapi-")) or (
                not api_key and "NVIDIA" in provider
            )
            modello_cloud = (
                modello_openai.ULTIMO_MODELLO_USATO
                or modello
                or (
                    os.environ.get("NVIDIA_MODEL")
                    or valore_env("NVIDIA_MODEL")
                    or MODELLO_NVIDIA_DEFAULT
                    if usa_nvidia
                    else os.environ.get("OPENAI_MODEL")
                    or valore_env("OPENAI_MODEL")
                    or "gpt-4o-mini"
                )
            )
            esito = {
                "risposta": risposta,
                "motore": "cloud",
                "modello_usato": f"{'NVIDIA' if usa_nvidia else 'OpenAI'} • {modello_cloud}",
                "complessita": livello,
                "motivo_routing": motivo,
            }

    if giorni_richiesti:
        id_fonti_giorno = {
            id_fonte(nome, testo).casefold().replace("_", "-")
            for nome, testo in fonti
        }
        id_citati = {
            citazione.casefold().replace("_", "-")
            for citazione in re.findall(
                r"\b(?:g\d+-\d+|lx\d+[-_]\d+)\b", esito["risposta"], re.IGNORECASE
            )
        }
        if id_citati - id_fonti_giorno:
            esito["risposta"] = risposta_locale_da_fonti(domanda, fonti)
            esito["motore"] = "locale"
            esito["modello_usato"] = "Estrattore deterministico sulle fonti del giorno richiesto"
            esito["motivo_routing"] = (
                "Risposta Cloud scartata: citava documenti di un giorno diverso"
            )

    esito["durata_ms"] = int((time.perf_counter() - inizio) * 1000)
    print(
        f"[ROUTING] {esito['motore'].upper()} | {esito['modello_usato']} | "
        f"{livello} ({motivo}) | {esito['durata_ms']} ms"
    )
    return esito


if __name__ == "__main__":
    from Backend.sources import carica_fonti
    fonti_demo = carica_fonti()

    d1 = "Chi ha lasciato il messaggio?"
    comp1, mot1 = valuta_complessita(d1)
    print(f"'{d1}' -> Complessa: {comp1} ({mot1})")

    d2 = "Confronta tutte le fonti e analizza se la voce è affidabile."
    comp2, mot2 = valuta_complessita(d2)
    print(f"'{d2}' -> Complessa: {comp2} ({mot2})")

    res = genera_risposta_ibrida(d1, fonti_demo)
    print(f"Esito ibrido: {res['motore']} -> {res['risposta']}")
