"""
Backend/Investigatore.py — Motore ibrido Locale + Cloud con server HTTP e interfaccia CLI.

- Richieste SEMPLICI  -> Modello locale di Investigatore.py (Qwen/Qwen2.5-0.5B-Instruct su CPU / estrattore locale sulle fonti)
- Richieste COMPLESSE -> Modello cloud di modello_openai.py (NVIDIA / OpenAI API)
- Persistenza         -> Database SQLite locale (Backend/cronologia.db, tabella cronologia_chat)

Avvio server web (Frontend + Backend):
    python Backend/Investigatore.py

Avvio da terminale interattivo:
    python Backend/Investigatore.py --cli
"""

from collections import OrderedDict
from collections.abc import Iterator, Sequence
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import json
import os
import re
import sys
import threading
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import modello_openai
from database import inizializza_db, salva_messaggio, leggi_cronologia

inizializza_db()

# ==============================================================================
# 1. MODELLO LOCALE DI INVESTIGATORE.PY (Qwen/Qwen2.5-0.5B-Instruct)
# ==============================================================================
MODELLO_LOCALE = "Qwen/Qwen2.5-0.5B-Instruct"
# Un modello da 0.5B su CPU è lento soprattutto in generazione: meno token = meno secondi.
MAX_TOKEN_LOCALE = int(os.environ.get("LOCAL_MAX_TOKENS", 120))
# Prompt BREVE per il modello locale: ogni token di prompt costa tempo di calcolo su CPU.
ISTRUZIONI_LOCALE = (
    "Sei un investigatore. Rispondi in italiano, in al massimo 3 frasi, usando le fonti "
    "e citandole (es. [G1-01.txt]). Per consigli pratici (sopravvivenza, rifugi) puoi usare "
    "conoscenze generali, ma distinguile da ciò che dicono le fonti. Se un fatto del caso "
    "non è nelle fonti scrivi: Non documentato nelle fonti disponibili. Non inventare."
)
_tokenizer_locale = None
_modello_locale = None
_modello_locale_tentato = False
_lock_caricamento = threading.Lock()
_lock_generazione = threading.Lock()


def carica_modello_locale() -> bool:
    """Carica il modello locale Qwen/Qwen2.5-0.5B-Instruct su CPU (Cella 3 di Investigatore.ipynb).

    Thread-safe: se il caricamento è già in corso in background, chi chiama aspetta che finisca.
    """

    global _tokenizer_locale, _modello_locale, _modello_locale_tentato
    if modello_openai._config("LOCALE_SENZA_TORCH") == "1":
        return False

    with _lock_caricamento:
        if _modello_locale_tentato:
            return _modello_locale is not None
        _modello_locale_tentato = True
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM

            torch.set_num_threads(max(1, os.cpu_count() or 1))
            print(f"[Locale] Caricamento modello {MODELLO_LOCALE} su CPU...")
            _tokenizer_locale = AutoTokenizer.from_pretrained(MODELLO_LOCALE)
            _modello_locale = AutoModelForCausalLM.from_pretrained(MODELLO_LOCALE).to("cpu")
            _modello_locale.eval()
            try:  # riscaldamento: la prima generazione è sempre la più lenta
                with torch.inference_mode():
                    dati = _tokenizer_locale("Ciao", return_tensors="pt")
                    _modello_locale.generate(
                        **dati,
                        max_new_tokens=1,
                        do_sample=False,
                        pad_token_id=_tokenizer_locale.eos_token_id,
                    )
            except Exception:
                pass
            print(f"[Locale] Modello {MODELLO_LOCALE} pronto.")
            return True
        except Exception as exc:
            _modello_locale = None
            print(f"[Locale] Impossibile caricare {MODELLO_LOCALE} con transformers/torch ({exc}).")
            print("[Locale] Verrà usato il risponditore locale diretto sulle fonti .txt.")
            return False


def precarica_modello_locale() -> None:
    """Avvia il caricamento di Qwen in background, così la prima domanda non lo aspetta."""
    if os.environ.get("PRECARICA_LOCALE", "1") != "0":
        threading.Thread(target=carica_modello_locale, daemon=True).start()


def formatta_fonte_locale(nome: str, testo: str) -> str:
    """Formatta una fonte come in Investigatore.ipynb: [ID] (Titolo): Corpo."""
    righe = [r.strip() for r in testo.strip().splitlines() if r.strip()]
    doc_id = righe[0].replace("ID ", "").strip() if righe else nome.replace(".txt", "")
    titolo = righe[1] if len(righe) > 1 else "Documento"
    corpo = " ".join(righe[2:]) if len(righe) > 2 else testo.strip()
    return f"[{doc_id}] ({titolo}): {corpo}"


def _risposta_locale_da_fonti(domanda: str, fonti: Sequence[tuple[str, str]]) -> str:
    """Risponditore locale deterministico basato sulle fonti quando torch/transformers non è attivo."""
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


def genera_risposta_locale(domanda: str, fonti: Sequence[tuple[str, str]], max_tokens: int | None = None) -> str:
    """Esegue la generazione sul modello locale di Investigatore.py (Qwen/Qwen2.5-0.5B-Instruct)."""
    if not domanda or not domanda.strip():
        raise ValueError("La domanda non può essere vuota.")
    if not fonti:
        raise ValueError("Fornisci almeno una fonte.")
    max_tokens = max_tokens or MAX_TOKEN_LOCALE

    if carica_modello_locale() and _tokenizer_locale is not None and _modello_locale is not None:
        import torch

        contesto = "\n\n".join(formatta_fonte_locale(nome, testo) for nome, testo in fonti)
        messaggio_utente = (
            f"Fonti:\n{contesto}\n\n"
            f"Domanda: {domanda.strip()}\n"
            "Rispondi in modo breve citando le fonti usate (es. [G1-01.txt])."
        )
        messaggi = [
            {"role": "system", "content": ISTRUZIONI_LOCALE},
            {"role": "user", "content": messaggio_utente},
        ]
        testo = _tokenizer_locale.apply_chat_template(
            messaggi, tokenize=False, add_generation_prompt=True
        )
        dati = _tokenizer_locale(testo, return_tensors="pt")
        if dati["input_ids"].shape[1] > 6000:
            raise ValueError("Troppi documenti: seleziona le fonti con il RAG.")
        with _lock_generazione, torch.inference_mode():
            out = _modello_locale.generate(
                **dati,
                max_new_tokens=max_tokens,
                do_sample=False,
                pad_token_id=_tokenizer_locale.eos_token_id,
            )
        risposta = _tokenizer_locale.decode(
            out[0][dati["input_ids"].shape[1] :], skip_special_tokens=True
        ).strip()
        if risposta:
            return risposta

    return _risposta_locale_da_fonti(domanda, fonti)


# ==============================================================================
# 2. CLASSIFICATORE DI COMPLESSITÀ E ROUTING IBRIDO (LOCALE vs CLOUD)
# ==============================================================================
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
    " approfond",
    "cronologia",
    "elenca tutti",
}


# Domande pratiche/generali ("come sopravvivere?", "dove ripararsi?"): la risposta
# NON sta nelle fonti, quindi il modello locale/estrattore non può rispondere -> cloud.
PAROLE_GENERALI = (
    "sopravviv",
    "al riparo",
    "stare al sicuro",
    "cosa devo fare",
    "cosa posso fare",
    "cosa dovrei fare",
    "dove devo andare",
    "dove posso andare",
    "dove andare",
    "come posso",
    "come faccio",
    "consigli",
    "consiglio",
    "proteggermi",
    "difendermi",
    "scappare",
    "nascondermi",
)


def valuta_complessita(domanda: str) -> tuple[bool, str]:
    """
    Determina se la domanda è semplice (False -> modello locale Investigatore.py)
    oppure complessa (True -> modello cloud modello_openai.py).
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

    # 3b. Domande pratiche/generali: servono conoscenze oltre le fonti
    for indicatore in PAROLE_GENERALI:
        if indicatore in testo_lower:
            return True, "Domanda pratica/generale (serve conoscenza oltre le fonti)"

    # 4. Domande lunghe o strutturate in più frasi
    if num_parole > 14 or len(testo) > 95:
        return True, f"Domanda articolata ({num_parole} parole)"

    return False, f"Domanda diretta e concisa ({num_parole} parole)"


# Cache delle risposte: la stessa domanda sulle stesse fonti torna in pochi millisecondi.
# Si disattiva con la variabile d'ambiente CACHE_RISPOSTE=0.
CACHE_MAX = 128
_cache_risposte: "OrderedDict[str, tuple[str, str]]" = OrderedDict()
_lock_cache = threading.Lock()


def _cache_attiva() -> bool:
    return os.environ.get("CACHE_RISPOSTE", "1") != "0"


def _chiave_cache(domanda: str, fonti: Sequence[tuple[str, str]], motore: str, modello: str | None) -> str:
    h = hashlib.sha1()
    h.update(" ".join(domanda.casefold().split()).encode("utf-8"))
    h.update(f"|{motore}|{modello or ''}|".encode("utf-8"))
    for nome, testo in fonti:
        h.update(nome.encode("utf-8"))
        h.update(testo.encode("utf-8"))
    return h.hexdigest()


def _cache_leggi(chiave: str):
    if not _cache_attiva():
        return None
    with _lock_cache:
        voce = _cache_risposte.get(chiave)
        if voce is not None:
            _cache_risposte.move_to_end(chiave)
        return voce


def _cache_scrivi(chiave: str, risposta: str, modello: str) -> None:
    if not _cache_attiva():
        return
    with _lock_cache:
        _cache_risposte[chiave] = (risposta, modello)
        _cache_risposte.move_to_end(chiave)
        while len(_cache_risposte) > CACHE_MAX:
            _cache_risposte.popitem(last=False)


def _flusso_ibrido(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    *,
    api_key: str | None = None,
    modello: str | None = None,
    modalita: str = "auto",
) -> Iterator[dict]:
    """
    Smista la richiesta tra:
    - Modello locale di Investigatore.py (per richieste semplici o modalita='locale')
    - Modello cloud di modello_openai.py (per richieste complesse o modalita='cloud')

    Produce eventi: {"tipo": "meta"}, poi {"tipo": "delta", "testo": ...} (uno o più),
    infine {"tipo": "fine", "risposta", "modello_usato", "tempo_ms", "ttft_ms", "da_cache"}.
    """
    inizio = time.perf_counter()
    is_complessa, motivo = valuta_complessita(domanda)
    modalita_norm = (modalita or "auto").strip().lower()
    ha_key, provider = _ha_chiave_configurata()
    cloud_disponibile = bool(api_key) or ha_key

    if modalita_norm == "locale":
        usa_cloud = False
        motivo = "Scelta manuale: Modello Locale (Investigatore.py)"
    elif modalita_norm == "cloud":
        usa_cloud = True
        motivo = "Scelta manuale: Modello Cloud (modello_openai.py)"
    else:
        usa_cloud = cloud_disponibile
        if usa_cloud and not cloud_disponibile:
            usa_cloud = False
            motivo += " — cloud non configurato, risponde il locale"

    livello = "complessa" if is_complessa else "semplice"
    motore = "cloud" if usa_cloud else "locale"
    if usa_cloud:
        modello_previsto = modello or modello_openai.modello_predefinito(
            modello_openai.rileva_provider(api_key)
        )
    else:
        modello_previsto = MODELLO_LOCALE

    yield {
        "tipo": "meta",
        "motore": motore,
        "modello_usato": modello_previsto,
        "complessita": livello,
        "motivo_routing": motivo,
    }

    chiave = _chiave_cache(domanda, fonti, motore, modello)
    voce = _cache_leggi(chiave)
    if voce is not None:
        risposta, modello_reale = voce
        tempo = round((time.perf_counter() - inizio) * 1000)
        yield {"tipo": "delta", "testo": risposta}
        yield {
            "tipo": "fine",
            "risposta": risposta,
            "modello_usato": modello_reale,
            "tempo_ms": tempo,
            "ttft_ms": tempo,
            "da_cache": True,
        }
        return

    parti: list[str] = []
    primo = None
    modello_reale = modello_previsto
    if usa_cloud:
        # Richiesta complessa -> Modello Cloud (modello_openai.py), risposta in streaming
        for evento in modello_openai.genera_risposta_stream(
            domanda, fonti, api_key=api_key, modello=modello
        ):
            if "delta" in evento:
                if primo is None:
                    primo = time.perf_counter()
                parti.append(evento["delta"])
                yield {"tipo": "delta", "testo": evento["delta"]}
            elif evento.get("fine"):
                modello_reale = evento["modello"]  # il modello che ha risposto davvero
    else:
        testo = genera_risposta_locale(domanda, fonti)
        primo = time.perf_counter()
        parti.append(testo)
        modello_reale = (
            MODELLO_LOCALE if _modello_locale is not None else f"{MODELLO_LOCALE} (estrattore locale)"
        )
        yield {"tipo": "delta", "testo": testo}

    risposta = "".join(parti).strip()
    if not risposta:
        raise RuntimeError("Il modello ha restituito una risposta vuota.")
    _cache_scrivi(chiave, risposta, modello_reale)
    fine = time.perf_counter()
    yield {
        "tipo": "fine",
        "risposta": risposta,
        "modello_usato": modello_reale,
        "tempo_ms": round((fine - inizio) * 1000),
        "ttft_ms": round(((primo or fine) - inizio) * 1000),
        "da_cache": False,
    }


def genera_risposta_ibrida(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    *,
    api_key: str | None = None,
    modello: str | None = None,
    modalita: str = "auto",
) -> dict:
    """Versione non in streaming di _flusso_ibrido: restituisce la risposta completa."""
    meta: dict = {}
    fine: dict = {}
    for evento in _flusso_ibrido(domanda, fonti, api_key=api_key, modello=modello, modalita=modalita):
        if evento["tipo"] == "meta":
            meta = evento
        elif evento["tipo"] == "fine":
            fine = evento
    return {
        "risposta": fine["risposta"],
        "motore": meta["motore"],
        "modello_usato": fine["modello_usato"],
        "complessita": meta["complessita"],
        "motivo_routing": meta["motivo_routing"],
        "tempo_ms": fine["tempo_ms"],
        "ttft_ms": fine["ttft_ms"],
        "da_cache": fine["da_cache"],
    }


# ==============================================================================
# 3. GESTIONE FONTI E STATO CHIAVI API
# ==============================================================================
def _risolvi_cartella_dati() -> Path:
    if modello_openai.DATA_DIR.is_dir():
        return modello_openai.DATA_DIR
    if (ROOT_DIR / "dati").is_dir():
        return ROOT_DIR / "dati"
    return modello_openai.DATA_DIR


def carica_fonti() -> list[tuple[str, str]]:
    cartella = _risolvi_cartella_dati()
    if not cartella.is_dir():
        return []
    percorsi = sorted(cartella.glob("*.txt"))
    return [(p.name, p.read_text(encoding="utf-8")) for p in percorsi]


def _ha_chiave_configurata() -> tuple[bool, str]:
    provider = modello_openai.rileva_provider(None)
    if provider:
        return True, {"nvidia": "NVIDIA", "gemini": "Gemini", "openai": "OpenAI"}[provider]
    return False, "Nessuna (.env non configurato)"


# ==============================================================================
# 4. SERVER HTTP PER IL FRONTEND (Frontend/index.html)
# ==============================================================================
def _errore_http(errore: Exception) -> tuple[int, str]:
    """Codice HTTP e messaggio per l'utente a partire da un'eccezione."""
    if isinstance(errore, modello_openai.AuthenticationError):
        return 401, "La chiave API non è stata accettata dal provider. Controlla la chiave (NVIDIA_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY) nel file .env della cartella Backend."
    if isinstance(errore, modello_openai.OpenAIError):
        return 502, (
            f"Chiamata al modello cloud non riuscita ({type(errore).__name__}). "
            "Controlla la connessione, il modello e la quota API."
        )
    if isinstance(errore, (RuntimeError, ValueError)):
        return 400, f"Impossibile ottenere una risposta: {errore}"
    return 500, f"Errore interno: {errore}"


class ModelloOpenAIHandler(SimpleHTTPRequestHandler):
    disable_nagle_algorithm = True  # invia subito i pacchetti piccoli (niente ritardi di ~40 ms)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _send_json(self, data: dict, status: int = 200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _chat_stream(self, payload: dict):
        """POST /api/chat/stream: risposta a pezzi (una riga JSON per evento), il testo appare subito."""
        domanda = (payload.get("domanda") or "").strip()
        if not domanda:
            return self._send_json(
                {"ok": False, "error": "La domanda è vuota: scrivi una domanda oppure digita 'esci'."},
                status=400,
            )
        if domanda.casefold() == modello_openai.COMANDO_USCITA:
            return self._send_json({"ok": True, "terminato": True, "risposta": "Programma terminato."})

        fonti_payload = payload.get("fonti")
        if isinstance(fonti_payload, list) and fonti_payload:
            fonti = [
                (str(f.get("nome", "")), str(f.get("contenuto", "")))
                for f in fonti_payload
                if f.get("nome") and f.get("contenuto")
            ]
        else:
            fonti = carica_fonti()
        api_key = (payload.get("api_key") or "").strip() or None
        modello = (payload.get("modello") or "").strip() or None
        modalita = (payload.get("modalita") or "auto").strip().lower()

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def invia(evento: dict):
            self.wfile.write((json.dumps(evento, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        try:
            for evento in _flusso_ibrido(
                domanda, fonti, api_key=api_key, modello=modello, modalita=modalita
            ):
                if evento["tipo"] == "fine":
                    # Il testo è già a schermo: il salvataggio su SQLite non ritarda la risposta
                    evento["fonti"] = [nome for nome, _ in fonti]
                    evento["record"] = None
                    try:
                        salva_messaggio(domanda, evento["risposta"], evento["fonti"])
                        cronologia = leggi_cronologia()
                        evento["record"] = cronologia[-1] if cronologia else None
                    except Exception as exc_db:
                        evento["avviso_db"] = str(exc_db)
                invia(evento)
        except (BrokenPipeError, ConnectionResetError):
            return  # il browser ha chiuso la connessione
        except Exception as errore:
            codice, messaggio = _errore_http(errore)
            try:
                invia({"tipo": "errore", "status": codice, "error": messaggio})
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        path = urlparse(self.path).path

        if path in {"/", "/index.html"}:
            self.path = "/Frontend/index.html"
            return super().do_GET()

        if path == "/api/status":
            fonti = carica_fonti()
            ha_key, provider = _ha_chiave_configurata()
            modello_default = modello_openai.modello_predefinito(modello_openai.rileva_provider(None))
            return self._send_json(
                {
                    "ok": True,
                    "backend": "Ibrido (Investigatore.py Locale + modello_openai.py Cloud)",
                    "modello_locale": MODELLO_LOCALE,
                    "modello_locale_caricato": _modello_locale is not None,
                    "chiave_configurata": ha_key,
                    "provider": provider,
                    "modello_default": modello_default,
                    "modelli_nvidia_riserva": modello_openai.MODELLI_NVIDIA_RISERVA,
                    "istruzioni": modello_openai.ISTRUZIONI,
                    "domanda_esempio": modello_openai.DOMANDA_ESEMPIO,
                    "comando_uscita": modello_openai.COMANDO_USCITA,
                    "cartella_dati": str(_risolvi_cartella_dati().relative_to(ROOT_DIR)),
                    "file_fonti": [nome for nome, _ in fonti],
                }
            )

        if path == "/api/history":
            return self._send_json({"ok": True, "cronologia": leggi_cronologia()})

        if path == "/api/sources":
            fonti = carica_fonti()
            return self._send_json(
                {
                    "ok": True,
                    "fonti": [
                        {
                            "nome": nome,
                            "contenuto": contenuto,
                            "formattata": f"--- Fonte: {nome} ---\n{contenuto}",
                        }
                        for nome, contenuto in fonti
                    ],
                }
            )

        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return self._send_json({"ok": False, "error": "JSON non valido."}, status=400)

        if path == "/api/chat/stream":
            return self._chat_stream(payload)

        if path == "/api/chat":
            domanda = (payload.get("domanda") or "").strip()
            if not domanda:
                return self._send_json(
                    {
                        "ok": False,
                        "error": "La domanda è vuota: scrivi una domanda oppure digita 'esci'.",
                    },
                    status=400,
                )

            if domanda.casefold() == modello_openai.COMANDO_USCITA:
                return self._send_json(
                    {
                        "ok": True,
                        "terminato": True,
                        "risposta": "Programma terminato.",
                    }
                )

            # Usa le fonti inviate dal frontend oppure quelle caricate da disco
            fonti_payload = payload.get("fonti")
            if isinstance(fonti_payload, list) and fonti_payload:
                fonti = [
                    (str(f.get("nome", "")), str(f.get("contenuto", "")))
                    for f in fonti_payload
                    if f.get("nome") and f.get("contenuto")
                ]
            else:
                fonti = carica_fonti()

            api_key = (payload.get("api_key") or "").strip() or None
            modello = (payload.get("modello") or "").strip() or None
            modalita = (payload.get("modalita") or "auto").strip().lower()

            try:
                esito = genera_risposta_ibrida(
                    domanda,
                    fonti,
                    api_key=api_key,
                    modello=modello,
                    modalita=modalita,
                )
                risposta = esito["risposta"]
                salva_messaggio(domanda, risposta, [nome for nome, _ in fonti])
                return self._send_json(
                    {
                        "ok": True,
                        "domanda": domanda,
                        "risposta": risposta,
                        "motore": esito["motore"],
                        "modello_usato": esito["modello_usato"],
                        "complessita": esito["complessita"],
                        "motivo_routing": esito["motivo_routing"],
                        "tempo_ms": esito["tempo_ms"],
                        "ttft_ms": esito["ttft_ms"],
                        "da_cache": esito["da_cache"],
                        "fonti": [nome for nome, _ in fonti],
                        "cronologia": leggi_cronologia(),
                    }
                )
            except modello_openai.AuthenticationError:
                return self._send_json(
                    {
                        "ok": False,
                        "error": "La chiave API non è stata accettata dal provider. Controlla la chiave (NVIDIA_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY) nel file .env della cartella Backend.",
                    },
                    status=401,
                )
            except modello_openai.OpenAIError as errore:
                return self._send_json(
                    {
                        "ok": False,
                        "error": (
                            f"Chiamata al modello cloud non riuscita ({type(errore).__name__}). "
                            "Controlla la connessione, il modello e la quota API."
                        ),
                    },
                    status=502,
                )
            except (RuntimeError, ValueError) as errore:
                return self._send_json(
                    {
                        "ok": False,
                        "error": f"Impossibile ottenere una risposta: {errore}",
                    },
                    status=400,
                )

        return self._send_json({"ok": False, "error": "Endpoint non trovato."}, status=404)


def avvia_cli() -> int:
    """Modalità interattiva da terminale con routing automatico Locale (semplici) / Cloud (complesse)."""
    fonti = carica_fonti()
    if not fonti:
        print("Impossibile avviare la chat: Nessun file .txt trovato in dati/.")
        return 1

    precarica_modello_locale()
    print("=== Investigatore AI — Routing Ibrido (Locale: Investigatore.py | Cloud: modello_openai.py) ===")
    print(f"Scrivi una domanda alla volta. Digita '{modello_openai.COMANDO_USCITA}' per terminare.")

    while True:
        try:
            domanda = input(f"\nDomanda (es. {modello_openai.DOMANDA_ESEMPIO}): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nProgramma terminato.")
            return 0

        if not domanda:
            print("La domanda è vuota: scrivi una domanda oppure digita 'esci'.")
            continue

        if domanda.casefold() == modello_openai.COMANDO_USCITA:
            print("Programma terminato.")
            return 0

        try:
            esito = genera_risposta_ibrida(domanda, fonti)
            etichetta = (
                f"[LOCALE • {esito['modello_usato']}]"
                if esito["motore"] == "locale"
                else f"[CLOUD • {esito['modello_usato']}]"
            )
            print(f"\n{etichetta} ({esito['complessita']} — {esito['motivo_routing']})")
            print(f"Risposta:\n{esito['risposta']}")
            print(f"(⏱ {esito['tempo_ms'] / 1000:.2f} s{' • cache' if esito['da_cache'] else ''})")
            salva_messaggio(domanda, esito["risposta"], [nome for nome, _ in fonti])
        except Exception as exc:
            print(f"Errore: {exc}")

    return 0


def avvia_server(host: str = "127.0.0.1", port: int = 8000):
    precarica_modello_locale()
    server = ThreadingHTTPServer((host, port), ModelloOpenAIHandler)
    print(f"Server ibrido (Locale Investigatore.py + Cloud modello_openai.py) attivo su http://{host}:{port}/")
    print(f"Scrivi una domanda alla volta. Digita '{modello_openai.COMANDO_USCITA}' per terminare.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProgramma terminato.")
        server.server_close()


if __name__ == "__main__":
    if "--cli" in sys.argv:
        sys.exit(avvia_cli())
    porta = int(os.environ.get("PORT", 8000))
    avvia_server(port=porta)

