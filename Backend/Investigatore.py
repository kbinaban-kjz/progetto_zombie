"""
Server HTTP di collegamento per il Frontend (Frontend/index.html) basato sul backend modello_openai.py.
Non modifica modello_openai.py: importa e richiama direttamente modello_openai.genera_risposta().

Avvio:
    python Backend/Investigatore.py
"""

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import modello_openai

# Supporta sia data/ (definito in modello_openai.DATA_DIR) sia dati/ presente nel repository
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
                    "backend": "modello_openai.py",
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

            try:
                risposta = modello_openai.genera_risposta(
                    domanda,
                    fonti,
                    api_key=api_key,
                    modello=modello,
                )
                return self._send_json(
                    {
                        "ok": True,
                        "domanda": domanda,
                        "risposta": risposta,
                        "fonti": [nome for nome, _ in fonti],
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
                            f"Chiamata al modello non riuscita ({type(errore).__name__}). "
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


def avvia_server(host: str = "127.0.0.1", port: int = 8000):
    server = ThreadingHTTPServer((host, port), ModelloOpenAIHandler)
    print(f"Server collegato a modello_openai.py attivo su http://{host}:{port}/")
    print(f"Scrivi una domanda alla volta. Digita '{modello_openai.COMANDO_USCITA}' per terminare.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProgramma terminato.")
        server.server_close()


if __name__ == "__main__":
    if "--cli" in sys.argv:
        sys.exit(modello_openai.main())
    porta = int(os.environ.get("PORT", 8000))
    avvia_server(port=porta)
