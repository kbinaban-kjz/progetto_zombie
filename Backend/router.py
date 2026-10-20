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
        valore_env,
        stato_chiavi_api,
    )
    from Backend.modello_locale import genera_risposta_locale, is_modello_caricato
    import Backend.modello_openai as modello_openai
except ImportError:
    from config import (
        MODELLO_LOCALE,
        MODELLO_NVIDIA_DEFAULT,
        valore_env,
        stato_chiavi_api,
    )
    from modello_locale import genera_risposta_locale, is_modello_caricato
    import modello_openai

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
    is_complessa, motivo = valuta_complessita(domanda)
    modalita_norm = (modalita or "auto").strip().lower()

    if modalita_norm == "locale":
        usa_cloud = False
        motivo = "Scelta manuale: Modello Locale"
    elif modalita_norm == "cloud":
        usa_cloud = True
        motivo = "Scelta manuale: Modello Cloud"
    else:
        usa_cloud = is_complessa

    livello = "complessa" if is_complessa else "semplice"
    inizio = time.perf_counter()

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
        # Richiesta complessa -> Modello Cloud
        risposta = modello_openai.genera_risposta(
            domanda,
            fonti,
            api_key=api_key,
            modello=modello,
            usa_tools=usa_tools,
        )
        _, provider = stato_chiavi_api()
        usa_nvidia = (api_key and api_key.startswith("nvapi-")) or (
            not api_key and provider == "NVIDIA"
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

