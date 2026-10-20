"""
Backend/server.py — Server HTTP e API REST per l'interfaccia Web (Frontend).

Responsabilità:
- Servire i file statici del Frontend (HTML, CSS, JS) e della mappa.
- Esporre gli endpoint REST:
    GET  /api/status         -> Stato del sistema, modelli e chiavi
    GET  /api/history        -> Cronologia completa salvata in SQLite
    GET  /api/sources        -> Elenco e contenuto delle fonti del dossier
    GET  /api/tools          -> Catalogo degli strumenti operativi disponibili
    POST /api/chat           -> Esecuzione query ibrida (Locale vs Cloud)
    POST /api/tools/execute  -> Invocazione diretta di un tool da API
"""

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Any

try:
    from Backend.config import (
        ROOT_DIR,
        MODELLO_LOCALE,
        MODELLO_NVIDIA_DEFAULT,
        MODELLI_NVIDIA_RISERVA,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        stato_chiavi_api,
    )
    from Backend.database import (
        leggi_cronologia_con_instradamento,
        salva_con_instradamento,
    )
    from Backend.sources import carica_fonti, risolvi_cartella_dati
    from Backend.tools import TOOLS_OPENAI_SCHEMA, STRUMENTI_REGISTRATI, esegui_tool
    from Backend.modello_locale import is_modello_caricato
    from Backend.router import genera_risposta_ibrida
    import Backend.modello_openai as modello_openai
except ImportError:
    from config import (
        ROOT_DIR,
        MODELLO_LOCALE,
        MODELLO_NVIDIA_DEFAULT,
        MODELLI_NVIDIA_RISERVA,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        stato_chiavi_api,
    )
    from database import (
        leggi_cronologia_con_instradamento,
        salva_con_instradamento,
    )
    from sources import carica_fonti, risolvi_cartella_dati
    from tools import TOOLS_OPENAI_SCHEMA, STRUMENTI_REGISTRATI, esegui_tool
    from modello_locale import is_modello_caricato
    from router import genera_risposta_ibrida
    import modello_openai


class InvestigatoreHTTPHandler(SimpleHTTPRequestHandler):
    """Handler HTTP con supporto CORS, API REST e servizio file statici."""

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

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path

        # Reindirizzamento alla homepage del Frontend
        if path in {"/", "/index.html"}:
            self.path = "/Frontend/index.html"
            return super().do_GET()

        # Compatibilità percorsi mappa: mappa/ ora risiede in Frontend/mappa/
        if path.startswith("/mappa"):
            self.path = "/Frontend" + path
            return super().do_GET()

        # API: Stato complessivo
        if path == "/api/status":
            fonti = carica_fonti()
            ha_key, provider = stato_chiavi_api()
            modello_default = (
                os.environ.get("NVIDIA_MODEL") or MODELLO_NVIDIA_DEFAULT
                if provider == "NVIDIA"
                else os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            )
            return self._send_json(
                {
                    "ok": True,
                    "backend": "Ibrido Modulare (Locale + Cloud + Tools)",
                    "modello_locale": MODELLO_LOCALE,
                    "modello_locale_caricato": is_modello_caricato(),
                    "chiave_configurata": ha_key,
                    "provider": provider,
                    "modello_default": modello_default,
                    "modelli_nvidia_riserva": MODELLI_NVIDIA_RISERVA,
                    "istruzioni": ISTRUZIONI,
                    "domanda_esempio": DOMANDA_ESEMPIO,
                    "comando_uscita": COMANDO_USCITA,
                    "cartella_dati": str(risolvi_cartella_dati().relative_to(ROOT_DIR)),
                    "file_fonti": [nome for nome, _ in fonti],
                    "tools_disponibili": list(STRUMENTI_REGISTRATI.keys()),
                }
            )

        # API: Cronologia SQLite arricchita con routing
        if path == "/api/history":
            return self._send_json(
                {"ok": True, "cronologia": leggi_cronologia_con_instradamento()}
            )

        # API: Fonti disponibili
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

        # API: Strumenti operativi (Tools) per l'AI
        if path == "/api/tools":
            return self._send_json(
                {
                    "ok": True,
                    "totale": len(STRUMENTI_REGISTRATI),
                    "strumenti": list(STRUMENTI_REGISTRATI.keys()),
                    "schemas": TOOLS_OPENAI_SCHEMA,
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

        # API: Esecuzione diretta di un tool
        if path == "/api/tools/execute":
            nome_tool = payload.get("tool") or payload.get("nome")
            argomenti = payload.get("arguments") or payload.get("argomenti") or {}
            if not nome_tool:
                return self._send_json(
                    {"ok": False, "error": "Parametro 'tool' mancante nel payload."},
                    status=400,
                )
            esito = esegui_tool(nome_tool, argomenti)
            return self._send_json(esito)

        # API: Chat principale dell'Investigatore
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

            if domanda.casefold() == COMANDO_USCITA:
                return self._send_json(
                    {
                        "ok": True,
                        "terminato": True,
                        "risposta": "Programma terminato.",
                    }
                )

            # Usa le fonti inviate dal client oppure quelle lette da disco
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
            usa_tools = bool(payload.get("usa_tools", False))

            try:
                esito = genera_risposta_ibrida(
                    domanda,
                    fonti,
                    api_key=api_key,
                    modello=modello,
                    modalita=modalita,
                    usa_tools=usa_tools,
                )
                risposta = esito["risposta"]
                record = salva_con_instradamento(domanda, [nome for nome, _ in fonti], esito)
                return self._send_json(
                    {
                        "ok": True,
                        "domanda": domanda,
                        "risposta": risposta,
                        "motore": esito["motore"],
                        "modello_usato": esito["modello_usato"],
                        "complessita": esito["complessita"],
                        "motivo_routing": esito["motivo_routing"],
                        "durata_ms": esito["durata_ms"],
                        "fonti": [nome for nome, _ in fonti],
                        "record": record,
                        "cronologia": leggi_cronologia_con_instradamento(),
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


# Alias per retrocompatibilità
ModelloOpenAIHandler = InvestigatoreHTTPHandler


def avvia_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Avvia il server HTTP per il Frontend e l'API REST."""
    server = ThreadingHTTPServer((host, port), InvestigatoreHTTPHandler)
    print(f"Server Investigatore AI attivo su http://{host}:{port}/")
    print(f"Scrivi una domanda alla volta. Digita '{COMANDO_USCITA}' per terminare.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProgramma terminato.")
        server.server_close()


if __name__ == "__main__":
    porta = int(valore_env("PORT", "8000"))
    avvia_server(port=porta)

