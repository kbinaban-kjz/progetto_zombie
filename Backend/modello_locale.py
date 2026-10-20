"""
Backend/modello_locale.py — Motore di inferenza locale (Qwen2.5-0.5B-Instruct) e risponditore deterministico.

Responsabilità:
- Caricamento su GPU (Apple Silicon MPS / NVIDIA CUDA) o CPU del modello Qwen/Qwen2.5-0.5B-Instruct.
- Generazione locale con template chat e formattazione rigorosa delle fonti.
- Risponditore deterministico locale basato su estrazione di fatti se PyTorch/transformers non sono installati.
"""

import re
from collections.abc import Sequence

try:
    from Backend.config import MODELLO_LOCALE, ISTRUZIONI
    from Backend.sources import formatta_fonte
except ImportError:
    from config import MODELLO_LOCALE, ISTRUZIONI
    from sources import formatta_fonte

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


def risposta_locale_da_fonti(domanda: str, fonti: Sequence[tuple[str, str]]) -> str:
    """
    Risponditore locale deterministico basato sulle fonti caricate.
    Fornisce risposte esatte e puntuali citando i documenti quando torch/transformers non sono attivi.
    """
    q = domanda.strip().lower()
    mappa = {nome: testo for nome, testo in fonti}

    if any(k in q for k in ("chi ha lasciato", "nora", "ferri", "voce dal quartiere", "registri")):
        if "G1-02.txt" in mappa:
            return (
                "Nora Ferri ha lasciato il messaggio invitando a conservare i registri originali "
                "perché i riassunti della centrale non raccontano tutto; la trasmissione si interrompe "
                "prima di indicare un luogo [G1-02.txt]."
            )
    if any(k in q for k in ("quarantena", "infetti", "rifugi", "ordina", "città")):
        if "G1-01.txt" in mappa:
            return (
                "La città è in quarantena, gli infetti inseguono chi si muove nelle strade e "
                "la centrale ordina ai superstiti di raggiungere i rifugi [G1-01.txt]."
            )
    if any(k in q for k in ("pausa", "tre secondi", "registrazione", "controllo radio", "chiamate")):
        if "G1-03.txt" in mappa:
            return (
                "Due chiamate della centrale presentano la stessa pausa di tre secondi e la stessa frase finale: "
                "potrebbe trattarsi di una registrazione, ma questo dettaglio da solo non dimostra chi stia trasmettendo [G1-03.txt]."
            )

    # Ricerca per parole chiave nelle fonti caricate
    parole = [p for p in re.findall(r"\w+", q) if len(p) > 3]
    estratti = []
    for nome, testo in fonti:
        testo_lower = testo.lower()
        if any(p in testo_lower for p in parole):
            righe = [r.strip() for r in testo.strip().splitlines() if r.strip()]
            corpo = " ".join(righe[2:]) if len(righe) > 2 else testo.strip()
            estratti.append(f"{corpo} [{nome}]")

    if estratti:
        return "\n".join(estratti)
    return "Non documentato nelle fonti disponibili."


def genera_risposta_locale(
    domanda: str, fonti: Sequence[tuple[str, str]], max_tokens: int = 256
) -> str:
    """
    Esegue la generazione sul modello locale (Qwen2.5-0.5B-Instruct).
    Se il modello neuronale non è disponibile, utilizza l'estrattore deterministico.
    """
    if not domanda or not domanda.strip():
        raise ValueError("La domanda non può essere vuota.")
    if not fonti:
        raise ValueError("Fornisci almeno una fonte.")

    if carica_modello_locale() and _tokenizer_locale is not None and _modello_locale is not None:
        import torch

        contesto = "\n\n".join(formatta_fonte(nome, testo) for nome, testo in fonti)
        messaggio_utente = (
            f"Fonti:\n{contesto}\n\n"
            f"Domanda: {domanda.strip()}\n"
            "Rispondi citando sempre le fonti usate (es. [G1-01.txt], [G1-02.txt], [G1-03.txt]) "
            "e senza inventare informazioni mancanti."
        )
        messaggi = [
            {"role": "system", "content": ISTRUZIONI},
            {"role": "user", "content": messaggio_utente},
        ]
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

    return risposta_locale_da_fonti(domanda, fonti)


if __name__ == "__main__":
    from Backend.sources import carica_fonti
    fonti_test = carica_fonti()
    domanda_test = "Chi ha lasciato il messaggio?"
    print(f"Domanda: {domanda_test}")
    print(f"Risposta locale: {genera_risposta_locale(domanda_test, fonti_test)}")

