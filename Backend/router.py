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
    from Backend.modello_locale import genera_risposta_locale, is_modello_caricato
    from Backend.database import leggi_ultimi_messaggi
    from Backend.sources import estrai_fonti_citate, scegli_fonti_dettagliato, verifica_grounding_risposta
    import Backend.modello_openai as modello_openai
    import Backend.modello_gemini as modello_gemini
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
    from modello_locale import genera_risposta_locale, is_modello_caricato
    from database import leggi_ultimi_messaggi
    from sources import estrai_fonti_citate, scegli_fonti_dettagliato, verifica_grounding_risposta
    import modello_openai
    import modello_gemini

PAROLE_COMPLESSE: tuple[str, ...] = (
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
    "collega",
    "collegano",
    "collegando",
    "quali documenti",
    "smentisce",
    "smentiscono",
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
    "focolaio",
    "causa",
    "colpevole",
    "sabotaggio",
    "firmato",
    "sincronizz",
    "ripetitore",
    "manomess",
    "audit",
    "coordinate",
    "pensi",
    "secondo te",
    "quanti",
    "quante",
)


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

    # 2. Riferimento esplicito a più fonti/documenti (es. G1-01, G2-01, LX5-1264, ARCH-3097)
    fonti_citate = {
        m.replace("_", "-")
        for m in re.findall(r"(?:g\d+-\d+|lx5[-_]\d+|arch[-_]\d+|wiki[-_]\d+|documento[-_]\d+)", testo_lower)
    }
    if len(fonti_citate) > 1:
        return True, "Confronto esplicito tra più documenti del dossier"

    # 3. Parole chiave di ragionamento complesso, analisi, confronto o sintesi (con word boundary iniziale)
    for indicatore in PAROLE_COMPLESSE:
        ind_clean = indicatore.strip()
        if re.search(rf"\b{re.escape(ind_clean)}", testo_lower):
            return True, f"Richiesta di ragionamento/analisi ('{ind_clean}')"

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
    usa_tools: bool = True,
    memoria: list[dict[str, Any]] | None = None,
    limite_memoria: int = 6,
) -> dict[str, Any]:
    """
    Smista la richiesta tra:
    - Modello locale (per richieste semplici o modalita='locale')
    - Modello cloud (per richieste complesse o modalita='cloud')
    Carica automaticamente gli ultimi `limite_memoria` messaggi dal database SQLite
    per garantire la continuità conversazionale dell'agente.
    """
    # Carica la memoria degli ultimi messaggi dal database se non passata esplicitamente
    if memoria is None:
        try:
            memoria = leggi_ultimi_messaggi(limite=limite_memoria)
        except Exception as exc:
            print(f"(Avviso recupero memoria database SQLite: {exc})")
            memoria = []
    limite = max(0, int(limite_memoria))
    memoria_limitata = []
    for messaggio in memoria[-limite:] if limite else []:
        if not isinstance(messaggio, dict):
            continue
        messaggio_limitato = dict(messaggio)
        for chiave in ("domanda", "risposta"):
            valore = messaggio.get(chiave)
            testo = valore.strip() if isinstance(valore, str) else ""
            messaggio_limitato[chiave] = testo[:497] + "..." if len(testo) > 500 else testo
        memoria_limitata.append(messaggio_limitato)
    memoria = memoria_limitata

    is_complessa, motivo = valuta_complessita(domanda)
    modalita_norm = (modalita or "auto").strip().lower()
    ha_chiave_env, _ = stato_chiavi_api()

    if modalita_norm == "locale":
        usa_cloud = False
        motivo = "Scelta manuale: Modello Locale"
    elif modalita_norm in {"cloud", "gemini", "nvidia", "openai"}:
        usa_cloud = True
        motivo = f"Scelta manuale: Modello Cloud ({modalita_norm.capitalize()})"
    else:
        if is_complessa and not (api_key or ha_chiave_env):
            usa_cloud = False
            motivo = f"{motivo} [Fallback Locale: nessuna chiave Cloud configurata]"
        else:
            usa_cloud = is_complessa

    livello = "complessa" if is_complessa else "semplice"
    inizio = time.perf_counter()

    # Recupero RAG (Giorno 3 — Operazione Esumazione): cerca prima i pezzi utili nell'archivio
    # (inclusi i 1.005 file TXT, HTML, JSON, XML in dati/archivio/) e li unisce al contesto.
    esito_rag = scegli_fonti_dettagliato(domanda, top_k=8)
    fonti_rag = esito_rag["fonti"]
    file_recuperati_rag = esito_rag["file_recuperati"]

    # Unisce i documenti recuperati dal RAG con il dossier base senza duplicati,
    # mettendo in testa i file recuperati dal RAG per massimizzare la rilevanza.
    fonti_combinate: list[tuple[str, str]] = []
    visti_nomi: set[str] = set()
    for n_f, t_f in list(fonti_rag) + list(fonti):
        if n_f not in visti_nomi:
            visti_nomi.add(n_f)
            fonti_combinate.append((n_f, t_f))

    if not usa_cloud:
        risposta = genera_risposta_locale(
            domanda,
            fonti_combinate,
            memoria=memoria,
            file_prioritari=file_recuperati_rag,
        )
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

        contesto_coll = esito_rag.get("testo_collegamenti", "")
        try:
            from Backend.evidenze import risposta_imprevisti
        except ImportError:
            try:
                from evidenze import risposta_imprevisti
            except ImportError:
                risposta_imprevisti = None
        if risposta_imprevisti is not None:
            try:
                evid = risposta_imprevisti(domanda)
                if evid and "ANALISI EVIDENZE" not in contesto_coll:
                    contesto_coll = f"{contesto_coll}\n\nANALISI EVIDENZE E CATENA MULTI-DOCUMENTO:\n{evid}".strip()
            except Exception:
                pass

        if usa_gemini:
            risposta = modello_gemini.genera_risposta(
                domanda,
                fonti_combinate,
                api_key=api_key,
                modello=modello,
                usa_tools=usa_tools,
                memoria=memoria,
                contesto_collegamenti=contesto_coll,
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
                fonti_combinate,
                api_key=api_key,
                modello=modello,
                usa_tools=usa_tools,
                memoria=memoria,
                contesto_collegamenti=contesto_coll,
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

    grounding = verifica_grounding_risposta(esito.get("risposta", ""), fonti_combinate)
    esito["fonti_citate"] = grounding["fonti_file"]
    esito["file_recuperati_rag"] = file_recuperati_rag
    esito["dettagli_rag"] = esito_rag["dettagli_file"]
    esito["collegamenti"] = esito_rag.get("collegamenti", [])
    esito["percorso_collegamento"] = esito_rag.get("percorso_collegamento")
    esito["grounding_ok"] = grounding["ok"]
    esito["citazioni_ignote"] = grounding["citazioni_ignote"]
    esito["memoria_usata"] = len(memoria)
    esito["durata_ms"] = int((time.perf_counter() - inizio) * 1000)
    print(
        f"[ROUTING] {esito['motore'].upper()} | {esito['modello_usato']} | "
        f"{livello} ({motivo}) | RAG: {file_recuperati_rag[:4]} | fonti citate: {len(esito['fonti_citate'])} | "
        f"memoria: {len(memoria)} msg | {esito['durata_ms']} ms"
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
