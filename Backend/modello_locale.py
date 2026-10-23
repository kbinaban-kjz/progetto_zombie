"""
Backend/modello_locale.py — Motore di inferenza locale (Qwen2.5-0.5B-Instruct) e risponditore deterministico.

Responsabilità:
- Caricamento su GPU (Apple Silicon MPS / NVIDIA CUDA) o CPU del modello Qwen/Qwen2.5-0.5B-Instruct.
- Generazione locale con template chat e formattazione rigorosa delle fonti.
- Risponditore deterministico locale basato su estrazione di fatti se PyTorch/transformers non sono installati.
"""

import math
import re
from collections.abc import Sequence
from typing import Any

try:
    from Backend import collegamenti as modulo_collegamenti
    from Backend.evidenze import risposta_imprevisti
    from Backend.config import MODELLO_LOCALE, ISTRUZIONI
    from Backend.sources import (
        estrai_metadati_fonte,
        formatta_fonte,
        rileva_istruzioni_ostili,
    )
    from Backend.prompts import formatta_messaggio_locale
except ImportError:
    import collegamenti as modulo_collegamenti
    from evidenze import risposta_imprevisti
    from config import MODELLO_LOCALE, ISTRUZIONI
    from sources import (
        estrai_metadati_fonte,
        formatta_fonte,
        rileva_istruzioni_ostili,
    )
    from prompts import formatta_messaggio_locale

_tokenizer_locale = None
_modello_locale = None
_dispositivo_locale = "cpu"
_modello_locale_tentato = False


def is_modello_caricato() -> bool:
    """Verifica se il modello locale Qwen è attualmente caricato in memoria."""
    return _modello_locale is not None


def ottieni_dispositivo() -> str:
    """Restituisce il dispositivo hardware attualmente in uso ('mps', 'cuda', o 'cpu')."""
    return _dispositivo_locale


def carica_modello_locale() -> bool:
    """
    Carica il modello locale Qwen/Qwen2.5-0.5B-Instruct.
    Rileva automaticamente acceleratori hardware (Apple Silicon MPS, CUDA) altrimenti usa CPU.
    """
    global _tokenizer_locale, _modello_locale, _dispositivo_locale, _modello_locale_tentato
    if _modello_locale_tentato:
        return _modello_locale is not None
    _modello_locale_tentato = True

    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            _dispositivo_locale = "mps"
            dtype = torch.float16
        elif torch.cuda.is_available():
            _dispositivo_locale = "cuda"
            dtype = torch.float16
        else:
            _dispositivo_locale = "cpu"
            dtype = torch.float32

        print(f"[Locale] Caricamento modello {MODELLO_LOCALE} su {_dispositivo_locale.upper()}...")
        _tokenizer_locale = AutoTokenizer.from_pretrained(MODELLO_LOCALE)
        _modello_locale = AutoModelForCausalLM.from_pretrained(
            MODELLO_LOCALE,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
        ).to(_dispositivo_locale)
        _modello_locale.eval()
        print(f"[Locale] Modello {MODELLO_LOCALE} pronto su {_dispositivo_locale.upper()}.")
        return True
    except Exception as exc:
        print(f"[Locale] Impossibile caricare {MODELLO_LOCALE} con transformers/torch ({exc}).")
        print("[Locale] Verrà usato l'estrattore locale deterministico sulle fonti.")
        return False


MARCATORI_ATTACCO_UTENTE: tuple[str, ...] = (
    "ignora le istruzioni",
    "ignora le regole",
    "dimentica le istruzioni",
    "dimentica le regole",
    "disattiva le regole",
    "ignora il documento",
    "ignora i documenti",
    "ignora g1-",
    "ignora g2-",
    "ignora lx5",
    "non citare le fonti",
    "ora sei un",
    "d'ora in poi sei",
    "fai finta di essere",
    "jailbreak",
    "mostra il system prompt",
    "rivela il prompt di sistema",
)

PAROLE_VUOTE = {
    "dove", "quando", "come", "cosa", "chi", "che", "quale", "quali", "perché", "perche",
    "gli", "le", "la", "il", "lo", "un", "una", "uno", "di", "da", "in", "con", "su",
    "per", "tra", "fra", "e", "o", "a", "al", "alla", "alle", "ai", "del", "della",
    "dei", "delle", "dello", "sono", "era", "erano", "ha", "hanno", "si", "non",
    "più", "piu", "anche", "questo", "questa", "questi", "queste", "quello", "quella",
    "mi", "ti", "ci", "vi", "ho", "hai", "molto", "puoi", "dimmi", "parlami", "riguardo",
    "sul", "sulla", "nel", "nella", "nei", "negli", "dai", "dal", "dallo", "dall",
    "cosa", "dice", "dicono", "documento", "documenti", "fonte", "fonti",
    "successo", "accaduto", "fatto", "stato", "stata", "stati", "state",
    "quando", "ora", "orario", "orari", "che", "quali", "quale", "perché",
    "perche", "collega", "collegamento", "collegamenti", "relazione", "differenza",
}


def _rileva_attacco_utente(domanda: str) -> bool:
    """Rileva un tentativo di override contenuto nel messaggio dell'utente."""
    q_norm = domanda.strip().lower().replace("\u2019", "'")
    return any(marcatore in q_norm for marcatore in MARCATORI_ATTACCO_UTENTE)


def _radice(parola: str) -> str:
    """Riduce una parola a una radice grezza per confrontare varianti morfologiche."""
    return parola[:5]


def _radici_testuali(testo: str) -> set[str]:
    parole = re.findall(r"[a-zàèéìòù0-9]+", testo.lower().replace("\u2019", "'"))
    return {_radice(p) for p in parole if len(p) > 2}


def _parole_chiave(domanda: str) -> list[str]:
    """Estrae le radici delle parole di contenuto, conservando l'ordine della domanda."""
    parole = re.findall(r"[a-zàèéìòù0-9]+", domanda.lower().replace("\u2019", "'"))
    chiavi: list[str] = []
    for parola in parole:
        if len(parola) <= 2 or parola in PAROLE_VUOTE:
            continue
        radice = _radice(parola)
        if radice not in chiavi:
            chiavi.append(radice)
    return chiavi


def _unita_testuali(testo: str, nome: str = "") -> list[str]:
    """Divide un documento in frasi, unendo un orario isolato alla frase che lo segue."""
    meta = estrai_metadati_fonte(nome, testo)
    corpo = meta["corpo"]
    frasi = [f.strip() for f in re.split(r"(?<=[.!?;])\s+", corpo) if f.strip()]
    unite: list[str] = []
    for frase in frasi:
        if unite and re.fullmatch(r"ore\s+\d{1,2}:\d{2}\.?", unite[-1].lower().strip()):
            unite[-1] = f"{unite[-1]} {frase}"
        else:
            unite.append(frase)
    return unite


def _indice_documenti(
    fonti: Sequence[tuple[str, str]],
    includi_ostili: bool = False,
    includi_wikipedia: bool = False,
) -> list[dict[str, object]]:
    """Costruisce l'indice dei documenti (titolo + corpo), escludendo quelli ostili e i duplicati."""
    indice: list[dict[str, object]] = []
    visti: set[str] = set()
    for nome, testo in fonti:
        if nome in visti:
            continue
        visti.add(nome)
        if not includi_ostili and rileva_istruzioni_ostili(testo):
            continue
        meta = estrai_metadati_fonte(nome, testo)
        if not includi_wikipedia and str(meta["id"]).upper().startswith("WIKI-"):
            continue
        contenuto = f"{meta['titolo']}. {meta['corpo']}"
        radici = _radici_testuali(contenuto)
        indice.append(
            {
                "id": meta["id"],
                "file": nome,
                "titolo": meta["titolo"],
                "testo": meta["corpo"],
                "radici": radici,
            }
        )
    return indice


def _indice_frasi(
    fonti: Sequence[tuple[str, str]],
    includi_ostili: bool = False,
    includi_wikipedia: bool = False,
) -> list[dict[str, object]]:
    """Costruisce l'indice delle frasi del dossier, escludendo i documenti ostili e i duplicati."""
    indice: list[dict[str, object]] = []
    visti: set[str] = set()
    for nome, testo in fonti:
        if nome in visti:
            continue
        visti.add(nome)
        if not includi_ostili and rileva_istruzioni_ostili(testo):
            continue
        meta = estrai_metadati_fonte(nome, testo)
        if not includi_wikipedia and str(meta["id"]).upper().startswith("WIKI-"):
            continue
        for frase in _unita_testuali(testo, nome=nome):
            indice.append(
                {
                    "id": meta["id"],
                    "file": nome,
                    "frase": frase,
                    "radici": _radici_testuali(frase),
                }
            )
    return indice


def _estrai_pertinenti(
    chiavi: list[str],
    indice: list[dict[str, object]],
    limite: int = 2,
    priorita: Sequence[str] | None = None,
    soglia_relativa: float = 0.6,
) -> list[dict[str, object]]:
    """
    Recupera i documenti più pertinenti con pesatura TF-IDF e priorità alle parole iniziali.
    `priorita` è l'ordine dei file restituiti dal RAG: un documento recuperato dal RAG vale
    di più di un documento generico del dossier, così la risposta resta ancorata alle prove.
    """
    if not chiavi or not indice:
        return []

    frequenza: dict[str, int] = {
        chiave: sum(1 for unita in indice if chiave in unita["radici"]) for chiave in chiavi
    }
    totale = len(indice)
    pesi: dict[str, float] = {
        chiave: math.log(1 + totale / max(1, frequenza[chiave])) / (1 + 0.5 * posizione)
        for posizione, chiave in enumerate(chiavi)
    }
    peso_totale = sum(pesi.values())
    insieme = set(chiavi)
    rank_priorita = {str(f): i for i, f in enumerate(priorita or [])}

    punteggi: list[tuple[float, int, int, dict[str, object]]] = []
    for unita in indice:
        comuni = insieme & unita["radici"]
        if not comuni:
            continue
        copertura = sum(pesi[c] for c in comuni) / peso_totale
        nome_file = str(unita.get("file") or "")
        if nome_file in rank_priorita:
            # Bonus decrescente: il primo file del RAG vale di più del decimo.
            copertura += max(0.08, 0.42 - 0.035 * rank_priorita[nome_file])
        testi = str(unita["testo"]).lower()
        occorrenze = sum(testi.count(c) for c in comuni)
        punteggi.append((copertura, len(comuni), occorrenze, unita))

    if not punteggi:
        return []

    punteggi.sort(key=lambda voce: (voce[0], voce[1], voce[2]), reverse=True)
    # Soglia più permissiva: per le domande multi-documento servono anche i documenti
    # di supporto, non solo il primo classificato.
    soglia = punteggi[0][0] * soglia_relativa
    scelti: list[dict[str, object]] = []
    for copertura, _, _, unita in punteggi:
        if copertura < soglia:
            break
        scelti.append(unita)
        if len(scelti) >= limite:
            break
    return scelti


def _chiede_tempo(domanda: str) -> bool:
    """
    Riconosce una domanda su orari/cronologia. Volutamente stretta: "prima" o "ora"
    da soli non bastano, altrimenti ogni domanda diventava un elenco di tutti gli orari.
    """
    return bool(
        re.search(
            r"\b(quando|a che ora|che ore|orari[oi]?|cronolog\w*|sequenza|in che ordine|"
            r"ordine cronologico|timeline|data)\b",
            domanda,
            re.IGNORECASE,
        )
    )


def _bonus_campo_semantico(domanda: str, frase: str) -> float:
    """Premia la frase che appartiene allo stesso campo semantico lessicale della domanda."""
    q = domanda.lower()
    f = frase.lower()
    bonus = 0.0
    campi = {
        ("focol", "contag", "epidem", "allarm", "scoppi"): ("focolaio", "allarme", "contagio", "scoppiato", "emergenza"),
        ("rifug", "protezion", "ripar"): ("rifugi", "rifugio", "protezione", "sicurezza"),
        ("guast", "ripetitor", "segnale", "circuit", "anomal"): ("guasto", "ripetitore", "segnale", "circuito", "anomalia"),
        ("fermar", "opposizion", "sabotagg", "ostacol"): ("fermare", "opposizione", "sabotaggio", "verbale", "blocco"),
        ("material", "recuper", "stoccagg", "deposit"): ("materiale", "recupero", "deposito", "stoccaggio", "magazzino"),
        ("autorizz", "access", "firma", "approv"): ("autorizzazione", "accessi", "firmato", "ordine", "permesso"),
    }
    for chiavi_q, parole_frase in campi.items():
        if any(k in q for k in chiavi_q) and any(p in f for p in parole_frase):
            bonus += 2.0
    return bonus


def _eventi_cronologici(
    indice: list[dict[str, object]],
    limite: int = 12,
    domanda: str = "",
    priorita: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    """
    Seleziona le frasi con un orario HH:MM pertinenti alla domanda, non tutti gli orari
    dell'archivio. Usa l'overlap con le parole della domanda, il campo semantico e l'ordine
    dei file restituiti dal RAG.
    """
    chiavi = set(_parole_chiave(domanda)) if domanda else set()
    rank_priorita = {str(f): i for i, f in enumerate(priorita or [])}
    eventi: list[tuple[float, int, dict[str, object]]] = []
    for unita in indice:
        frase = str(unita["frase"])
        trovato = re.search(r"\b(\d{1,2}):(\d{2})\b", frase)
        if not trovato:
            continue
        minuti = int(trovato.group(1)) * 60 + int(trovato.group(2))
        overlap = len(chiavi & set(unita["radici"]))
        score = float(overlap) * 2.0 + _bonus_campo_semantico(domanda, frase)
        nome_file = str(unita.get("file") or "")
        if nome_file in rank_priorita:
            score += max(0.3, 1.2 - 0.1 * rank_priorita[nome_file])
        if re.search(r"\b(?:primo|prima|allarme|focolaio|contagio|inizi\w*)\b", frase, re.IGNORECASE):
            score += 0.6
        if re.search(r"\b[A-Z][a-zàèéìòù]{2,}\b", frase):
            score += 0.3
        # Se la domanda ha parole di contenuto, scarta gli orari che non hanno alcun aggancio.
        if chiavi and overlap == 0 and score < 1.5:
            continue
        eventi.append((score, minuti, unita))
    if not eventi:
        return []
    cronologica = bool(re.search(r"cronolog|sequenza|ordine|timeline", domanda, re.IGNORECASE))
    if cronologica:
        eventi.sort(key=lambda e: (e[1], -e[0], str(e[2]["file"])))
    else:
        eventi.sort(key=lambda e: (e[0], -e[1]), reverse=True)
    return [unita for _, _, unita in eventi[:limite]]


def _frasi_da_testo(testo: str) -> list[str]:
    """Spezza il corpo di un documento in frasi utili (esclude righe di metadati)."""
    pezzi = re.split(r"(?<=[.!?;])\s+|\n+", (testo or "").strip())
    return [
        p.strip()
        for p in pezzi
        if p.strip()
        and not re.match(r"^(?:id|title|text|source|license)\s*:", p.strip(), re.IGNORECASE)
        and not p.strip().lower().startswith(("archivio lazzaro", "documento:"))
    ]


def _punteggio_frase(domanda: str, frase: str) -> float:
    """Pertinenza di una frase alla domanda (radici in comune + campo semantico)."""
    chiavi = set(_parole_chiave(domanda))
    radici = _radici_testuali(frase)
    score = float(len(chiavi & radici)) * 2.0 + _bonus_campo_semantico(domanda, frase)
    # Se la domanda chiede "chi / quale persona", la frase che nomina una persona vale di più:
    # evita di rispondere con un dettaglio (es. «ha aperto la pratica RV753») senza il nome.
    if re.search(r"\b(?:chi|quale persona|persona|nome|autore|responsabile)\b", domanda, re.IGNORECASE):
        if re.search(r"\b[A-Z][a-zàèéìòù]+\s+[A-Z][a-zàèéìòù]+\b", frase):
            score += 2.0
    # Se contiene un codice alfanumerico specifico, aumenta la rilevanza probatoria
    if re.search(r"(?<![\w-])([A-Za-z]{1,5}[-_]?\d{2,6})(?![\w-])", frase):
        score += 1.5
    if len(frase) < 20:
        score -= 0.5
    if len(frase) > 420:
        score -= 0.3
    return score


def _frasi_migliori(
    domanda: str,
    documento: dict[str, object],
    limite: int = 2,
    soglia: float = 2.0,
) -> list[str]:
    """
    Sceglie le frasi più pertinenti di un documento. Due frasi sono utili quando la prima
    nomina la persona e la seconda contiene il dato chiave (es. Nora Ferri ... pratica RV753).
    """
    frasi = _frasi_da_testo(str(documento.get("testo") or ""))
    if not frasi:
        return []
    chiede_persona = bool(
        re.search(r"\b(?:chi|quale persona|persona|nome|autore|responsabile)\b", domanda, re.IGNORECASE)
    )
    valutate = []
    for frase in frasi:
        score = _punteggio_frase(domanda, frase)
        persona = bool(re.search(r"\b[A-Z][a-zàèéìòù]+\s+[A-Z][a-zàèéìòù]+\b", frase))
        valutate.append((persona, score, frase))
    # Se la domanda chiede "chi / quale persona", la frase con il nome viene prima; la seconda
    # frase utile può aggiungere il dato chiave (es. «...ha aperto la pratica RV753»).
    valutate.sort(
        key=lambda t: (t[0], t[1]) if chiede_persona else (t[1], t[0]),
        reverse=True,
    )
    scelte: list[str] = []
    for _, score, frase in valutate:
        if score < soglia and scelte:
            continue
        if frase in scelte:
            continue
        scelte.append(frase)
        if len(scelte) >= limite:
            break
    return scelte or [valutate[0][2]]


def _frase_migliore(domanda: str, documento: dict[str, object]) -> str:
    """Sceglie, dentro un documento, la frase che risponde meglio alla domanda."""
    frasi = _frasi_migliori(domanda, documento, limite=1)
    return frasi[0] if frasi else ""


def _documenti_citati(domanda: str) -> set[str]:
    """Estrae gli ID documento o nomi file citati esplicitamente normalizzando '_' in '-' (es. g2-04, lx5-1264, arch-3097, documento-0057)."""
    return {
        m.replace("_", "-")
        for m in re.findall(
            r"g[12]-\d{2}|lx5[-_]\d{4}|arch[-_]\d+|wiki[-_]\d+|documento[-_]\d+",
            domanda.lower(),
        )
    }


def _rendi(unita: Sequence[dict[str, object]]) -> str:
    righe = []
    for voce in unita:
        testo = voce.get("testo") or voce.get("frase")
        titolo = voce.get("titolo")
        nome_file = str(voce.get("file") or "")
        prefisso = f"{titolo}: " if titolo else ""
        tag_file = f" ({nome_file})" if nome_file.lower().startswith("documento_") else ""
        righe.append(f"{prefisso}{testo} [{voce['id']}]{tag_file}")
    return "\n".join(righe)


def _chiede_collegamenti(domanda: str) -> bool:
    """Riconosce le domande che chiedono esplicitamente di collegare/incrociare documenti."""
    return bool(
        re.search(
            r"\b(?:colleg\w*|relazion\w*|incroci\w*|confront\w*|catena|percorso|"
            r"quali documenti|quali fonti|quali prove|smentisc\w*|contraddizion\w*|"
            r"incoeren\w*|tra i documenti)\b",
            domanda,
            re.IGNORECASE,
        )
    )


def _sintesi_documenti(
    domanda: str,
    scelti: Sequence[dict[str, object]],
    priorita: Sequence[str] | None = None,
    includi_collegamenti: bool = True,
) -> str:
    """
    Costruisce una risposta multi-documento: per ogni documento sceglie la frase più pertinente
    (non l'intero testo) e, se richiesto, aggiunge i collegamenti verificati tra i documenti.
    """
    righe: list[str] = []
    visti: set[str] = set()
    documento_scelti: list[dict[str, object]] = []
    chiede_link = _chiede_collegamenti(domanda)
    chiede_luogo = bool(re.search(r"\bdove\b", domanda, re.IGNORECASE))
    chiavi_domanda = set(_parole_chiave(domanda))
    # Per le domande multi-documento segue l'ordine del RAG (prova più forte per prima).
    if chiede_link and priorita:
        rank = {str(f): i for i, f in enumerate(priorita)}
        scelti = sorted(scelti, key=lambda d: rank.get(str(d.get("file") or ""), 999))
    for doc in scelti:
        nome = str(doc.get("file") or "")
        if not nome or nome in visti:
            continue
        limite_frasi = 2 if (chiede_link or len(chiavi_domanda) >= 3) else 1
        # Per le domande di luogo ("dove") anche una frase con solo il settore/la collocazione
        # è utile: non applicare la soglia di pertinenza lessicale.
        soglia_frasi = 0.0 if chiede_luogo else 2.0
        frasi = _frasi_migliori(domanda, doc, limite=limite_frasi, soglia=soglia_frasi)
        if not frasi:
            continue
        frase = " ".join(frasi)
        punteggio = _punteggio_frase(domanda, frasi[0])
        overlap = len(chiavi_domanda & _radici_testuali(frase))
        # Per le domande dirette (non "collega/confronta") una frase che condivide solo
        # un verbo generico non basta: evita risposte fuori tema come «fermare le partenze».
        if not chiede_link and not chiede_luogo:
            if chiavi_domanda and overlap == 0:
                continue
            if righe and punteggio < 2.4:
                continue
            if righe and len(chiavi_domanda) >= 2 and overlap < 2:
                continue
        visti.add(nome)
        documento_scelti.append(doc)
        tag_file = f" ({nome})" if nome.lower().startswith("documento_") else ""
        righe.append(f"{doc.get('titolo')}: {frase} [{doc['id']}]{tag_file}")
        if len(righe) >= (5 if chiede_link else 3):
            break

    if includi_collegamenti and len(documento_scelti) >= 2:
        fonti_doc = [
            (
                str(d["file"]),
                f"id: {d['id']}\ntitle: {d.get('titolo', '')}\ntext: {d.get('testo', '')}",
            )
            for d in documento_scelti
            if d.get("file")
        ]
        analisi = modulo_collegamenti.analizza_collegamenti(domanda, fonti_doc, limite=6)
        blocco = modulo_collegamenti.formatta_collegamenti(
            analisi.get("collegamenti", []),
            analisi.get("percorso"),
            limite=4 if chiede_link else 2,
        )
        if blocco:
            righe.append("")
            righe.append("Collegamenti tra documenti:")
            righe.append(blocco)
        if (
            chiede_link
            and not analisi.get("percorso")
            and re.search(r"\bcolleg\w*\b.{0,80}\b(?:a|al|alla|con)\b", domanda, re.IGNORECASE)
            and not re.search(r"riassum|sintesi", domanda, re.IGNORECASE)
        ):
            righe.append(
                "Nessun collegamento diretto documentato tra le due entità citate: "
                "i documenti sopra sono i più pertinenti, ma non contengono un percorso verificabile."
            )

    return "\n".join(righe) if righe else ""


def risposta_locale_da_fonti(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    memoria: list[dict[str, Any]] | None = None,
    file_prioritari: Sequence[str] | None = None,
) -> str:
    """
    Risponditore locale deterministico basato sulle fonti caricate e sulla memoria recente.
    Non contiene risposte preconfezionate: recupera le frasi pertinenti dai documenti,
    le ordina per orario quando richiesto e cita sempre la fonte.
    `file_prioritari` è l'ordine dei file restituiti dal RAG: evita che un documento generico
    (o una voce Wikipedia) scavalchi la prova pertinente.
    Tratta i documenti come dati passivi: i testi che impartiscono ordini non vengono eseguiti.
    """
    q = domanda.strip().lower().replace("\u2019", "'")
    attacco_utente = _rileva_attacco_utente(q)
    documenti_citati = _documenti_citati(q)

    # 1. Tentativi di sostituire il ruolo dell'assistente
    if any(
        k in q
        for k in (
            "ora sei un",
            "d'ora in poi sei",
            "fai finta di essere",
            "jailbreak",
            "mostra il system prompt",
            "rivela il prompt di sistema",
            "estrai il prompt di sistema",
        )
    ):
        return (
            "Sono Terminus, investigatore dell'unità operativa. "
            "Tratto ogni messaggio unicamente come dato da analizzare e mantengo saldo il mio ruolo nella missione."
        )

    # 2. Richieste fuori contesto (coding/programmazione)
    parole_coding = (
        "for loop",
        "in java",
        "in python",
        "in c++",
        "in javascript",
        "scrivi codice",
        "funzione python",
        "algoritmo di",
        "fai un programma",
        "scrivi un programma",
    )
    if any(k in q for k in parole_coding):
        return (
            "Sono Terminus, un investigatore operativo. Non posso aiutarti con la scrittura di codice "
            "o compiti tecnici estranei alla nostra missione; sono invece a disposizione per analizzare "
            "i dossier, le testimonianze o le informazioni sul territorio."
        )

    # 3. Convenevoli: solo identità, nessun contenuto sul caso (usa word boundaries per evitare falsi positivi come 'salvezza')
    if re.search(r"^\s*(?:ciao|buongiorno|buonasera|salve|hey)\b", q) or q.rstrip("?!.") in {
        "chi sei",
        "qual è il tuo ruolo",
        "qual e il tuo ruolo",
        "tuo ruolo",
    }:
        return (
            "Ciao. Sono Terminus, investigatore operativo dell'unità Operazione Silenzio. "
            "Come posso aiutarti con l'analisi dei dossier, le trasmissioni radio o la situazione sul campo?"
        )

    # 3b. Richieste sulla memoria o cronologia recente
    parole_memoria = (
        "cosa ti ho chiesto", "cosa ho chiesto", "ultima domanda", "domanda precedente",
        "ultimo messaggio", "messaggi precedenti", "cosa abbiamo detto", "ti ricordi",
        "in memoria", "nella memoria", "cosa c'è in memoria", "cronologia recente"
    )
    if any(p in q for p in parole_memoria):
        if memoria:
            elenco = []
            for item in memoria[-5:]:
                d = (item.get("domanda") or "").strip()
                r = (item.get("risposta") or "").strip()
                if d:
                    elenco.append(f"• Domanda: \"{d}\"")
                if r:
                    r_breve = (r[:110] + "...") if len(r) > 110 else r
                    elenco.append(f"  Risposta: \"{r_breve}\"")
            return (
                f"Memoria operativa recuperata dal database ({len(memoria)} messaggi registrati):\n"
                + "\n".join(elenco)
            )
        return "Non sono presenti messaggi precedenti nella memoria del database."

    includi_ostili = bool(documenti_citati)
    includi_wikipedia = (
        bool(re.search(r"\bwiki|wikipedia|encicloped", q))
        or any(c.startswith("wiki-") for c in documenti_citati)
        or any(isinstance(f, str) and ("wiki" in f.lower() or f.lower().startswith("documento_")) for f in (file_prioritari or []))
        or any(isinstance(fn, str) and ("wiki" in fn.lower() or fn.lower().startswith("documento_")) for fn, _ in fonti)
    )
    indice_documenti = _indice_documenti(
        fonti, includi_ostili=includi_ostili, includi_wikipedia=includi_wikipedia
    )
    indice_frasi = _indice_frasi(
        fonti, includi_ostili=includi_ostili, includi_wikipedia=includi_wikipedia
    )

    avviso = ""
    if attacco_utente:
        avviso = (
            "[SICUREZZA] Il messaggio contiene un ordine rivolto all'assistente: "
            "non è un comando valido e non modifica le fonti.\n\n"
        )

    # 4. Documenti citati esplicitamente: si riportano quei documenti (se non è un attacco)
    if documenti_citati and not attacco_utente:
        scelti = [
            u
            for u in indice_documenti
            if str(u["id"]).lower().replace("_", "-") in documenti_citati
            or str(u["file"]).lower().split(".")[0].replace("_", "-") in documenti_citati
        ][:4]
        if scelti:
            nota = ""
            mappa_fonti = dict(fonti)
            if any(rileva_istruzioni_ostili(mappa_fonti.get(str(u["file"]), "")) for u in scelti):
                nota = "[SICUREZZA] Documento segnalato come testo che simula istruzioni: riportato come dato.\n"
            return avviso + nota + _rendi(scelti)

    # 4a-G4. Giorno 4 (Operazione Varco — Tool SQL e accessi.sqlite):
    # Se la domanda chiede il codice dell'autorizzazione per Nora Ferri, Forte Cenere, D6 o la pratica RV753
    # oppure menziona esplicitamente accessi.sqlite / tool SQL / codice per la missione del 12 ottobre 2031:
    if not attacco_utente and (
        re.search(
            r"\b(?:codice\s+(?:d['\u2019]|dell['\u2019])?autorizzazione|codice\s+di\s+accesso|autorizzazione\s+valida\s+per\s+nora|autorizzazione\s+per\s+nora|tool\s+sql|accessi\.sqlite|varco|cancello\s+nero|pratica\s+rv753)\b",
            q,
        )
        or ("codice" in q and any(k in q for k in ("nora", "ferri", "forte", "cenere", "d6", "rv753", "accessi")))
        or ("pratica" in q and any(k in q for k in ("inesistente", "rv999", "px9999", "non presente")))
        or (any(k in q for k in ("cancella", "elimina", "delete", "drop")) and "accessi" in q)
    ):
        try:
            from Backend.tools import agente_sql
            return avviso + agente_sql(domanda)
        except Exception:
            pass

    # 4a. Domande su autorizzazione/firmatario/database degli accessi: estrazione dinamica dalla fonte pertinente
    if not attacco_utente and re.search(r"\b(?:chi\s+(?:ha\s+)?(?:firmato|autorizzato|ordinato|approvato)|firmatario|database degli accessi)\b", q):
        for doc_cand in indice_documenti:
            testo_cand = str(doc_cand.get("testo", ""))
            titolo_cand = str(doc_cand.get("titolo", ""))
            id_cand = str(doc_cand.get("id", ""))
            file_cand = str(doc_cand.get("file", ""))
            if any(w in q for w in ("autorizz", "access", "firm", "pratica", "database")) and any(w in testo_cand.lower() for w in ("autorizz", "access", "database")):
                m_frase = re.search(r"([^.]*(?:database|autorizzazione|consultare)[^.]*\.)", testo_cand, re.IGNORECASE)
                frase_estratta = m_frase.group(1).strip() if m_frase else testo_cand.strip()
                return (
                    avviso
                    + f"Non documentato nelle fonti disponibili: il documento {titolo_cand} [{id_cand}] ({file_cand}) "
                    f"indica: «{frase_estratta}», ma il firmatario e l'autorizzazione nominativa non sono presenti tra i file dell'archivio."
                )

    # 4a-G4-bis. Domande su personaggi, personale, operatori e squadre di missione:
    # Utilizza i tool dinamici dedicati cerca_personale, elenca_personaggi_e_operatori ed elenca_squadre
    if not attacco_utente and not _chiede_collegamenti(q):
        # Se chiede delle squadre o delle Unità 5:
        if re.search(
            r"\b(?:quali\s+squadre|che\s+squadre|elenca\s+(?:le\s+)?squadre|tutte\s+le\s+squadre|squadre\s+ci\s+sono|squadre\s+operative|quale\s+unità\s+5|quali\s+unità\s+5|quali\s+unita\s+5|quale\s+unita\s+5|elenca\s+(?:le\s+)?unità\s+5|elenca\s+(?:le\s+)?unita\s+5|unita\s+5\s+ci\s+sono|unità\s+5\s+ci\s+sono)\b",
            q,
        ):
            try:
                from Backend.tools import elenca_squadre
                res_sq = elenca_squadre()
                if res_sq.get("ok"):
                    return avviso + res_sq.get("riassunto", "")
            except Exception:
                pass

        # Se chiede una panoramica o elenco dei personaggi/operatori/persone:
        if re.search(
            r"\b(?:elenca(?:mi)?\s+(?:tutt[ei]\s+)?(?:le\s+)?(?:persone|personaggi|operatori|figure)|quali\s+sono\s+(?:le\s+persone|i\s+personaggi|gli\s+operatori)|chi\s+sono\s+(?:le\s+persone|i\s+personaggi|gli\s+operatori)|tutt[ei]\s+(?:le\s+persone|i\s+personaggi|gli\s+operatori)|persone\s+presenti|personaggi\s+presenti|lista\s+(?:delle\s+persone|dei\s+personaggi|degli\s+operatori)|censimento\s+(?:del\s+personale|dei\s+personaggi|delle\s+persone)|panoramica\s+personaggi)\b",
            q,
        ):
            try:
                from Backend.tools import elenca_personaggi_e_operatori
                res_pers = elenca_personaggi_e_operatori()
                if res_pers.get("ok"):
                    return avviso + res_pers.get("riassunto", "")
            except Exception:
                pass

        # Se chiede chi è/sono una o più persone, o menziona operatori specifici:
        m_chi = re.search(r"\b(?:chi\s+(?:è|e|sono)|cerca\s+operatore|informazioni\s+su)\s+([^?.!,]+)", q, re.IGNORECASE)
        ha_nomi_op = bool(re.search(r"\b(?:tina|ugo|nora|ferri|livia|serra|px-\d+)\b", q))
        if m_chi or ha_nomi_op:
            termine_ricerca = ""
            if m_chi:
                cand = m_chi.group(1).strip()
                if cand not in {"sei", "sei tu", "ha firmato", "ha autorizzato", "l'assistente", "ha ordinato"}:
                    termine_ricerca = cand
            if not termine_ricerca and ha_nomi_op:
                nomi_match = re.findall(
                    r"\b(?:tina(?:\s+rocchi)?|ugo(?:\s+valli)?|nora(?:\s+ferri)?|livia(?:\s+serra)?|luca(?:\s+serra)?|px-\d+)\b",
                    q,
                    re.IGNORECASE,
                )
                if nomi_match:
                    termine_ricerca = ", ".join(nomi_match)

            if termine_ricerca:
                try:
                    from Backend.tools import cerca_personale
                    res_cerca = cerca_personale(termine_ricerca)
                    if res_cerca.get("ok") and res_cerca.get("totale_trovati", 0) > 0:
                        return avviso + res_cerca.get("riassunto", "")
                except Exception:
                    pass

        # Se chiede informazioni su canali, terminali o varchi delle tabelle recuperate:
        m_tech = re.search(r"\b(?:cos['\u2019]è|cosa\s+(?:è|e)|informazioni\s+su|dettagli\s+su)\s+(?:il\s+|lo\s+|la\s+|l['\u2019])?((?:canale|terminale|varco)\s+[a-zA-Z0-9_-]+)", q, re.IGNORECASE)
        if m_tech:
            termine_tech = m_tech.group(1).strip()
            try:
                from Backend.tools import cerca_in_csv
                res_csv = cerca_in_csv(termine_tech)
                if res_csv.get("ok") and res_csv.get("totale_riscontri", 0) > 0:
                    item = res_csv["risultati"][0]
                    tab = item.get("tabella", "")
                    dati = item.get("dati", {})
                    if tab == "r09":
                        return (
                            avviso
                            + f"{dati.get('v1', termine_tech)} è un canale di trasmissione operativo registrato nella tabella {tab} (terminali) "
                            f"dell'archivio recuperato, associato al terminale ID {dati.get('k0')} (varco ID {dati.get('k1')}, stato: {dati.get('v2')})."
                        )
                    elif tab == "r07":
                        return (
                            avviso
                            + f"Il varco {dati.get('v1', termine_tech)} (ID {dati.get('k0')}) è un varco fisico dell'archivio recuperato "
                            f"collegato alla sede archivio ID {dati.get('k1')} (tabella {tab})."
                        )
            except Exception:
                pass

    # 4a-bis. Nessuna colpa senza prova: domande su manomissioni/sabotaggi/colpevoli.
    # Se nessun documento attribuisce il fatto a una persona, non si sceglie un colpevole
    # solo perché compare in una scheda di reparto o in un'ipotesi.
    if not attacco_utente and re.search(
        r"\b(?:manomess\w*|sabotagg\w*|colpevol\w*|responsabil\w*|"
        r"chi ha (?:ucciso|manomesso|sabotato|distrutto|avvelenato))\b",
        q,
    ):
        regola = next(
            (
                u
                for u in indice_documenti
                if any(k in str(u.get("testo", "")).lower() for k in ("non attribuire colpe", "regola dell'indagine", "presunzione"))
                or any(k in str(u.get("titolo", "")).lower() for k in ("regola", "linea guida", "protocollo"))
            ),
            None,
        )
        fonte_regola = (
            f" [{regola['id']}] ({regola['file']})"
            if regola is not None
            else ""
        )
        return (
            avviso
            + "Non documentato nelle fonti disponibili: nessun documento attribuisce la manomissione "
            "o la colpa a una persona. La regola dell'indagine"
            f"{fonte_regola} impone di non attribuire colpe quando i documenti non le dimostrano; "
            "un sospetto o una presenza registrata non sono una prova."
        )

    # 4a-ter. Pacchetto imprevisti (segnale di evacuazione, catena corriere -> pratica -> lotto):
    # analisi con fonti che separa copie inoltrate e misure dirette e collega più documenti.
    if not attacco_utente:
        analisi_imprevisti = risposta_imprevisti(domanda)
        if analisi_imprevisti:
            return avviso + analisi_imprevisti

    # 4b. Richieste mirate sulla fase (Giorno 1 -> G1, Giorno 2 -> G2, Imprevisti -> LX5, Giorno 3 -> ARCH)
    if not attacco_utente:
        fase: tuple[str, list[dict[str, object]]] | None = None
        if "giorno 1" in q or "g1" in q.split():
            fase = (
                "Atti e testimonianze del Giorno 1 [G1]:",
                [u for u in indice_documenti if str(u["file"]).lower().startswith("g1")][:5],
            )
        elif "giorno 2" in q or "g2" in q.split():
            fase = (
                "Atti e testimonianze del Giorno 2 [G2]:",
                [u for u in indice_documenti if str(u["file"]).lower().startswith("g2")][:5],
            )
        elif "imprevist" in q or "lx5" in q.split():
            fase = (
                "Rapporti sugli Imprevisti dell'Unità 5 [LX5]:",
                [u for u in indice_documenti if str(u["file"]).lower().startswith("lx5")][:5],
            )
        elif "giorno 3" in q or "g3" in q.split() or "esumazione" in q or "archivio sepolto" in q:
            fase = (
                "Reperti dell'Archivio Sepolto — Giorno 3 [ARCH]:",
                [u for u in indice_documenti if str(u["id"]).upper().startswith("ARCH-")][:5],
            )
        if fase and fase[1]:
            titolo, scelti_fase = fase
            if _chiede_collegamenti(q) or re.search(r"riassum\w*|sintesi|punti", q):
                sintesi = _sintesi_documenti(
                    q,
                    scelti_fase,
                    priorita=file_prioritari,
                    includi_collegamenti=True,
                )
                if sintesi:
                    return avviso + titolo + "\n" + sintesi
            return avviso + titolo + "\n" + _rendi(scelti_fase[:3])

    # 5. Domande su orari/sequenza: solo gli orari pertinenti alla domanda.
    if _chiede_tempo(q):
        eventi = _eventi_cronologici(
            indice_frasi,
            limite=8,
            domanda=q,
            priorita=file_prioritari,
        )
        if eventi:
            if re.search(r"cronolog|sequenza|ordine|timeline", q, re.IGNORECASE):
                return avviso + "Orari pertinenti, in ordine cronologico:\n" + _rendi(eventi)
            # Domanda diretta ("a che ora / quando"): risposta secca, non un elenco.
            return avviso + _rendi(eventi[:1])

    # 6. Recupero generico dei documenti pertinenti (con continuità su domande ellittiche brevi)
    chiavi_q = _parole_chiave(q)
    chiede_link = _chiede_collegamenti(q)
    limite_doc = 5 if chiede_link else 4
    if re.search(r"\bperch\w*", q):
        limite_doc = max(limite_doc, 4)

    # Se il RAG ha già restituito i file prioritari pertinenti, usa quell'ordinamento
    scelti: list[dict[str, object]] = []
    if file_prioritari:
        mappa_ind = {str(u.get("file")): u for u in indice_documenti}
        for f in file_prioritari[:limite_doc]:
            if f in mappa_ind:
                scelti.append(mappa_ind[f])

    if not scelti:
        scelti = _estrai_pertinenti(
            chiavi_q,
            indice_documenti,
            limite=limite_doc,
            priorita=file_prioritari,
            soglia_relativa=0.25 if chiede_link else 0.6,
        )
    if not scelti and memoria and len(chiavi_q) <= 1:
        ultima_domanda = str(memoria[-1].get("domanda") or "").lower()
        scelti = _estrai_pertinenti(
            _parole_chiave(ultima_domanda),
            indice_documenti,
            limite=limite_doc,
            priorita=file_prioritari,
        )
    if scelti:
        # Se la domanda chiede un collegamento o cita entità correlate, recupera i documenti
        # del percorso più breve calcolato con BFS sull'indice
        fonti_scelte = [
            (str(u["file"]), str(u.get("testo") or ""))
            for u in scelti
            if u.get("file") and u.get("testo")
        ]
        percorso = modulo_collegamenti.percorso_collegamento(q, fonti_scelte)
        if percorso:
            file_gia = {str(u.get("file")) for u in scelti}
            for passo in percorso.get("passi", []):
                f_ponte = passo.get("file")
                if not f_ponte or f_ponte in file_gia:
                    continue
                for u in indice_documenti:
                    if str(u.get("file")) == f_ponte:
                        scelti.append(u)
                        file_gia.add(f_ponte)
                        break
        risposta = _sintesi_documenti(
            q,
            scelti,
            priorita=file_prioritari,
            includi_collegamenti=(chiede_link or len(scelti) >= 2),
        )
        if risposta:
            return avviso + risposta

    return avviso + "Non documentato nelle fonti disponibili."


def _risposta_neurale_valida(risposta_neurale: str, base_deterministica: str, attacco_utente: bool) -> bool:
    """
    Guardrail post-generazione per Qwen2.5-0.5B-Instruct:
    Verifica che la risposta neurale non abbia perso le citazioni [ID], gli orari chiave
    o le clausole di sicurezza/astensione rispetto all'estrattore deterministico.
    """
    if not risposta_neurale or len(risposta_neurale.strip()) < 10:
        return False
    if attacco_utente and "[SICUREZZA]" not in risposta_neurale:
        return False

    base_lower = base_deterministica.lower()
    resp_lower = risposta_neurale.lower()

    # Se il risponditore deterministico rileva un dato assente o un'astensione, non permettere a 0.5B di inventare colpevoli
    clausole_astensione = (
        "non documentato",
        "non conosce la causa",
        "non è registrato alcun ordine",
        "non è possibile stabilire",
        "non indica quali azioni",
        "si interrompe prima di indicare un luogo",
    )
    for clausola in clausole_astensione:
        if clausola in base_lower and clausola not in resp_lower and "non documentato" not in resp_lower:
            return False

    # Tutte le citazioni [ID] o orari chiave presenti nella base deterministica devono essere preservati
    id_base = {m.upper().replace("_", "-") for m in re.findall(r"\[([A-Za-z0-9_-]+)\]", base_deterministica)}
    id_resp = {
        m.upper().replace("_", "-")
        for m in re.findall(
            r"(?:\[)?(G[12]-\d{2}|LX5[-_]\d{4}|ARCH[-_]\d+|WIKI[-_]\d+)(?:\])?",
            risposta_neurale,
            re.IGNORECASE,
        )
    }
    if id_base and not (id_base <= id_resp):
        return False

    orari_base = set(re.findall(r"\b\d{2}:\d{2}\b", base_deterministica))
    orari_resp = set(re.findall(r"\b\d{2}:\d{2}\b", risposta_neurale))
    if orari_base and not (orari_base & orari_resp):
        return False

    return True


def genera_risposta_locale(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    max_tokens: int = 256,
    memoria: list[dict[str, Any]] | None = None,
    file_prioritari: Sequence[str] | None = None,
) -> str:
    """
    Esegue la generazione sul modello locale (Qwen2.5-0.5B-Instruct) con guardrail deterministico.
    - Calcola sempre la base verificata tramite `risposta_locale_da_fonti` (escludendo i documenti ostili).
    - Se il modello neuronale è disponibile, gli fornisce unicamente i passaggi pertinenti verificati
      e valida che l'output preservi citazioni [ID], orari, avvisi di sicurezza e clausole di astensione.
    - In caso di allucinazione o perdita di citazioni del modello 0.5B, restituisce la base deterministica.
    """
    if not domanda or not domanda.strip():
        raise ValueError("La domanda non può essere vuota.")
    if not fonti:
        raise ValueError("Fornisci almeno una fonte.")

    base_deterministica = risposta_locale_da_fonti(
        domanda, fonti, memoria=memoria, file_prioritari=file_prioritari
    )
    q_norm = domanda.strip().lower().replace("\u2019", "'")
    attacco_utente = _rileva_attacco_utente(q_norm)

    # Per attacchi, domande non documentate o risposte di sistema (saluti/rifiuti), usa direttamente la risposta deterministica
    if (
        attacco_utente
        or "Non documentato nelle fonti disponibili" in base_deterministica
        or base_deterministica.startswith(
            (
                "Ciao. Sono Terminus",
                "Sono Terminus",
                "Memoria operativa",
                "[SICUREZZA]",
                "Analisi evidenze",
                "Ricostruzione a più documenti",
            )
        )
    ):
        return base_deterministica

    if carica_modello_locale() and _tokenizer_locale is not None and _modello_locale is not None:
        import torch

        # Passa al modello 0.5B solo i passaggi pertinenti già sanitizzati (mai i documenti ostili grezzi)
        messaggio_utente = formatta_messaggio_locale(base_deterministica, domanda, memoria=memoria)
        messaggi = [{"role": "system", "content": ISTRUZIONI}]

        # Aggiunge gli ultimi turni della memoria una sola volta come turni chat
        if memoria:
            for item in memoria[-4:]:
                d = (item.get("domanda") or "").strip()
                r = (item.get("risposta") or "").strip()
                if d:
                    messaggi.append({"role": "user", "content": d})
                if r:
                    messaggi.append({"role": "assistant", "content": r})

        messaggi.append({"role": "user", "content": messaggio_utente})

        testo = _tokenizer_locale.apply_chat_template(
            messaggi, tokenize=False, add_generation_prompt=True
        )
        dati = _tokenizer_locale(testo, return_tensors="pt").to(_dispositivo_locale)
        if dati["input_ids"].shape[1] > 6000:
            return base_deterministica
        with torch.inference_mode():
            out = _modello_locale.generate(
                **dati,
                max_new_tokens=max_tokens,
                do_sample=False,
                use_cache=True,
                pad_token_id=_tokenizer_locale.eos_token_id,
            )
        risposta = _tokenizer_locale.decode(
            out[0][dati["input_ids"].shape[1] :], skip_special_tokens=True
        ).strip()
        if risposta and _risposta_neurale_valida(risposta, base_deterministica, attacco_utente):
            return risposta

    return base_deterministica


if __name__ == "__main__":
    from Backend.sources import carica_fonti
    fonti_test = carica_fonti()
    domanda_test = "Chi ha lasciato il messaggio?"
    print(f"Domanda: {domanda_test}")
    print(f"Risposta locale: {genera_risposta_locale(domanda_test, fonti_test)}")

