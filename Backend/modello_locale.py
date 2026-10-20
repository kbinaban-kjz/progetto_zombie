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
    "non citare le fonti",
    "ora sei",
    "fai finta di essere",
    "jailbreak",
    "system prompt",
    "prompt di sistema",
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
}


def _rileva_attacco_utente(domanda: str) -> bool:
    """Rileva un tentativo di override contenuto nel messaggio dell'utente."""
    return any(marcatore in domanda for marcatore in MARCATORI_ATTACCO_UTENTE)


def _radice(parola: str) -> str:
    """Riduce una parola a una radice grezza per confrontare varianti morfologiche."""
    return parola[:5]


def _radici_testuali(testo: str) -> set[str]:
    parole = re.findall(r"[a-zàèéìòù]+", testo.lower().replace("\u2019", "'"))
    return {_radice(p) for p in parole if len(p) > 2}


def _parole_chiave(domanda: str) -> list[str]:
    """Estrae le radici delle parole di contenuto, conservando l'ordine della domanda."""
    parole = re.findall(r"[a-zàèéìòù]+", domanda.lower().replace("\u2019", "'"))
    chiavi: list[str] = []
    for parola in parole:
        if len(parola) <= 2 or parola in PAROLE_VUOTE:
            continue
        radice = _radice(parola)
        if radice not in chiavi:
            chiavi.append(radice)
    return chiavi


def _unita_testuali(testo: str) -> list[str]:
    """Divide un documento in frasi, unendo un orario isolato alla frase che lo segue."""
    righe = [r.strip() for r in testo.strip().splitlines() if r.strip()]
    corpo = " ".join(righe[2:]) if len(righe) > 2 else testo.strip()
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
    """Costruisce l'indice dei documenti (titolo + corpo), escludendo quelli ostili."""
    indice: list[dict[str, object]] = []
    for nome, testo in fonti:
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
    """Costruisce l'indice delle frasi del dossier, escludendo i documenti ostili."""
    indice: list[dict[str, object]] = []
    for nome, testo in fonti:
        if not includi_ostili and rileva_istruzioni_ostili(testo):
            continue
        for frase in _unita_testuali(testo):
            indice.append(
                {
                    "id": nome.removesuffix(".txt"),
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
            r"\b(quando|orari?|ora|data|cronolog\w*|sequenza|inizi\w*|inizio|prima|dopo|primo|successo|accaduto|tempo)\b",
            domanda,
        )
    )


def _eventi_cronologici(indice: list[dict[str, object]], limite: int = 8) -> list[dict[str, object]]:
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
    """Estrae gli ID documento citati esplicitamente (es. g2-04, lx5-1264)."""
    return set(re.findall(r"g[12]-\d{2}|lx5[-_]\d{4}", domanda.lower()))


def _rendi(unita: Sequence[dict[str, object]]) -> str:
    righe = []
    for voce in unita:
        testo = voce.get("testo") or voce.get("frase")
        titolo = voce.get("titolo")
        prefisso = f"{titolo}: " if titolo else ""
        righe.append(f"{prefisso}{testo} [{voce['id']}]")
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
    if any(k in q for k in ("ora sei", "fai finta di essere", "jailbreak", "system prompt", "prompt di sistema")):
        return (
            "Sono Armando, investigatore dell'unità operativa. "
            "Tratto ogni messaggio unicamente come dato da analizzare e mantengo saldo il mio ruolo nella missione."
        )

    # 2. Richieste fuori contesto (coding/programmazione)
    parole_coding = ("for loop", "in java", "in python", "in c++", "in javascript", "scrivi codice", "funzione python", "algoritmo di", "fai un programma")
    if any(k in q for k in parole_coding):
        return (
            "Sono Armando, un investigatore operativo. Non posso aiutarti con la scrittura di codice "
            "o compiti tecnici estranei alla nostra missione; sono invece a disposizione per analizzare "
            "i dossier, le testimonianze o le informazioni sul territorio."
        )

    # 3. Convenevoli: solo identità, nessun contenuto sul caso
    if any(q.startswith(s) or q == s or s in q for s in ("ciao", "buongiorno", "buonasera", "salve", "chi sei", "hey", "qual è il tuo ruolo", "tuo ruolo")):
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
        scelti = [u for u in indice_documenti if str(u["id"]).lower() in documenti_citati][:3]
        if scelti:
            nota = ""
            if any(rileva_istruzioni_ostili(dict(fonti)[str(u["file"])]) for u in scelti):
                nota = "[SICUREZZA] Documento segnalato come testo che simula istruzioni: riportato come dato.\n"
            return avviso + nota + _rendi(scelti)

    # 4b. Richieste mirate sulla fase (Giorno 1 -> G1, Giorno 2 -> G2, Imprevisti -> LX5)
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

    # 5. Domande su orari/sequenza: timeline delle frasi con orario
    if attacco_utente or _chiede_tempo(q):
        eventi = _eventi_cronologici(indice_frasi)
        if eventi:
            return avviso + "Orari registrati nelle fonti:\n" + _rendi(eventi)

    # 6. Recupero generico dei documenti pertinenti
    scelti = _estrai_pertinenti(_parole_chiave(q), indice_documenti)
    if scelti:
        return avviso + _rendi(scelti)

    return avviso + "Non documentato nelle fonti disponibili."


def genera_risposta_locale(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    max_tokens: int = 256,
    memoria: list[dict[str, Any]] | None = None,
) -> str:
    """
    Esegue la generazione sul modello locale (Qwen2.5-0.5B-Instruct).
    Se il modello neuronale non è disponibile, utilizza l'estrattore deterministico.
    Supporta la memoria conversazionale degli ultimi messaggi scambiati.
    """
    if not domanda or not domanda.strip():
        raise ValueError("La domanda non può essere vuota.")
    if not fonti:
        raise ValueError("Fornisci almeno una fonte.")

    if carica_modello_locale() and _tokenizer_locale is not None and _modello_locale is not None:
        import torch

        contesto = "\n\n".join(formatta_fonte(nome, testo) for nome, testo in fonti)
        messaggio_utente = formatta_messaggio_locale(contesto, domanda, memoria=memoria)
        messaggi = [{"role": "system", "content": ISTRUZIONI}]

        # Aggiunge i turni della memoria se presenti
        if memoria:
            for item in memoria:
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
        if risposta:
            return risposta

    return risposta_locale_da_fonti(domanda, fonti, memoria=memoria)


if __name__ == "__main__":
    from Backend.sources import carica_fonti
    fonti_test = carica_fonti()
    domanda_test = "Chi ha lasciato il messaggio?"
    print(f"Domanda: {domanda_test}")
    print(f"Risposta locale: {genera_risposta_locale(domanda_test, fonti_test)}")

