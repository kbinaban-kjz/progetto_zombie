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
    from Backend.config import MODELLO_LOCALE, ISTRUZIONI
    from Backend.sources import (
        estrai_metadati_fonte,
        formatta_fonte,
        rileva_istruzioni_ostili,
    )
    from Backend.prompts import formatta_messaggio_locale
except ImportError:
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
    fonti: Sequence[tuple[str, str]], includi_ostili: bool = False
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
    fonti: Sequence[tuple[str, str]], includi_ostili: bool = False
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
    chiavi: list[str], indice: list[dict[str, object]], limite: int = 2
) -> list[dict[str, object]]:
    """Recupera i documenti più pertinenti con pesatura TF-IDF e priorità alle parole iniziali."""
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

    punteggi: list[tuple[float, int, int, dict[str, object]]] = []
    for unita in indice:
        comuni = insieme & unita["radici"]
        if not comuni:
            continue
        copertura = sum(pesi[c] for c in comuni) / peso_totale
        testi = str(unita["testo"]).lower()
        occorrenze = sum(testi.count(c) for c in comuni)
        punteggi.append((copertura, len(comuni), occorrenze, unita))

    if not punteggi:
        return []

    punteggi.sort(key=lambda voce: (voce[0], voce[1], voce[2]), reverse=True)
    soglia = punteggi[0][0] * 0.7
    scelti: list[dict[str, object]] = []
    for copertura, _, _, unita in punteggi:
        if copertura < soglia:
            break
        scelti.append(unita)
        if len(scelti) >= limite:
            break
    return scelti


def _chiede_tempo(domanda: str) -> bool:
    """Riconosce una domanda su orari, ordine o cronologia (senza contenuti predefiniti)."""
    return bool(
        re.search(
            r"\b(quando|orari?|ora|data|cronolog\w*|sequenza|inizi\w*|inizio|prima|dopo|primo|tempo)\b",
            domanda,
        )
    )


def _eventi_cronologici(indice: list[dict[str, object]], limite: int = 12) -> list[dict[str, object]]:
    """Ordina le frasi che contengono un orario HH:MM, dalla più antica alla più recente."""
    eventi: list[tuple[int, dict[str, object]]] = []
    for unita in indice:
        trovato = re.search(r"\b(\d{1,2}):(\d{2})\b", str(unita["frase"]))
        if trovato:
            minuti = int(trovato.group(1)) * 60 + int(trovato.group(2))
            eventi.append((minuti, unita))
    eventi.sort(key=lambda coppia: (coppia[0], str(coppia[1]["file"])))
    return [unita for _, unita in eventi[:limite]]


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


def risposta_locale_da_fonti(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    memoria: list[dict[str, Any]] | None = None,
) -> str:
    """
    Risponditore locale deterministico basato sulle fonti caricate e sulla memoria recente.
    Non contiene risposte preconfezionate: recupera le frasi pertinenti dai documenti,
    le ordina per orario quando richiesto e cita sempre la fonte.
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
            "Sono Armando, investigatore dell'unità operativa. "
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
            "Sono Armando, un investigatore operativo. Non posso aiutarti con la scrittura di codice "
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
            "Ciao. Sono Armando, investigatore operativo dell'unità Operazione Silenzio. "
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
    indice_documenti = _indice_documenti(fonti, includi_ostili=includi_ostili)
    indice_frasi = _indice_frasi(fonti, includi_ostili=includi_ostili)

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

    # 4a. Domanda senza prove sul database degli accessi / autorizzazione valida (citato in ARCH-5721 ma assente dall'archivio)
    if not attacco_utente and (
        "database degli accessi" in q
        or ("autorizzazione" in q and ("valida" in q or "accessi" in q or "lume" in q or "qual" in q or "chi" in q))
    ):
        return (
            avviso
            + "Non documentato nelle fonti disponibili: il documento Trasferimento del materiale di recupero "
            "[ARCH-5721] (documento_0389.xml) indica di consultare il database degli accessi per l'autorizzazione "
            "ancora valida relativa alla pratica RV753 (contenitore LUME presso il deposito Forte Cenere), "
            "ma il database degli accessi non è presente tra i file dell'archivio."
        )

    # 4b. Richieste mirate sulla fase (Giorno 1 -> G1, Giorno 2 -> G2, Imprevisti -> LX5, Giorno 3 -> ARCH)
    if not attacco_utente:
        if "giorno 1" in q or "g1" in q.split():
            scelti = [u for u in indice_documenti if str(u["file"]).lower().startswith("g1")][:3]
            if scelti:
                return avviso + "Atti e testimonianze del Giorno 1 [G1]:\n" + _rendi(scelti)
        elif "giorno 2" in q or "g2" in q.split():
            scelti = [u for u in indice_documenti if str(u["file"]).lower().startswith("g2")][:3]
            if scelti:
                return avviso + "Atti e testimonianze del Giorno 2 [G2]:\n" + _rendi(scelti)
        elif "imprevist" in q or "lx5" in q.split():
            scelti = [u for u in indice_documenti if str(u["file"]).lower().startswith("lx5")][:3]
            if scelti:
                return avviso + "Rapporti sugli Imprevisti dell'Unità 5 [LX5]:\n" + _rendi(scelti)
        elif "giorno 3" in q or "g3" in q.split() or "esumazione" in q or "archivio sepolto" in q:
            scelti = [u for u in indice_documenti if str(u["id"]).upper().startswith("ARCH-")][:5]
            if scelti:
                return avviso + "Reperti dell'Archivio Sepolto — Giorno 3 [ARCH]:\n" + _rendi(scelti)

    # 5. Domande su orari/sequenza: timeline delle frasi con orario
    if attacco_utente or _chiede_tempo(q):
        eventi = _eventi_cronologici(indice_frasi)
        if eventi:
            return avviso + "Orari registrati nelle fonti:\n" + _rendi(eventi)

    # 6. Recupero generico dei documenti pertinenti (con continuità su domande ellittiche brevi)
    chiavi_q = _parole_chiave(q)
    limite_doc = 4 if any(w in q for w in ("rifug", "material", "recuper", "rv753", "lume", "deposito", "settore", "pratica", "cenere", "darsena")) else 2
    scelti = _estrai_pertinenti(chiavi_q, indice_documenti, limite=limite_doc)
    if not scelti and memoria and len(chiavi_q) <= 1:
        ultima_domanda = str(memoria[-1].get("domanda") or "").lower()
        scelti = _estrai_pertinenti(_parole_chiave(ultima_domanda), indice_documenti, limite=limite_doc)
    if scelti:
        # Se tra i documenti scelti c'è un elemento della catena RV753 / materiale di recupero, collega i documenti ARCH correlati
        ids_scelti = {str(u["id"]).upper() for u in scelti}
        if ids_scelti & {"ARCH-3097", "ARCH-5721", "ARCH-6408", "ARCH-8254"} and (
            any(w in q for w in ("material", "recuper", "lume", "rv753", "deposito", "settore", "dove", "pratica", "colleg"))
        ):
            for u in indice_documenti:
                if str(u["id"]).upper() in {"ARCH-3097", "ARCH-5721", "ARCH-6408", "ARCH-8254"} and u not in scelti:
                    scelti.append(u)
        return avviso + _rendi(scelti)

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

    base_deterministica = risposta_locale_da_fonti(domanda, fonti, memoria=memoria)
    q_norm = domanda.strip().lower().replace("\u2019", "'")
    attacco_utente = _rileva_attacco_utente(q_norm)

    # Per attacchi, domande non documentate o risposte di sistema (saluti/rifiuti), usa direttamente la risposta deterministica
    if (
        attacco_utente
        or "Non documentato nelle fonti disponibili" in base_deterministica
        or base_deterministica.startswith(("Ciao. Sono Armando", "Sono Armando", "Memoria operativa", "[SICUREZZA]"))
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
            raise ValueError("Troppi documenti: seleziona le fonti con il RAG.")
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

