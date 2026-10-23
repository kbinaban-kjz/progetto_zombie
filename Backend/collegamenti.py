"""
Backend/collegamenti.py — Collegamenti trasversali tra documenti (entità-ponte).

Responsabilità:
- Estrarre da ogni documento le entità che possono fare da ponte tra fonti diverse:
  codici (RV753, M562, K591, EV-541, CN-58...), nomi propri (Nora Ferri, Forte Cenere,
  San Mauro...), acronimi (LUME) e orari.
- Costruire un grafo documento <-> entità e ricavare:
  * i collegamenti diretti tra i documenti recuperati (con l'entità condivisa);
  * il percorso più breve tra due entità citate nella domanda (es. Nora Ferri -> LUME).
- Fornire un blocco testuale compatto da passare al modello, così i collegamenti sono
  verificabili e non inventati.

Il modulo non importa altri moduli del progetto: lavora solo su coppie (nome_file, testo)
e può essere usato sia dal RAG sia dal risponditore locale e dai modelli cloud.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Sequence

# ==============================================================================
# ESTRAZIONE ENTITÀ
# ==============================================================================
_RE_CODICE = re.compile(r"(?<![\w-])([A-Za-z]{1,5}[-_]?\d{2,6}(?:[-_]\d+)?)(?![\w-])")
_RE_SETTORE = re.compile(r"\bsettore\s+([A-Za-z]\d)\b", re.IGNORECASE)
_RE_NOME_COMPOSTO = re.compile(r"\b([A-Z][a-zàèéìòù]+(?:\s+[A-Z][a-zàèéìòù]+)+)\b")
_RE_PAROLA_MAIUSCOLA = re.compile(r"\b([A-Z][a-zàèéìòù]{2,})\b")
_RE_ACRONIMO = re.compile(r"\b([A-Z]{3,10})\b")
_RE_ORARIO = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")

# Parole troppo generiche: non sono entità-ponte.
_PAROLE_NON_ENTITA = {
    "il", "lo", "la", "i", "gli", "le", "un", "una", "uno", "di", "da", "in", "con",
    "su", "per", "tra", "fra", "del", "della", "dei", "delle", "dello", "degli",
    "al", "alla", "alle", "ai", "nel", "nella", "nei", "nelle", "sul", "sulla",
    "che", "chi", "cosa", "dove", "quando", "come", "quale", "quali", "quanto",
    "sono", "era", "erano", "stato", "stata", "stati", "state", "ha", "hanno",
    "non", "più", "piu", "anche", "questo", "questa", "questi", "queste",
    "quello", "quella", "documento", "documenti", "file", "fonte", "fonti",
    "dossier", "testo", "nota", "note", "titolo", "id", "ore", "giorno",
    "giorni", "operativo", "operativa", "primo", "prima", "secondo", "seconda",
    "ultimo", "ultima", "nuovo", "nuova", "vecchio", "vecchia", "dopo", "entro",
    "circa", "alle", "agli", "dalle", "dal", "dallo", "dai", "questo", "stesso",
    "stessa", "altri", "altre", "altro", "altra", "solo", "senza", "sopra",
    "sotto", "presso", "verso", "durante", "secondo", "secondo", "essere",
    "avere", "fare", "detto", "dice", "dicono", "riporta", "riportato",
    "riportata", "registro", "registri", "scheda", "schede", "verbale",
    "circolare", "planimetria", "appunto", "trasferimento", "consegna",
    "messaggio", "trasmissione", "centrale", "unità", "unita", "squadra",
    "protocollo", "progetto", "materiale", "contenitore", "custodia",
    "laboratorio", "deposito", "settore", "armadio", "pratica", "lotto",
    "corriere", "ripetitore", "circuito", "segnale", "radio", "rete",
    "bollettino", "misura", "misure", "collaudo", "rettifica", "copia",
    "copie", "inoltro", "origine", "verifica", "controllo", "allarme",
    "focolaio", "contagio", "rifugio", "rifugi", "persone", "persona",
    "nome", "civile", "destinazione", "contenuto", "autorizzazione",
    "database", "accessi", "validità", "validita", "valida", "valido",
    "ufficio", "servizio", "interno", "interna", "originale", "originali",
    "senza", "firma", "firmato", "firmata", "anonimo", "anonima",
    "archivio", "wiki", "wikipedia", "ricevuta", "collocazione", "officina",
    "forte", "punto", "raccolta", "invio", "alimentazione", "presente",
    "assente", "riuscito", "fallito", "nuove", "nuovi", "dati", "dato",
    "portate", "portatelo", "fermate", "inviatelo", "aprite",
}

_ACRONIMI_NON_ENTITA = {
    "ID", "TXT", "HTML", "JSON", "XML", "PDF", "URL", "API", "GPS", "UTC",
    "OK", "KO", "NORD", "SUD", "EST", "OVEST", "TUTTI", "TUTTE", "NON",
    "ARCH", "WIKI", "LX", "G", "EV", "CN", "RV", "PT", "SL",
}

# Righe di metadati che non sono frasi di prova.
_RE_METADATO = re.compile(r"^(?:id|title|text|source|license)\s*:", re.IGNORECASE)


def _normalizza_entita(testo: str) -> str:
    """Forma canonica usata per confrontare la stessa entità in documenti diversi."""
    return re.sub(r"\s+", " ", testo.strip().lower().replace("_", "-"))


def estrai_entita(testo: str) -> dict[str, set[str]]:
    """
    Estrae codici, nomi propri, acronimi e orari da un testo.
    Restituisce valori normalizzati (minuscolo) pronti per il confronto.
    """
    codici: set[str] = set()
    for m in _RE_CODICE.finditer(testo or ""):
        cod = m.group(1).upper().replace("_", "-")
        # Esclude parole comuni scambiate per codici (es. "DI2") e anni isolati.
        if any(c.isdigit() for c in cod):
            codici.add(_normalizza_entita(cod))

    for m in _RE_SETTORE.finditer(testo or ""):
        codici.add(_normalizza_entita(f"settore {m.group(1).upper()}"))
        codici.add(_normalizza_entita(m.group(1).upper()))

    nomi: set[str] = set()
    for m in _RE_NOME_COMPOSTO.finditer(testo or ""):
        nome = _normalizza_entita(m.group(1))
        if nome not in _PAROLE_NON_ENTITA and len(nome) > 4:
            nomi.add(nome)
    for m in _RE_PAROLA_MAIUSCOLA.finditer(testo or ""):
        parola = _normalizza_entita(m.group(1))
        if parola not in _PAROLE_NON_ENTITA and len(parola) > 3:
            nomi.add(parola)
    for m in _RE_ACRONIMO.finditer(testo or ""):
        acronimo = m.group(1).upper()
        if acronimo not in _ACRONIMI_NON_ENTITA and len(acronimo) >= 3:
            nomi.add(_normalizza_entita(acronimo))

    orari = {o for o in _RE_ORARIO.findall(testo or "")}
    return {"codici": codici, "nomi": nomi, "orari": orari}


def estrai_id_documento(nome_file: str, testo: str) -> str:
    """Ricava l'ID leggibile del documento (ARCH-3097, G2-01, LX5-2775...).

    Gestisce i quattro formati dell'archivio: TXT (ID G2-01), HTML (<b>id</b>),
    JSON ("id": ...), XML (<id>...</id>) e le righe normalizzate "id: ...".
    """
    testo = testo or ""
    pattern = (
        r"(?im)(?:^|\n)\s*(?:id|documento:?)\s*[:=]?\s*([A-Za-z0-9_-]+)\s*$",
        r"(?i)<b>id</b>\s*:\s*([A-Za-z0-9_-]+)",
        r'(?i)"id"\s*:\s*"([A-Za-z0-9_-]+)"',
        r"(?i)<id>\s*([A-Za-z0-9_-]+)\s*</id>",
    )
    for espressione in pattern:
        m = re.search(espressione, testo)
        if m:
            return m.group(1).upper().replace("_", "-")
    return nome_file.rsplit(".", 1)[0].upper().replace("_", "-")


def _frasi(testo: str) -> list[str]:
    """Spezza il testo in frasi, mantenendo la punteggiatura finale."""
    pezzi = re.split(r"(?<=[.!?;])\s+|\n+", (testo or "").strip())
    return [
        p.strip()
        for p in pezzi
        if p and p.strip() and not _RE_METADATO.match(p.strip())
    ]


def frase_con_entita(testo: str, entita: str) -> str:
    """Restituisce la frase più breve che contiene l'entità (per mostrare la prova)."""
    target = _normalizza_entita(entita)
    candidate = [f for f in _frasi(testo) if target in _normalizza_entita(f)]
    if not candidate:
        return ""
    # Preferisce una frase di contenuto, non una riga di intestazione, e non troppo lunga.
    candidate.sort(key=lambda f: (len(f) < 25, len(f) > 320, len(f)))
    return candidate[0]


def _entita_in_domanda(domanda: str, entita_note: set[str]) -> list[str]:
    """
    Individua le entità del corpus citate nella domanda, dalle più specifiche alle più generiche.
    Evita i falsi positivi (es. 'lume' dentro 'volume') usando i confini di parola.
    """
    q = _normalizza_entita(domanda)
    trovate: list[str] = []
    for ent in sorted(entita_note, key=len, reverse=True):
        if len(ent) < 3:
            continue
        pattern = rf"(?<![\w-]){re.escape(ent)}(?![\w-])"
        if re.search(pattern, q):
            # Scarta entità contenute in una già trovata (es. 'cenere' dentro 'forte cenere')
            if not any(ent != altra and ent in altra for altra in trovate):
                trovate.append(ent)
    return trovate


def _score_entita(entita: str, documenti: int, domanda: str) -> float:
    """Entità rare e citate nella domanda valgono di più; le entità onnipresenti valgono poco."""
    if documenti <= 0:
        return 0.0
    score = 1.0 / documenti
    if _normalizza_entita(entita) in _normalizza_entita(domanda):
        score += 2.0
    return score


# ==============================================================================
# INDICE E COLLEGAMENTI
# ==============================================================================
def costruisci_indice(fonti: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """
    Costruisce l'indice documento -> entità e entità -> documenti.
    Deduplica per nome file preservando l'ordine di arrivo (che riflette la rilevanza RAG).
    """
    documenti: dict[str, dict[str, Any]] = {}
    entita_documenti: dict[str, set[str]] = {}
    fonti_utili = list(fonti)
    # Le voci enciclopediche non fanno parte del dossier investigativo: non devono
    # creare collegamenti (sono rumore). Si tengono solo se la richiesta è tutta su WIKI.
    contiene_dossier = any(
        not estrai_id_documento(n, t).upper().startswith("WIKI-") for n, t in fonti_utili
    )
    for nome, testo in fonti_utili:
        if nome in documenti:
            continue
        doc_id = estrai_id_documento(nome, testo)
        if contiene_dossier and doc_id.upper().startswith("WIKI-"):
            continue
        dati = estrai_entita(testo)
        entita = set(dati["codici"]) | set(dati["nomi"]) | set(dati["orari"])
        documenti[nome] = {
            "file": nome,
            "id": doc_id,
            "testo": testo,
            "entita": entita,
        }
        for ent in entita:
            entita_documenti.setdefault(ent, set()).add(nome)
    return {
        "documenti": documenti,
        "entita_documenti": entita_documenti,
        "entita_note": set(entita_documenti),
    }


def collegamenti_tra_documenti(
    fonti: Sequence[tuple[str, str]],
    domanda: str = "",
    limite: int = 12,
    max_documenti_per_entita: int = 25,
) -> list[dict[str, Any]]:
    """
    Elenca i collegamenti tra i documenti recuperati: ogni collegamento è dato da un'entità
    che compare testualmente in entrambi i documenti. Le entità troppo comuni (presenti in
    decine di file) vengono escluse perché non distinguono una relazione.
    """
    indice = costruisci_indice(fonti)
    documenti = indice["documenti"]
    entita_documenti = indice["entita_documenti"]
    nomi = list(documenti.keys())

    collegamenti: list[dict[str, Any]] = []
    for i in range(len(nomi)):
        for j in range(i + 1, len(nomi)):
            f1, f2 = nomi[i], nomi[j]
            e1 = documenti[f1]["entita"]
            e2 = documenti[f2]["entita"]
            comuni = [
                e for e in (e1 & e2)
                if len(entita_documenti.get(e, ())) <= max_documenti_per_entita
            ]
            if not comuni:
                continue
            comuni.sort(key=lambda e: _score_entita(e, len(entita_documenti[e]), domanda), reverse=True)
            peso = sum(_score_entita(e, len(entita_documenti[e]), domanda) for e in comuni)
            collegamenti.append(
                {
                    "da": f1,
                    "a": f2,
                    "id_da": documenti[f1]["id"],
                    "id_a": documenti[f2]["id"],
                    "entita": comuni,
                    "peso": round(peso, 3),
                }
            )
    collegamenti.sort(key=lambda c: c["peso"], reverse=True)
    return collegamenti[:limite]


def percorso_collegamento(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    max_profondita: int = 3,
    max_documenti_per_entita: int = 15,
    max_nodi: int = 300,
) -> dict[str, Any] | None:
    """
    Cerca il percorso più breve tra due entità citate nella domanda, passando per documenti
    che condividono codici, nomi o orari. Restituisce None se non esiste un collegamento
    documentato (meglio nessuna risposta che un collegamento inventato).
    """
    indice = costruisci_indice(fonti)
    documenti = indice["documenti"]
    entita_documenti = indice["entita_documenti"]
    bersagli = _entita_in_domanda(domanda, indice["entita_note"])
    if len(bersagli) < 2:
        return None

    partenza, arrivo = bersagli[0], bersagli[1]
    # Un doc può contenere più entità della domanda: in tal caso il percorso ha un solo nodo.
    docs_partenza = entita_documenti.get(partenza, set())
    docs_arrivo = entita_documenti.get(arrivo, set())
    if not docs_partenza or not docs_arrivo:
        return None

    comuni = docs_partenza & docs_arrivo
    if comuni:
        f = sorted(comuni)[0]
        return {
            "entita_partenza": partenza,
            "entita_arrivo": arrivo,
            "passi": [{"file": f, "id": documenti[f]["id"], "ponte": partenza, "prova": frase_con_entita(documenti[f]["testo"], partenza)}],
        }

    # BFS documento -> entità -> documento.
    coda: deque[tuple[str, list[dict[str, Any]]]] = deque()
    visti: set[str] = set()
    for f in sorted(docs_partenza):
        if f in documenti:
            visti.add(f)
            coda.append((f, [{"file": f, "id": documenti[f]["id"], "ponte": partenza, "prova": frase_con_entita(documenti[f]["testo"], partenza)}]))
    espansi = 0
    while coda and espansi < max_nodi:
        f, percorso = coda.popleft()
        espansi += 1
        if f in docs_arrivo:
            return {
                "entita_partenza": partenza,
                "entita_arrivo": arrivo,
                "passi": percorso,
            }
        if len(percorso) > max_profondita:
            continue
        # Prima le entità più specifiche (es. pratica RV753) e solo dopo quelle onnipresenti
        # (es. LAZZARO): il percorso deve spiegare il collegamento, non un tema comune.
        entita_ordinate = sorted(
            documenti[f]["entita"],
            key=lambda e: (len(entita_documenti.get(e, ())), e),
        )
        for ent in entita_ordinate:
            docs_ent = entita_documenti.get(ent, set())
            if len(docs_ent) > max_documenti_per_entita:
                continue
            for g in sorted(docs_ent):
                if g in visti or g not in documenti:
                    continue
                # Non attraversare rumore enciclopedico.
                if documenti[g]["id"].upper().startswith("WIKI-"):
                    continue
                visti.add(g)
                nuovo = percorso + [
                    {
                        "file": g,
                        "id": documenti[g]["id"],
                        "ponte": ent,
                        "prova": frase_con_entita(documenti[g]["testo"], ent),
                    }
                ]
                coda.append((g, nuovo))
                if g in docs_arrivo:
                    return {
                        "entita_partenza": partenza,
                        "entita_arrivo": arrivo,
                        "passi": nuovo,
                    }
    return None


def formatta_collegamenti(
    collegamenti: Sequence[dict[str, Any]],
    percorso: dict[str, Any] | None = None,
    limite: int = 8,
) -> str:
    """Rende i collegamenti in un blocco compatto e verificabile per il prompt del modello."""
    righe: list[str] = []
    if percorso:
        catena = " -> ".join(
            f"[{p['id']}] ({p['file']})"
            + (f" --{p['ponte'].upper() if any(c.isdigit() for c in p['ponte']) else p['ponte']}--" if i else "")
            for i, p in enumerate(percorso["passi"])
        )
        righe.append(
            f"PERCORSO TRA «{percorso['entita_partenza']}» E «{percorso['entita_arrivo']}»: {catena}"
        )
        for p in percorso["passi"][1:]:
            if p.get("prova"):
                righe.append(f"  • {p['id']}: «{p['prova']}»")
    if collegamenti:
        righe.append("COLLEGAMENTI TRA I DOCUMENTI RECUPERATI (entità presente in entrambi i testi):")
        for c in collegamenti[:limite]:
            entita = ", ".join(c["entita"][:3])
            righe.append(
                f"  • [{c['id_da']}] ({c['da']}) <-> [{c['id_a']}] ({c['a']}): {entita}"
            )
    if not righe:
        return ""
    righe.append(
        "Regola: un collegamento è valido solo se l'entità indicata compare davvero in entrambi i documenti. "
        "Se il percorso manca, dichiara che il collegamento non è documentato: non inventarlo."
    )
    return "\n".join(righe)


def analizza_collegamenti(
    domanda: str,
    fonti: Sequence[tuple[str, str]],
    limite: int = 10,
) -> dict[str, Any]:
    """Analisi pronta per l'API/gli strumenti: collegamenti + eventuale percorso tra entità."""
    collegamenti = collegamenti_tra_documenti(fonti, domanda=domanda, limite=limite)
    percorso = percorso_collegamento(domanda, fonti)
    return {
        "ok": bool(collegamenti or percorso),
        "domanda": domanda,
        "collegamenti": collegamenti,
        "percorso": percorso,
        "testo": formatta_collegamenti(collegamenti, percorso),
    }
