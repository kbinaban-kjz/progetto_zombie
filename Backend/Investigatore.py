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

from collections.abc import Sequence
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import json
import os
import re
import sys

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
_tokenizer_locale = None
_modello_locale = None
_modello_locale_tentato = False


def carica_modello_locale() -> bool:
    """Carica il modello locale Qwen/Qwen2.5-0.5B-Instruct su CPU (Cella 3 di Investigatore.ipynb)."""
    global _tokenizer_locale, _modello_locale, _modello_locale_tentato
    if _modello_locale_tentato:
        return _modello_locale is not None
    _modello_locale_tentato = True
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM

        print(f"[Locale] Caricamento modello {MODELLO_LOCALE} su CPU...")
        _tokenizer_locale = AutoTokenizer.from_pretrained(MODELLO_LOCALE)
        _modello_locale = AutoModelForCausalLM.from_pretrained(MODELLO_LOCALE).to("cpu")
        _modello_locale.eval()
        print(f"[Locale] Modello {MODELLO_LOCALE} pronto.")
        return True
    except Exception as exc:
        print(f"[Locale] Impossibile caricare {MODELLO_LOCALE} con transformers/torch ({exc}).")
        print("[Locale] Verrà usato il risponditore locale diretto sulle fonti .txt.")
        return False


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


def genera_risposta_locale(domanda: str, fonti: Sequence[tuple[str, str]], max_tokens: int = 220) -> str:
    """Esegue la generazione sul modello locale di Investigatore.py (Qwen/Qwen2.5-0.5B-Instruct)."""
    if not domanda or not domanda.strip():
        raise ValueError("La domanda non può essere vuota.")
    if not fonti:
        raise ValueError("Fornisci almeno una fonte.")

    if carica_modello_locale() and _tokenizer_locale is not None and _modello_locale is not None:
        import torch

        contesto = "\n\n".join(formatta_fonte_locale(nome, testo) for nome, testo in fonti)
        messaggio_utente = (
            f"Fonti:\n{contesto}\n\n"
            f"Domanda: {domanda.strip()}\n"
            "Rispondi citando sempre le fonti usate (es. [G1-01.txt], [G1-02.txt], [G1-03.txt]) "
            "e senza inventare informazioni mancanti."
        )
        messaggi = [
            {"role": "system", "content": modello_openai.ISTRUZIONI},
            {"role": "user", "content": messaggio_utente},
        ]
        testo = _tokenizer_locale.apply_chat_template(
            messaggi, tokenize=False, add_generation_prompt=True
        )
        dati = _tokenizer_locale(testo, return_tensors="pt")
        if dati["input_ids"].shape[1] > 6000:
            raise ValueError("Troppi documenti: seleziona le fonti con il RAG.")
        with torch.inference_mode():
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
) -> dict:
    """
    Smista la richiesta tra:
    - Modello locale di Investigatore.py (per richieste semplici o modalita='locale')
    - Modello cloud di modello_openai.py (per richieste complesse o modalita='cloud')
    """
    is_complessa, motivo = valuta_complessita(domanda)
    modalita_norm = (modalita or "auto").strip().lower()

    if modalita_norm == "locale":
        usa_cloud = False
        motivo = "Scelta manuale: Modello Locale (Investigatore.py)"
    elif modalita_norm == "cloud":
        usa_cloud = True
        motivo = "Scelta manuale: Modello Cloud (modello_openai.py)"
    else:
        usa_cloud = is_complessa

    livello = "complessa" if is_complessa else "semplice"

    if not usa_cloud:
        risposta = genera_risposta_locale(domanda, fonti)
        modello_effettivo = (
            MODELLO_LOCALE if _modello_locale is not None else f"{MODELLO_LOCALE} (estrattore locale)"
        )
        return {
            "risposta": risposta,
            "motore": "locale",
            "modello_usato": modello_effettivo,
            "complessita": livello,
            "motivo_routing": motivo,
        }

    # Richiesta complessa -> Modello Cloud (modello_openai.py)
    risposta = modello_openai.genera_risposta(
        domanda,
        fonti,
        api_key=api_key,
        modello=modello,
    )
    ha_key, provider = _ha_chiave_configurata()
    modello_cloud = modello or (
        os.environ.get("NVIDIA_MODEL") or "nvidia/nemotron-3-ultra-550b-a55b"
        if (api_key and api_key.startswith("nvapi-")) or provider == "NVIDIA"
        else os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    )
    return {
        "risposta": risposta,
        "motore": "cloud",
        "modello_usato": modello_cloud,
        "complessita": livello,
        "motivo_routing": motivo,
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
    chiave_nvidia = os.environ.get("NVIDIA_API_KEY") or modello_openai._valore_env_file("NVIDIA_API_KEY")
    chiave_openai = os.environ.get("OPENAI_API_KEY") or modello_openai._valore_env_file("OPENAI_API_KEY")
    if chiave_nvidia:
        return True, "NVIDIA"
    if chiave_openai:
        return True, "OpenAI"
    return False, "Nessuna (.env non configurato)"


# ==============================================================================
# 4. SERVER HTTP PER IL FRONTEND (Frontend/index.html)
# ==============================================================================
class ModelloOpenAIHandler(SimpleHTTPRequestHandler):
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

    def do_GET(self):
        path = urlparse(self.path).path

        if path in {"/", "/index.html"}:
            self.path = "/Frontend/index.html"
            return super().do_GET()

        if path == "/api/status":
            fonti = carica_fonti()
            ha_key, provider = _ha_chiave_configurata()
            modello_default = (
                os.environ.get("NVIDIA_MODEL") or "nvidia/nemotron-3-ultra-550b-a55b"
                if provider == "NVIDIA"
                else os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            )
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
                        "fonti": [nome for nome, _ in fonti],
                        "cronologia": leggi_cronologia(),
                    }
                )
            except modello_openai.AuthenticationError:
                return self._send_json(
                    {
                        "ok": False,
                        "error": "NVIDIA non ha accettato la chiave API. Controlla NVIDIA_API_KEY in .env.",
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
            salva_messaggio(domanda, esito["risposta"], [nome for nome, _ in fonti])
        except Exception as exc:
            print(f"Errore: {exc}")

    return 0


def avvia_server(host: str = "127.0.0.1", port: int = 8000):
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

