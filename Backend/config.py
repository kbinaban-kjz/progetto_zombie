"""
Backend/config.py — Configurazione centralizzata del progetto Investigatore AI.

Gestisce percorsi, variabili d'ambiente (.env), modelli e costanti condivise.
"""

import os
import sys
from pathlib import Path

# Percorsi principali del progetto
BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
ENV_PATH = ROOT_DIR / ".env"
DATI_DIR = ROOT_DIR / "dati" if (ROOT_DIR / "dati").is_dir() else ROOT_DIR / "data"
# Documenti aggiunti giorno per giorno (es. new_dati/ per il Giorno 2, dati_4/ per il Giorno 5)
NUOVI_DATI_DIR = ROOT_DIR / "new_dati"
DATI_4_DIR = ROOT_DIR / "dati_4"
# Archivio digitale di emergenza (Giorno 3 — Operazione Esumazione: .txt, .html, .json, .xml)
ARCHIVIO_DIR = DATI_DIR / "archivio" if (DATI_DIR / "archivio").is_dir() else ROOT_DIR / "archivio"
# Pacchetto "imprevisti" del Giorno 3 (500 documenti LX5_*.txt): va unito all'archivio per il RAG
IMPREVISTI_DIR = DATI_DIR / "dati_imprevisti_gg3"
ESTENSIONI_SUPPORTATE = (".txt", ".html", ".json", ".xml", ".xlsx")
MODELLO_EMBEDDING_RAG = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Assicura che la root e la cartella Backend siano nel PYTHONPATH
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Cache per il caricamento del file .env
_env_cache_mtime: int | None = None
_env_cache_valori: dict[str, str] = {}

# Caricamento variabili dal file .env (se presente)
def carica_env() -> dict[str, str]:
    """Legge le variabili definite nel file .env con cache basata su mtime senza sovrascrivere l'ambiente esistente."""
    global _env_cache_mtime, _env_cache_valori
    if not ENV_PATH.is_file():
        return {}
    try:
        mtime = ENV_PATH.stat().st_mtime_ns
        if _env_cache_mtime == mtime:
            return _env_cache_valori
        valori: dict[str, str] = {}
        for riga in ENV_PATH.read_text(encoding="utf-8").splitlines():
            riga = riga.strip()
            if not riga or riga.startswith("#") or "=" not in riga:
                continue
            chiave, valore = riga.split("=", 1)
            chiave_clean = chiave.strip()
            valore_clean = valore.strip().strip("\"'")
            valori[chiave_clean] = valore_clean
            os.environ.setdefault(chiave_clean, valore_clean)
        _env_cache_valori = valori
        _env_cache_mtime = mtime
        return valori
    except Exception:
        return _env_cache_valori

# Inizializza l'ambiente da .env
carica_env()

def valore_env(nome: str, default: str | None = None) -> str | None:
    """Restituisce il valore di una variabile d'ambiente (da os.environ o da .env)."""
    return os.environ.get(nome) or carica_env().get(nome) or default


def risolvi_cartelle_dati_disponibili() -> list[Path]:
    """
    Rileva dinamicamente tutte le cartelle dati presenti nel workspace senza hardcoding:
    - Cartelle standard (dati/, new_dati/, dati_4/)
    - Qualsiasi cartella nella root che inizi per 'dati' o 'data' e contenga documenti operativi
    - Percorsi configurati da variabili d'ambiente (DATI_DIR, DATI_4_DIR, ecc.)
    """
    trovate: list[Path] = []

    # 1. Candidati espliciti/d'ambiente
    candidati_base = [
        valore_env("DATI_DIR"),
        valore_env("DATI_4_DIR"),
        str(DATI_DIR),
        str(NUOVI_DATI_DIR),
        str(DATI_4_DIR),
        str(ROOT_DIR / "data"),
    ]
    for c in candidati_base:
        if c:
            p = Path(c).resolve()
            if p.is_dir() and p not in trovate:
                trovate.append(p)

    # 2. Rilevamento dinamico su ROOT_DIR (qualsiasi cartella dati* o new_dati*)
    try:
        for p in ROOT_DIR.iterdir():
            if p.is_dir() and not p.name.startswith((".", "_", "~")):
                nome_low = p.name.lower()
                if (nome_low.startswith("dati") or nome_low.startswith("data") or "dati" in nome_low) and p.resolve() not in trovate:
                    if p.name in ("archivio", "dati_imprevisti_gg3"):
                        continue
                    try:
                        if any(f.is_file() and f.suffix.lower() in ESTENSIONI_SUPPORTATE for f in p.iterdir()):
                            trovate.append(p.resolve())
                    except Exception:
                        pass
    except Exception:
        pass

    return trovate

# Configurazione Database SQLite (Cronologia conversazioni)
DB_PATH = Path(valore_env("SQLITE_DB_PATH", str(BACKEND_DIR / "cronologia.db")))

# Configurazione Database Accessi (Giorno 4 — Operazione Varco: accessi.sqlite)
DATA_MISSIONE_G4 = "2031-10-12 06:00"

def risolvi_accessi_db() -> Path:
    """Restituisce il percorso valido del database accessi.sqlite controllando le posizioni note."""
    env_p = valore_env("ACCESSI_DB_PATH")
    percorsi_candidati = [
        Path(env_p) if env_p else None,
        ROOT_DIR / "accessi.sqlite",
        BACKEND_DIR / "accessi.sqlite",
        ROOT_DIR / "New information" / "accessi.sqlite",
        ROOT_DIR / "New Information" / "accessi.sqlite",
        Path("accessi.sqlite"),
    ]
    for p in percorsi_candidati:
        if p and p.is_file():
            return p.resolve()
    return (ROOT_DIR / "accessi.sqlite").resolve()

ACCESSI_DB_PATH = risolvi_accessi_db()

# Configurazione Archivio Recuperato e Tabelle CSV (Giorno 4 — Terminale Danneggiato / Archivio Erebo V-59)
DATA_MISSIONE_VARCO = "2026-11-04 12:00"

def risolvi_tabelle_csv_dir() -> Path:
    """Restituisce il percorso valido della cartella TABELLE_CSV controllando le posizioni note."""
    env_p = valore_env("TABELLE_CSV_DIR")
    percorsi_candidati = [
        Path(env_p) if env_p else None,
        ROOT_DIR / "New Information 2" / "TABELLE_CSV",
        ROOT_DIR / "New information 2" / "TABELLE_CSV",
        ROOT_DIR / "TABELLE_CSV",
        BACKEND_DIR / "TABELLE_CSV",
        Path("TABELLE_CSV"),
    ]
    for p in percorsi_candidati:
        if p and p.is_dir():
            return p.resolve()
    return (ROOT_DIR / "New Information 2" / "TABELLE_CSV").resolve()

def risolvi_archivio_recuperato_db() -> Path:
    """Restituisce il percorso valido del database archivio_recuperato.sqlite controllando le posizioni note."""
    env_p = valore_env("ARCHIVIO_RECUPERATO_DB_PATH")
    percorsi_candidati = [
        Path(env_p) if env_p else None,
        ROOT_DIR / "New Information 2" / "archivio_recuperato.sqlite",
        ROOT_DIR / "New information 2" / "archivio_recuperato.sqlite",
        ROOT_DIR / "archivio_recuperato.sqlite",
        BACKEND_DIR / "archivio_recuperato.sqlite",
        Path("archivio_recuperato.sqlite"),
    ]
    for p in percorsi_candidati:
        if p and p.is_file():
            return p.resolve()
    return (ROOT_DIR / "New Information 2" / "archivio_recuperato.sqlite").resolve()

TABELLE_CSV_DIR = risolvi_tabelle_csv_dir()
ARCHIVIO_RECUPERATO_DB_PATH = risolvi_archivio_recuperato_db()

# Modello Locale (Investigatore.py)
# Cambia modello locale da .env (MODELLO_LOCALE=...) senza toccare il codice
MODELLO_LOCALE = valore_env("MODELLO_LOCALE", "Qwen/Qwen2.5-1.5B-Instruct")

# Modelli Cloud (Google Gemini)
MODELLO_GEMINI_DEFAULT = valore_env("GEMINI_MODEL", "gemini-flash-lite-latest")
MODELLI_GEMINI_RISERVA = [
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]

# Modelli Cloud (OpenAI / NVIDIA NIM)
NVIDIA_BASE_URL = valore_env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
MODELLO_NVIDIA_DEFAULT = valore_env("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
MODELLI_NVIDIA_RISERVA = [
    "meta/llama-3.1-8b-instruct",
    "meta/llama-3.3-70b-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/llama-3.1-nemotron-51b-instruct",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-4-340b-instruct",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/nemotron-3-ultra-550b-a55b",
]


def elenco_modelli_nvidia() -> list[str]:
    """
    Catalogo dei modelli NVIDIA esposto al frontend (GET /api/status -> "modelli_nvidia").
    Ordine: modello di default (NVIDIA_MODEL), poi quelli extra definiti nel .env
    (NVIDIA_MODELS_EXTRA, separati da virgola), infine i modelli di riserva. Senza duplicati.
    Per aggiungere un modello basta toccare il .env o MODELLI_NVIDIA_RISERVA: il frontend non va modificato.
    """
    extra = [m.strip() for m in (valore_env("NVIDIA_MODELS_EXTRA") or "").split(",") if m.strip()]
    elenco: list[str] = []
    for nome in [MODELLO_NVIDIA_DEFAULT, *extra, *MODELLI_NVIDIA_RISERVA]:
        if nome and nome not in elenco:
            elenco.append(nome)
    return elenco


MODELLO_OPENAI_DEFAULT = valore_env("OPENAI_MODEL", "gpt-4o-mini")

# Cataloghi mostrati nel menu "Modello Cloud" del frontend (GET /api/status).
# Per aggiungerne altri senza toccare il codice: GEMINI_MODELS_EXTRA / OPENAI_MODELS_EXTRA nel .env (separati da virgola).
MODELLI_GEMINI_DISPONIBILI = [
    "gemini-3.8-flash-lite",
    "gemini-3.8-flash",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.1-pro-preview",
]
MODELLI_OPENAI_DISPONIBILI = [
    "gpt-4o-mini",
]


def _catalogo_modelli(base: list[str], nome_env_extra: str, default: str | None) -> list[str]:
    """Unisce lista base + modelli extra del .env + modello di default, senza duplicati e mantenendo l'ordine."""
    extra = [m.strip() for m in (valore_env(nome_env_extra) or "").split(",") if m.strip()]
    elenco: list[str] = []
    for nome in [*base, *extra, default]:
        if nome and nome not in elenco:
            elenco.append(nome)
    return elenco


def elenco_modelli_gemini() -> list[str]:
    return _catalogo_modelli(MODELLI_GEMINI_DISPONIBILI, "GEMINI_MODELS_EXTRA", MODELLO_GEMINI_DEFAULT)


def elenco_modelli_openai() -> list[str]:
    return _catalogo_modelli(MODELLI_OPENAI_DISPONIBILI, "OPENAI_MODELS_EXTRA", MODELLO_OPENAI_DEFAULT)


# Timeout e impostazioni rete
TIMEOUT_SECONDI = 30.0
STATI_RIPROVABILI = {404, 408, 429, 500, 502, 503, 504}

# Comandi e costanti di interazione
DOMANDA_ESEMPIO = "Chi ha lasciato il messaggio? Rispondi citando la fonte."
COMANDO_USCITA = "esci"

# Istruzioni di sistema (Prompt dell'investigatore definito in prompts.py)
try:
    from Backend.prompts import ISTRUZIONI, PROMPT_SISTEMA
except ImportError:
    from prompts import ISTRUZIONI, PROMPT_SISTEMA

def get_gemini_api_key() -> str | None:
    """Restituisce la chiave API di Google Gemini (da GEMINI_API_KEY o GEMINI_API)."""
    return valore_env("GEMINI_API_KEY") or valore_env("GEMINI_API")

def get_nvidia_api_key() -> str | None:
    """Restituisce la chiave API di NVIDIA NIM."""
    return valore_env("NVIDIA_API_KEY")

def get_openai_api_key() -> str | None:
    """Restituisce la chiave API di OpenAI."""
    return valore_env("OPENAI_API_KEY")

def stato_chiavi_api() -> tuple[bool, str]:
    """Verifica se è configurata una chiave per Gemini, NVIDIA o OpenAI."""
    chiave_gemini = get_gemini_api_key()
    chiave_nvidia = get_nvidia_api_key()
    chiave_openai = get_openai_api_key()

    provider_attivi: list[str] = []
    if chiave_gemini:
        provider_attivi.append("Gemini")
    if chiave_nvidia:
        provider_attivi.append("NVIDIA")
    if chiave_openai:
        provider_attivi.append("OpenAI")

    if provider_attivi:
        return True, " / ".join(provider_attivi)
    return False, "Nessuna (.env non configurato)"
