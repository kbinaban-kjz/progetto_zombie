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
# Documenti aggiunti giorno per giorno (es. new_dati/ per il Giorno 2)
NUOVI_DATI_DIR = ROOT_DIR / "new_dati"
# Archivio digitale di emergenza (Giorno 3 — Operazione Esumazione: .txt, .html, .json, .xml)
ARCHIVIO_DIR = DATI_DIR / "archivio" if (DATI_DIR / "archivio").is_dir() else ROOT_DIR / "archivio"
# Pacchetto "imprevisti" del Giorno 3 (500 documenti LX5_*.txt): va unito all'archivio per il RAG
IMPREVISTI_DIR = DATI_DIR / "dati_imprevisti_gg3"
ESTENSIONI_SUPPORTATE =(".txt", ".html", ".json", ".xml")
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

# Configurazione Database SQLite
DB_PATH = Path(valore_env("SQLITE_DB_PATH", str(BACKEND_DIR / "cronologia.db")))

# Modello Locale (Investigatore.py)
MODELLO_LOCALE = "Qwen/Qwen2.5-0.5B-Instruct"

# Modelli Cloud (Google Gemini)
MODELLO_GEMINI_DEFAULT = valore_env("GEMINI_MODEL", "gemini-flash-lite-latest")
MODELLI_GEMINI_RISERVA = [
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash",
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
]
MODELLO_OPENAI_DEFAULT = valore_env("OPENAI_MODEL", "gpt-4o-mini")

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
