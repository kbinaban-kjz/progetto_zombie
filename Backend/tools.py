"""
Backend/tools.py — Strumenti (Tools) operativi invocabili dall'AI e dall'Investigatore.

Responsabilità:
- Implementazione delle funzioni investigative (analisi fonti, mappa, nodi, database SQLite).
- Esposizione degli schemi OpenAI Function Calling (TOOLS_OPENAI_SCHEMA) per i modelli cloud.
- Dispatcher per l'esecuzione dinamica e sicura degli strumenti (esegui_tool).
"""

import json
from typing import Any

try:
    from Backend.database import cerca_in_cronologia, leggi_cronologia
    from Backend.sources import carica_fonti, estrai_metadati_fonte, cerca_in_fonti
except ImportError:
    from database import cerca_in_cronologia, leggi_cronologia
    from sources import carica_fonti, estrai_metadati_fonte, cerca_in_fonti

# ==============================================================================
# DATASET DEL TEATRO OPERATIVO (Mappa e Nodi Protocollo Lazzaro)
# ==============================================================================
NODI_TEATRO = [
    {
        "id": "laz01",
        "code": "LAZ-01",
        "name": "La Centrale",
        "place": "Ravenna",
        "region": "Emilia-Romagna, IT",
        "type": "bunker",
        "status": "OPERATIVO",
        "threat": 2,
        "survivors": "214",
        "contact": "T-00:00",
        "source": "G1-01",
        "reliability": 92,
        "tags": ["COMANDO", "RIPETITORE", "LIVELLO 4"],
        "desc": "Bunker di comando dell'Operazione Silenzio, scavato sotto la costa adriatica. Da qui la centrale diffonde ordini e coordinate dei rifugi. Ogni messaggio arriva identico, con la stessa pausa di tre secondi.",
    },
    {
        "id": "ferri",
        "code": "ECO-07",
        "name": "Ultima Voce",
        "place": "Appennino Tosco-Emiliano",
        "region": "Italia",
        "type": "signal",
        "status": "SEGNALE INTERROTTO",
        "threat": 4,
        "survivors": "??",
        "contact": "T-04:37",
        "source": "G1-02",
        "reliability": 64,
        "tags": ["NORA FERRI", "REGISTRI", "FREQ. 87.4"],
        "desc": "L'ultima trasmissione di Nora Ferri si spegne su questa frequenza. La voce ordina di conservare i registri originali, poi il silenzio. Il ripetitore è ancora alimentato, ma nessuno risponde.",
    },
    {
        "id": "genova",
        "code": "GEN-07",
        "name": "Porto Sigillato",
        "place": "Genova",
        "region": "Liguria, IT",
        "type": "outbreak",
        "status": "PERIMETRO VIOLATO",
        "threat": 5,
        "survivors": "0",
        "contact": "T-01:12",
        "source": "LOG-017",
        "reliability": 88,
        "tags": ["MOLO 7", "QUARANTENA", "DRONI PERSI: 2"],
        "desc": "Il porto è caduto nella notte del Giorno 12. I container sul molo 7 sono stati aperti dall'interno. I droni di ricognizione non trasmettono più.",
    },
    {
        "id": "milano",
        "code": "MIL-12",
        "name": "Corridoio Nord",
        "place": "Milano",
        "region": "Lombardia, IT",
        "type": "outbreak",
        "status": "SILENZIO RADIO",
        "threat": 4,
        "survivors": "12",
        "contact": "T-09:51",
        "source": "LOG-114",
        "reliability": 41,
        "tags": ["CITTÀ VUOTA", "EVACUAZIONE", "NO RIENTRO"],
        "desc": "Il corridoio nord è una città vuota. Le radio ripetono un avviso di evacuazione registrato tre settimane fa. Le squadre di recupero non sono mai rientrate.",
    },
    {
        "id": "roma",
        "code": "LAB-04",
        "name": "Ceppo LZ-7",
        "place": "Roma",
        "region": "Lazio, IT",
        "type": "anomaly",
        "status": "QUARANTENA TOTALE",
        "threat": 5,
        "survivors": "0",
        "contact": "T-02:08",
        "source": "LOG-220",
        "reliability": 77,
        "tags": ["CAMPIONI", "CIFRATO", "ACCESSO NEGATO"],
        "desc": "Il Lab-04 custodisce i campioni del ceppo LZ-7. La quarantena è totale e le comunicazioni passano solo su canale cifrato. Nessun registro è stato reso pubblico.",
    },
    {
        "id": "berlino",
        "code": "BER-07",
        "name": "Muro 7",
        "place": "Berlino",
        "region": "Germania",
        "type": "bunker",
        "status": "FILTRO ATTIVO",
        "threat": 3,
        "survivors": "682",
        "contact": "T-00:41",
        "source": "LOG-078",
        "reliability": 95,
        "tags": ["TRANSITO", "CAPACENZA 91%", "FILTRO SANITARIO"],
        "desc": "Muro 7 è il filtro più grande d'Europa: 682 superstiti registrati e una lista d'attesa che non scorre. Il perimetro tiene, ma il morale no.",
    },
    {
        "id": "londra",
        "code": "LON-00",
        "name": "Zona 0",
        "place": "Londra",
        "region": "Regno Unito",
        "type": "outbreak",
        "status": "BLACKOUT TOTALE",
        "threat": 5,
        "survivors": "??",
        "contact": "T-11:23",
        "source": "LOG-301",
        "reliability": 12,
        "tags": ["BLACKOUT", "SOTTOSUOLO", "ULTIMO SEGNALE"],
        "desc": "Zona 0 è al buio da undici ore. Il blackout ha cancellato telecamere, sensori e la maggior parte delle comunicazioni. L'ultimo segnale parlava di 'movimento sotto la città'.",
    },
    {
        "id": "mosca",
        "code": "SIL-12",
        "name": "Silo 12",
        "place": "Mosca",
        "region": "Federazione Russa",
        "type": "anomaly",
        "status": "SIGILLATO",
        "threat": 3,
        "survivors": "48",
        "contact": "T-06:15",
        "source": "LOG-052",
        "reliability": 83,
        "tags": ["ARCHIVIO", "CRIOGENICO", "PING / 90 MIN"],
        "desc": "Il Silo 12 conserva campioni criogenici e registri della prima settimana. È sigillato dall'interno. L'unica cosa che esce è un ping ogni novanta minuti.",
    },
    {
        "id": "newyork",
        "code": "NYC-03",
        "name": "Quarantena Portuale",
        "place": "New York",
        "region": "Stati Uniti",
        "type": "outbreak",
        "status": "NESSUN PRESIDIO",
        "threat": 5,
        "survivors": "0",
        "contact": "T-03:30",
        "source": "LOG-198",
        "reliability": 58,
        "tags": ["NAVI ALLA FONDA", "RUMORE RITMICO", "ACCESSO CHIUSO"],
        "desc": "La quarantena portuale non è più presidiata. Le navi all'ancora formano una linea di galleggianti vuoti. Dagli scali arriva un rumore metallico ritmico.",
    },
    {
        "id": "saopaolo",
        "code": "SAO-09",
        "name": "Cluster Mutazione",
        "place": "San Paolo",
        "region": "Brasile",
        "type": "anomaly",
        "status": "OSSERVAZIONE",
        "threat": 4,
        "survivors": "??",
        "contact": "T-07:44",
        "source": "LOG-260",
        "reliability": 46,
        "tags": ["MUTAZIONE", "COORDINAZIONE", "ZONA SUD"],
        "desc": "Un cluster di mutazione è emerso nella zona sud. Gli infetti mostrano una coordinazione che non dovrebbero avere. La zona è in osservazione, non in contenimento.",
    },
    {
        "id": "tokyo",
        "code": "HAK-01",
        "name": "Porto Haku",
        "place": "Tokyo",
        "region": "Giappone",
        "type": "bunker",
        "status": "RIFUGIO APERTO",
        "threat": 2,
        "survivors": "1.204",
        "contact": "T-00:12",
        "source": "LOG-410",
        "reliability": 98,
        "tags": ["EVACUAZIONE", "FILTRI ATTIVI", "PARTENZE"],
        "desc": "Il porto Haku è uno dei pochi rifugi ancora aperti. 1.204 superstiti, filtri sanitari attivi e una lista di partenze che non basta mai.",
    },
    {
        "id": "cairo",
        "code": "CAI-05",
        "name": "Rotta Sud",
        "place": "Il Cairo",
        "region": "Egitto",
        "type": "signal",
        "status": "SEGNALE DEBOLE",
        "threat": 3,
        "survivors": "530",
        "contact": "T-02:56",
        "source": "LOG-333",
        "reliability": 71,
        "tags": ["NILO", "CONVOGLI", "VALICO ASSUAN"],
        "desc": "La rotta sud lungo il Nilo regge, ma il segnale è debole. I convogli viaggiano di notte. L'ultimo messaggio chiede rinforzi per il valico di Assuan.",
    },
    {
        "id": "sydney",
        "code": "DAG-02",
        "name": "Rifugio Dago",
        "place": "Sydney",
        "region": "Australia",
        "type": "bunker",
        "status": "ISOLATO",
        "threat": 1,
        "survivors": "890",
        "contact": "T-05:19",
        "source": "LOG-120",
        "reliability": 90,
        "tags": ["AUTONOMO", "ACQUA 8 MESI", "NO CONTATTO"],
        "desc": "Il rifugio Dago è operativo e isolato. 890 superstiti, acqua e energia per otto mesi. Il comandante ha sospeso ogni contatto con la centrale.",
    },
    {
        "id": "echo",
        "code": "ECH-00",
        "name": "Stazione Echo",
        "place": "Mare di Ross",
        "region": "Antartide",
        "type": "anomaly",
        "status": "TRASMISSIONE ATTIVA",
        "threat": 5,
        "survivors": "0",
        "contact": "T-00:03",
        "source": "G1-03",
        "reliability": 33,
        "tags": ["SOTTO IL GHIACCIO", "PAUSA 3.0 S", "ORIGINE IGNOTA"],
        "desc": "Sotto il ghiaccio del Mare di Ross, un ripetitore trasmette il messaggio della centrale. La pausa è identica: tre secondi. Non è chiaro chi — o cosa — lo stia alimentando.",
    },
]


# ==============================================================================
# IMPLEMENTAZIONE DEI TOOL
# ==============================================================================

def cerca_fonti(query: str, limite: int = 5) -> dict[str, Any]:
    """
    Cerca termini o concetti chiave all'interno dei documenti del dossier.
    Restituisce i brani più rilevanti e il file di provenienza.
    """
    fonti = carica_fonti()
    risultati = cerca_in_fonti(query, fonti)
    return {
        "ok": True,
        "query": query,
        "trovati": len(risultati),
        "risultati": risultati[:limite],
    }


def leggi_fonte(nome_file: str) -> dict[str, Any]:
    """
    Restituisce il testo completo e i dettagli di un documento specifico (es. 'G1-01.txt').
    """
    fonti = carica_fonti()
    mappa = {n.lower(): (n, t) for n, t in fonti}
    chiave = nome_file.strip().lower()
    if not chiave.endswith(".txt"):
        chiave += ".txt"

    if chiave in mappa:
        nome_reale, testo = mappa[chiave]
        meta = estrai_metadati_fonte(nome_reale, testo)
        return {
            "ok": True,
            "file": nome_reale,
            "id": meta["id"],
            "titolo": meta["titolo"],
            "testo": testo,
        }
    return {
        "ok": False,
        "error": f"Documento '{nome_file}' non trovato nel dossier.",
        "file_disponibili": [n for n, _ in fonti],
    }


def elenca_fonti() -> dict[str, Any]:
    """
    Elenca tutti i documenti attualmente disponibili nel dossier con metadati riassuntivi.
    """
    fonti = carica_fonti()
    elenco = []
    for nome, testo in fonti:
        meta = estrai_metadati_fonte(nome, testo)
        elenco.append(
            {
                "file": nome,
                "id": meta["id"],
                "titolo": meta["titolo"],
                "anteprima": meta["corpo"][:120] + "...",
                "caratteri": len(testo),
            }
        )
    return {"ok": True, "totale": len(elenco), "fonti": elenco}


def ottieni_nodi_mappa(tipo: str | None = None, min_threat: int = 0) -> dict[str, Any]:
    """
    Restituisce i nodi strategici della mappa operativa Protocollo Lazzaro
    (bunker, focolai, segnali, anomalie).
    """
    nodi_filtrati = []
    tipo_filtro = tipo.strip().lower() if tipo else None

    for nodo in NODI_TEATRO:
        if tipo_filtro and nodo["type"].lower() != tipo_filtro:
            continue
        if nodo.get("threat", 0) < min_threat:
            continue
        nodi_filtrati.append(nodo)

    return {
        "ok": True,
        "totale": len(nodi_filtrati),
        "filtro_tipo": tipo,
        "min_threat": min_threat,
        "nodi": nodi_filtrati,
    }


def ottieni_dettaglio_nodo(id_o_codice: str) -> dict[str, Any]:
    """
    Restituisce l'analisi di intelligence dettagliata di un nodo della mappa
    (es. 'laz01', 'ferri', 'echo', 'berlino', 'LAZ-01').
    """
    chiave = id_o_codice.strip().lower()
    for nodo in NODI_TEATRO:
        if (
            nodo["id"].lower() == chiave
            or nodo["code"].lower() == chiave
            or nodo["name"].lower() == chiave
        ):
            return {"ok": True, "nodo": nodo}

    return {
        "ok": False,
        "error": f"Nodo '{id_o_codice}' non trovato nel teatro operativo.",
        "nodi_noti": [f"{n['id']} ({n['name']})" for n in NODI_TEATRO],
    }


def cerca_cronologia(termine: str) -> dict[str, Any]:
    """
    Cerca tra le domande e risposte registrate nel database SQLite locale.
    """
    risultati = cerca_in_cronologia(termine)
    return {
        "ok": True,
        "termine": termine,
        "trovati": len(risultati),
        "cronologia": risultati,
    }


def statistiche_missione() -> dict[str, Any]:
    """
    Restituisce un quadro di sintesi sullo stato della missione, fonti e database.
    """
    fonti = carica_fonti()
    cronologia = leggi_cronologia()
    return {
        "ok": True,
        "missione": "Operazione Silenzio — Protocollo Lazzaro",
        "fonti_dossier": len(fonti),
        "file_dossier": [n for n, _ in fonti],
        "nodi_teatro_mappa": len(NODI_TEATRO),
        "record_sqlite_chat": len(cronologia),
        "tipi_nodi": {
            "bunker": sum(1 for n in NODI_TEATRO if n["type"] == "bunker"),
            "outbreak": sum(1 for n in NODI_TEATRO if n["type"] == "outbreak"),
            "signal": sum(1 for n in NODI_TEATRO if n["type"] == "signal"),
            "anomaly": sum(1 for n in NODI_TEATRO if n["type"] == "anomaly"),
        },
    }


# ==============================================================================
# REGISTRO STRUMENTI E SCHEMI PER OPENAI FUNCTION CALLING
# ==============================================================================

STRUMENTI_REGISTRATI: dict[str, Any] = {
    "cerca_fonti": cerca_fonti,
    "leggi_fonte": leggi_fonte,
    "elenca_fonti": elenca_fonti,
    "ottieni_nodi_mappa": ottieni_nodi_mappa,
    "ottieni_dettaglio_nodo": ottieni_dettaglio_nodo,
    "cerca_cronologia": cerca_cronologia,
    "statistiche_missione": statistiche_missione,
}

TOOLS_OPENAI_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "cerca_fonti",
            "description": "Cerca parole chiave, testimonianze o frasi nei documenti ufficiali del dossier (dati/*.txt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Termine o frase da cercare nei documenti (es. 'Nora Ferri', 'registri', 'pausa').",
                    },
                    "limite": {
                        "type": "integer",
                        "description": "Numero massimo di riscontri da restituire (default 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leggi_fonte",
            "description": "Recupera il contenuto integrale di un file di testimonianza specifico (es. 'G1-01.txt', 'G1-02.txt', 'G1-03.txt').",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_file": {
                        "type": "string",
                        "description": "Il nome del file da leggere (es. 'G1-02.txt').",
                    }
                },
                "required": ["nome_file"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "elenca_fonti",
            "description": "Elenca tutti i file di testimonianze presenti nel dossier con identificativi e titoli.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ottieni_nodi_mappa",
            "description": "Interroga la mappa tattica globale per ottenere informazioni sui 14 nodi di rete (bunker, focolai, segnali radio, anomalie).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {
                        "type": "string",
                        "description": "Tipo di nodo da filtrare: 'bunker', 'outbreak', 'signal', 'anomaly'.",
                        "enum": ["bunker", "outbreak", "signal", "anomaly"],
                    },
                    "min_threat": {
                        "type": "integer",
                        "description": "Livello minimo di minaccia (da 1 a 5).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ottieni_dettaglio_nodo",
            "description": "Recupera il fascicolo di intelligence completo su un nodo specifico della mappa (es. 'laz01' / Centrale, 'ferri' / Nora Ferri, 'echo').",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_o_codice": {
                        "type": "string",
                        "description": "ID o codice del nodo (es. 'laz01', 'ferri', 'echo', 'roma', 'berlino').",
                    }
                },
                "required": ["id_o_codice"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cerca_cronologia",
            "description": "Cerca nel database SQLite locale domande e risposte passate dell'investigatore.",
            "parameters": {
                "type": "object",
                "properties": {
                    "termine": {
                        "type": "string",
                        "description": "Parola chiave da cercare nelle sessioni precedenti.",
                    }
                },
                "required": ["termine"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "statistiche_missione",
            "description": "Restituisce un resoconto globale sullo stato della missione, fonti caricate e nodi operativi.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def esegui_tool(nome: str, argomenti: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """
    Esegue in modo sicuro un tool registrato per nome, parsando gli argomenti se forniti come stringa JSON.
    """
    if nome not in STRUMENTI_REGISTRATI:
        return {
            "ok": False,
            "error": f"Tool '{nome}' sconosciuto. Strumenti disponibili: {list(STRUMENTI_REGISTRATI.keys())}",
        }

    funzione = STRUMENTI_REGISTRATI[nome]

    # Parsing degli argomenti se sono una stringa JSON
    args_dict: dict[str, Any] = {}
    if isinstance(argomenti, str):
        try:
            args_dict = json.loads(argomenti) if argomenti.strip() else {}
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"Argomenti JSON non validi per '{nome}': {exc}"}
    elif isinstance(argomenti, dict):
        args_dict = argomenti

    try:
        esito = funzione(**args_dict)
        return esito
    except TypeError as err:
        return {"ok": False, "error": f"Parametri non validi per il tool '{nome}': {err}"}
    except Exception as exc:
        return {"ok": False, "error": f"Errore durante l'esecuzione del tool '{nome}': {exc}"}


if __name__ == "__main__":
    print("=== Test Strumenti AI (tools.py) ===")
    print("1. statistiche_missione():", statistiche_missione())
    print("2. cerca_fonti('Nora Ferri'):", cerca_fonti("Nora Ferri"))
    print("3. ottieni_dettaglio_nodo('ferri'):", ottieni_dettaglio_nodo("ferri"))
    print("4. esegui_tool('elenca_fonti'):", esegui_tool("elenca_fonti"))

