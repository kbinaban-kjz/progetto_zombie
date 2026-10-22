"""
Backend/server.py — Server HTTP e API REST per l'interfaccia Web (Frontend).

Responsabilità:
- Servire i file statici del Frontend (HTML, CSS, JS) e della mappa.
- Esporre gli endpoint REST:
    GET  /api/status         -> Stato del sistema, modelli e chiavi
    GET  /api/history        -> Cronologia completa salvata in SQLite
    POST /api/history/clear  -> Rimuove tutta la cronologia da SQLite
    DELETE /api/history      -> Rimuove tutta la cronologia da SQLite
    GET  /api/sources        -> Elenco e contenuto delle fonti del dossier
    GET  /api/vector-sources -> Archivio completo (anche HTML/WIKI) per lo spazio vettoriale
    GET  /api/tools          -> Catalogo degli strumenti operativi disponibili
    POST /api/chat           -> Esecuzione query ibrida (Locale vs Cloud)
    POST /api/tools/execute  -> Invocazione diretta di un tool da API
"""

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from typing import Any

try:
    from Backend.config import (
        ROOT_DIR,
        MODELLO_LOCALE,
        MODELLO_NVIDIA_DEFAULT,
        MODELLI_NVIDIA_RISERVA,
        MODELLO_GEMINI_DEFAULT,
        MODELLI_GEMINI_RISERVA,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        stato_chiavi_api,
        get_gemini_api_key,
        get_nvidia_api_key,
        get_openai_api_key,
    )
    from Backend.database import (
        leggi_cronologia_con_instradamento,
        salva_con_instradamento,
        cancella_cronologia,
        leggi_ultimi_messaggi,
    )
    from Backend.sources import (
        carica_archivio_completo,
        carica_fonti,
        costruisci_indice_rag,
        costruisci_intelligence_board,
        risolvi_cartella_dati,
        scegli_fonti_dettagliato,
    )
    from Backend.tools import TOOLS_OPENAI_SCHEMA, STRUMENTI_REGISTRATI, esegui_tool, NODI_TEATRO, interroga_database
    from Backend.schema_inspector import estrai_schema_database, leggi_dati_tabella
    from Backend.modello_locale import is_modello_caricato
    from Backend.router import genera_risposta_ibrida
    import Backend.modello_openai as modello_openai
    import Backend.modello_gemini as modello_gemini
except ImportError:
    from config import (
        ROOT_DIR,
        MODELLO_LOCALE,
        MODELLO_NVIDIA_DEFAULT,
        MODELLI_NVIDIA_RISERVA,
        MODELLO_GEMINI_DEFAULT,
        MODELLI_GEMINI_RISERVA,
        ISTRUZIONI,
        DOMANDA_ESEMPIO,
        COMANDO_USCITA,
        valore_env,
        stato_chiavi_api,
        get_gemini_api_key,
        get_nvidia_api_key,
        get_openai_api_key,
    )
    from database import (
        leggi_cronologia_con_instradamento,
        salva_con_instradamento,
        cancella_cronologia,
        leggi_ultimi_messaggi,
    )
    from sources import (
        carica_archivio_completo,
        carica_fonti,
        costruisci_indice_rag,
        costruisci_intelligence_board,
        risolvi_cartella_dati,
        scegli_fonti_dettagliato,
    )
    from tools import TOOLS_OPENAI_SCHEMA, STRUMENTI_REGISTRATI, esegui_tool, NODI_TEATRO, interroga_database
    from schema_inspector import estrai_schema_database, leggi_dati_tabella
    from modello_locale import is_modello_caricato
    from router import genera_risposta_ibrida
    import modello_openai
    import modello_gemini


class InvestigatoreHTTPHandler(SimpleHTTPRequestHandler):
    """Handler HTTP con supporto CORS, API REST e servizio file statici."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path in {"/api/history", "/api/history/clear"}:
            eliminati = cancella_cronologia()
            return self._send_json(
                {
                    "ok": True,
                    "messaggio": f"Cronologia eliminata con successo ({eliminati} record rimossi).",
                    "eliminati": eliminati,
                    "cronologia": [],
                }
            )
        return self._send_json({"ok": False, "error": "Endpoint non trovato."}, status=404)

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

        # Compatibilità percorsi assets: risiede in Frontend/assets/
        if path.startswith("/assets"):
            self.path = "/Frontend" + path
            return super().do_GET()

        # Compatibilità percorsi Spazio Latente RAG 3D: risiede in Frontend/rag3d/
        if path.startswith("/rag3d"):
            self.path = "/Frontend" + path
            return super().do_GET()

        if path in {"/spazio-latente", "/spazio-latente-3d", "/rag-3d"}:
            self.path = "/Frontend/rag3d/index.html"
            return super().do_GET()

        # API: Stato complessivo
        if path == "/api/status":
            fonti = carica_fonti()
            ha_key, provider = stato_chiavi_api()
            chiave_gemini_presente = bool(get_gemini_api_key())
            chiave_nvidia_presente = bool(get_nvidia_api_key())
            chiave_openai_presente = bool(get_openai_api_key())

            if chiave_gemini_presente and not chiave_nvidia_presente:
                modello_default = os.environ.get("GEMINI_MODEL") or MODELLO_GEMINI_DEFAULT
            elif chiave_nvidia_presente:
                modello_default = os.environ.get("NVIDIA_MODEL") or MODELLO_NVIDIA_DEFAULT
            elif chiave_gemini_presente:
                modello_default = os.environ.get("GEMINI_MODEL") or MODELLO_GEMINI_DEFAULT
            else:
                modello_default = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

            return self._send_json(
                {
                    "ok": True,
                    "backend": "Ibrido Modulare (Locale + Gemini + NVIDIA/OpenAI + Tools)",
                    "modello_locale": MODELLO_LOCALE,
                    "modello_locale_caricato": is_modello_caricato(),
                    "chiave_configurata": ha_key,
                    "provider": provider,
                    "chiave_gemini": chiave_gemini_presente,
                    "chiave_nvidia": chiave_nvidia_presente,
                    "chiave_openai": chiave_openai_presente,
                    "modello_gemini_default": MODELLO_GEMINI_DEFAULT,
                    "modelli_gemini_riserva": MODELLI_GEMINI_RISERVA,
                    "modello_default": modello_default,
                    "modelli_nvidia_riserva": MODELLI_NVIDIA_RISERVA,
                    "istruzioni": ISTRUZIONI,
                    "domanda_esempio": DOMANDA_ESEMPIO,
                    "comando_uscita": COMANDO_USCITA,
                    "cartella_dati": str(risolvi_cartella_dati().relative_to(ROOT_DIR)),
                    "file_fonti": [nome for nome, _ in fonti],
                    "tools_disponibili": list(STRUMENTI_REGISTRATI.keys()),
                    "limite_memoria": 6,
                    "memoria_db_attiva": len(leggi_ultimi_messaggi(6)),
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

        # API: Archivio completo (inclusi HTML, JSON, XML e voci WIKI) per lo spazio vettoriale
        if path == "/api/vector-sources":
            nomi_pertinenti = {nome for nome, _ in carica_fonti()}
            return self._send_json(
                {
                    "ok": True,
                    "fonti": [
                        {"nome": nome, "contenuto": contenuto, "pertinente": nome in nomi_pertinenti}
                        for nome, contenuto in carica_archivio_completo()
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

        # API: Lavagna Investigativa & Relazioni ("Collega i Puntini")
        if path in {"/api/board", "/api/intelligence"}:
            board_data = costruisci_intelligence_board()
            return self._send_json(board_data)

        # API: Mappa Tattica del Teatro Operativo
        if path in {"/api/map", "/api/mappa"}:
            return self._send_json(
                {
                    "ok": True,
                    "totale": len(NODI_TEATRO),
                    "nodi": NODI_TEATRO,
                }
            )

        # API: Schema dinamico e Diagramma ER del database accessi.sqlite
        if path in {"/api/database/schema", "/api/schema/accessi", "/api/accessi/schema", "/api/er-diagram"}:
            schema_db = estrai_schema_database()
            return self._send_json(schema_db, status=200 if schema_db.get("ok") else 500)

        # API: Ispezione dati riga di una tabella di accessi.sqlite
        if path == "/api/database/table":
            query_params = parse_qs(urlparse(self.path).query)
            nome_tab = (query_params.get("name", [""])[0] or query_params.get("tabella", [""])[0]).strip()
            limite_val = query_params.get("limit", ["50"])[0]
            offset_val = query_params.get("offset", ["0"])[0]
            limite = int(limite_val) if limite_val.isdigit() else 50
            offset = int(offset_val) if offset_val.isdigit() else 0
            if not nome_tab:
                return self._send_json({"ok": False, "error": "Parametro 'name' mancante."}, status=400)
            dati = leggi_dati_tabella(nome_tab, limite=limite, offset=offset)
            return self._send_json(dati, status=200 if dati.get("ok") else 400)

        # Sicurezza file statici: consenti solo risorse dentro /Frontend/
        norm_path = os.path.normpath(path).replace("\\", "/")
        if ".." in path or not norm_path.startswith("/Frontend/"):
            return self._send_json(
                {"ok": False, "error": "Accesso negato alla risorsa richiesta."},
                status=403,
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

        # API: Cancellazione intera cronologia da SQLite
        if path in {"/api/history/clear", "/api/history/delete"}:
            eliminati = cancella_cronologia()
            return self._send_json(
                {
                    "ok": True,
                    "messaggio": f"Cronologia eliminata con successo ({eliminati} record rimossi).",
                    "eliminati": eliminati,
                    "cronologia": [],
                }
            )

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

        # API: Query diretta di sola lettura su accessi.sqlite per l'ispettore ER
        if path in {"/api/database/query", "/api/accessi/query"}:
            query_sql = (payload.get("query") or payload.get("sql") or "").strip()
            if not query_sql:
                return self._send_json({"ok": False, "error": "Query SQL mancante."}, status=400)
            res = interroga_database(query_sql)
            if "errore" in res:
                return self._send_json({"ok": False, "error": res["errore"]}, status=400)
            return self._send_json(
                {
                    "ok": True,
                    "query": query_sql,
                    "colonne": res.get("colonne", []),
                    "righe": res.get("righe", []),
                    "altre_righe": res.get("altre_righe", False),
                }
            )

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
                visti: set[str] = set()
                fonti = []
                for f in fonti_payload:
                    nome_f = str(f.get("nome", ""))
                    contenuto_f = str(f.get("contenuto", ""))
                    if nome_f and contenuto_f and nome_f not in visti:
                        visti.add(nome_f)
                        fonti.append((nome_f, contenuto_f))
            else:
                fonti = carica_fonti()

            api_key = (payload.get("api_key") or "").strip() or None
            modello = (payload.get("modello") or "").strip() or None
            modalita = (payload.get("modalita") or "auto").strip().lower()
            usa_tools = bool(payload.get("usa_tools", True))
            memoria = payload.get("memoria")

            try:
                esito = genera_risposta_ibrida(
                    domanda,
                    fonti,
                    api_key=api_key,
                    modello=modello,
                    modalita=modalita,
                    usa_tools=usa_tools,
                    memoria=memoria,
                )
                risposta = esito["risposta"]
                fonti_citate = esito.get("fonti_citate") or []
                file_rag = esito.get("file_recuperati_rag") or []
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
                        "memoria_usata": esito.get("memoria_usata", 0),
                        "fonti": fonti_citate,
                        "file_recuperati_rag": file_rag,
                        "collegamenti": esito.get("collegamenti", []),
                        "percorso_collegamento": esito.get("percorso_collegamento"),
                        "dettagli_rag": esito.get("dettagli_rag", []),
                        "fonti_disponibili": [nome for nome, _ in fonti],
                        "grounding_ok": esito.get("grounding_ok", True),
                        "record": record,
                        "cronologia": leggi_cronologia_con_instradamento(),
                    }
                )
            except modello_gemini.GeminiAuthError as errore:
                return self._send_json(
                    {
                        "ok": False,
                        "error": str(errore) or "Google Gemini non ha accettato la chiave API. Controlla GEMINI_API_KEY in .env.",
                    },
                    status=401,
                )
            except modello_gemini.GeminiQuotaError as errore:
                return self._send_json(
                    {
                        "ok": False,
                        "error": str(errore) or "Quota o rate limit superato per Google Gemini.",
                    },
                    status=429,
                )
            except (modello_gemini.GeminiConnectionError, modello_gemini.GeminiError) as errore:
                return self._send_json(
                    {
                        "ok": False,
                        "error": f"Errore Google Gemini: {errore}",
                    },
                    status=502,
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
