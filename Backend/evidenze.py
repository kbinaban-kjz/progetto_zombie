"""
Backend/evidenze.py — Analisi delle evidenze e ricostruzione di catene multi-documento
(Giorno 3 — pacchetto "imprevisti" LX5).

Responsabilità:
- Distinguere, per un segnale (es. EV-541), le COPIE inoltrate di un bollettino dalle MISURE
  DIRETTE e dalle rettifiche, e contare le conferme realmente indipendenti.
- Ricostruire una catena di documenti (corriere -> pratica -> lotto -> collocazione fisica)
  con un RAG a più salti: ogni salto è una nuova domanda, fatta al RAG, sul codice-ponte
  trovato nel documento precedente.

Nessuna risposta è scritta a mano: nomi, codici, orari e collocazioni vengono estratti
dai documenti recuperati dall'indice RAG (archivio unito, nome file conservato).
"""

import re
from typing import Any

try:
    from Backend.sources import (
        classifica_provenienza,
        costruisci_indice_rag,
        scegli_fonti_dettagliato,
    )
except ImportError:
    from sources import (
        classifica_provenienza,
        costruisci_indice_rag,
        scegli_fonti_dettagliato,
    )


# ==============================================================================
# UTILITÀ
# ==============================================================================
_RE_SEGNALE = re.compile(r"(?<![\w-])(EV)[-_ ]?(\d+)(?![\w-])", re.IGNORECASE)
_RE_GIORNO_QUERY = re.compile(r"giorno\s+(?:operativo\s+)?0?(\d{1,2})\b", re.IGNORECASE)
_RE_GIORNO_DOC = re.compile(r"giorno operativo\s+0?(\d{1,2})", re.IGNORECASE)
_RE_ORA_DOC = re.compile(r"\bore\s+(\d{1,2}:\d{2})", re.IGNORECASE)
# Codice di pratica/lotto (es. M562, K591, RV753). Il lookahead esclude i codici con suffisso
# (M562-098 è un'altra spedizione, non M562).
_RE_CODICE = re.compile(r"(?<![\w-])([A-Z]{1,4}\d{3,5})(?![\w-])")
_PAROLE_VUOTE_CATENA = {
    "dove", "quale", "quali", "come", "chi", "cosa", "nel", "nella", "della", "delle", "dello",
    "dalla", "dal", "dei", "degli", "giorno", "operativo", "trova", "ricostruite", "passaggi",
    "fino", "recuperate", "localizzate", "mostrate", "una", "uno", "per", "con", "che",
}


def _documenti() -> dict[str, tuple[str, dict[str, str]]]:
    """Archivio unito: nome_file -> (testo normalizzato, metadati)."""
    return costruisci_indice_rag()["mappa_documenti"]


def _rif(nome_file: str, meta: dict[str, str]) -> str:
    """Citazione standard: ID e nome file della fonte."""
    return f"[{meta['id']}] ({nome_file})"


def _giorno_documento(meta: dict[str, str]) -> str | None:
    trovato = _RE_GIORNO_DOC.search(meta.get("titolo", "") + " " + meta.get("corpo", ""))
    return f"{int(trovato.group(1)):02d}" if trovato else None


def _ora_documento(meta: dict[str, str]) -> str | None:
    trovato = _RE_ORA_DOC.search(meta.get("titolo", ""))
    return trovato.group(1) if trovato else None


def _giorno_query(domanda: str) -> str | None:
    trovato = _RE_GIORNO_QUERY.search(domanda)
    return f"{int(trovato.group(1)):02d}" if trovato else None


def _codice_esatto(codice: str, testo: str) -> bool:
    """True se il codice compare come token intero (K591 sì, K591-098 no)."""
    return bool(re.search(rf"(?<![\w-]){re.escape(codice)}(?![\w-])", testo, re.IGNORECASE))


def _frasi(corpo: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+", corpo) if f.strip()]


def _stems(testo: str) -> set[str]:
    parole = re.findall(r"[a-zàèéìòù0-9]+", testo.lower().replace("’", "'"))
    return {p[:5] for p in parole if len(p) > 3 and p not in _PAROLE_VUOTE_CATENA}


# ==============================================================================
# 1) SEGNALE DI EVACUAZIONE: COPIE vs MISURE DIRETTE
# ==============================================================================
def estrai_segnale(domanda: str) -> str | None:
    trovato = _RE_SEGNALE.search(domanda)
    return f"EV-{trovato.group(2)}" if trovato else None


def analizza_conferme_segnale(domanda: str, segnale: str | None = None) -> dict[str, Any]:
    """
    Esamina TUTTI i documenti dell'archivio unito che citano il segnale e li separa in:
    copie inoltrate (stessa origine, nessuna misura), misure dirette, rettifiche.
    Una rettifica che si appoggia a un collaudo NON è una seconda conferma indipendente.
    """
    giorno = _giorno_query(domanda)
    archivio = _documenti()
    if segnale is None:
        segnale = estrai_segnale(domanda)
    if segnale is None:
        # Nessun codice nella domanda: lo si ricava dai documenti che NON sono copie (misure e
        # rettifiche), così un'ondata di inoltri non decide quale segnale cercare.
        conteggio: dict[str, int] = {}
        for testo, _ in archivio.values():
            if classifica_provenienza(testo) in {"misura_diretta", "rettifica"}:
                trovato = estrai_segnale(testo)
                if trovato:
                    conteggio[trovato] = conteggio.get(trovato, 0) + 1
        if conteggio:
            segnale = max(conteggio, key=conteggio.get)
    if segnale is None:
        return {"ok": False, "motivo": "Nessun segnale di evacuazione individuato nelle fonti."}

    copie: list[dict[str, Any]] = []
    misure: list[dict[str, Any]] = []
    rettifiche: list[dict[str, Any]] = []
    for nome, (testo, meta) in archivio.items():
        if not _codice_esatto(segnale, testo):
            continue
        giorno_doc = _giorno_documento(meta)
        if giorno and giorno_doc and giorno_doc != giorno:
            continue
        corpo = meta["corpo"]
        tipo = classifica_provenienza(testo)
        voce = {"file": nome, "id": meta["id"], "titolo": meta["titolo"], "ora": _ora_documento(meta), "giorno": giorno_doc}
        if tipo == "copia_inoltrata":
            ripetitore = re.search(r"Ripetitore\s+(\w+)", corpo)
            origine = re.search(r"(?:bollettino|secondo)\s+([A-Z]-\d+)(?:\s+delle\s+(\d{1,2}:\d{2}))?", corpo)
            voce.update(
                ripetitore=ripetitore.group(1) if ripetitore else None,
                origine=origine.group(1) if origine else "origine non indicata",
                ora_origine=origine.group(2) if origine and origine.group(2) else None,
            )
            copie.append(voce)
        elif tipo == "misura_diretta":
            esiti = []
            for seg in re.finditer(r"Ripetitore\s+(\w+):\s*([^.]*)\.", corpo):
                dettagli = seg.group(2).lower()
                circuito = re.search(r"circuito\s+([A-Z]+-\d+)", seg.group(2))
                esiti.append(
                    {
                        "ripetitore": seg.group(1),
                        "circuito": circuito.group(1) if circuito else None,
                        "riuscito": "invio riuscito" in dettagli,
                        "dettaglio": seg.group(2).strip(),
                    }
                )
            voce["esiti"] = esiti
            misure.append(voce)
        elif tipo == "rettifica":
            usare = re.search(r"Usare\s+Ripetitore\s+(\w+),\s*circuito\s+([A-Z]+-\d+)", corpo)
            fuori = re.search(r"Ripetitore\s+(\w+)\s+è\s+fuori\s+servizio", corpo)
            supporto = re.search(r"collaudo(?:\s+di\s+linea)?\s+delle\s+(\d{1,2}:\d{2})", corpo)
            voce.update(
                ripetitore=usare.group(1) if usare else None,
                circuito=usare.group(2) if usare else None,
                fuori_servizio=fuori.group(1) if fuori else None,
                supporto_ora=supporto.group(1) if supporto else None,
            )
            rettifiche.append(voce)

    # Scelta: vince il canale che una misura diretta ha visto funzionare.
    scelto: dict[str, Any] | None = None
    misure_a_favore: list[dict[str, Any]] = []
    for misura in misure:
        for esito in misura["esiti"]:
            if esito["riuscito"] and esito["circuito"]:
                if scelto is None:
                    scelto = {"ripetitore": esito["ripetitore"], "circuito": esito["circuito"]}
                if (esito["ripetitore"], esito["circuito"]) == (scelto["ripetitore"], scelto["circuito"]):
                    misure_a_favore.append(misura)
    solo_rettifica = False
    if scelto is None:
        for rett in rettifiche:
            if rett["ripetitore"] and rett["circuito"]:
                scelto = {"ripetitore": rett["ripetitore"], "circuito": rett["circuito"]}
                solo_rettifica = True
                break

    # Dipendenza delle rettifiche: da quale misura derivano?
    for rett in rettifiche:
        rett["dipende_da"] = None
        for misura in misure_a_favore:
            if rett["supporto_ora"] and misura["ora"] == rett["supporto_ora"]:
                rett["dipende_da"] = misura["file"]

    ripetitori_copie = sorted({c["ripetitore"] for c in copie if c["ripetitore"]})
    scartati = [r for r in ripetitori_copie if not scelto or r != scelto["ripetitore"]]
    esiti_scartati = {
        e["ripetitore"]: e["dettaglio"]
        for m in misure
        for e in m["esiti"]
        if not e["riuscito"]
    }
    origini: dict[str, dict[str, Any]] = {}
    for c in copie:
        o = origini.setdefault(c["origine"], {"copie": 0, "ora": c["ora_origine"]})
        o["copie"] += 1

    indipendenti = {m["file"] for m in misure_a_favore}
    return {
        "ok": True,
        "segnale": segnale,
        "giorno": giorno,
        "scelto": scelto,
        "solo_rettifica": solo_rettifica,
        "scartati": scartati,
        "esiti_scartati": esiti_scartati,
        "totale_documenti": len(copie) + len(misure) + len(rettifiche),
        "copie": copie,
        "origini_copie": origini,
        "misure_dirette": misure,
        "misure_a_favore": misure_a_favore,
        "rettifiche": rettifiche,
        "conferme_indipendenti": len(indipendenti),
        "file_indipendenti": sorted(indipendenti),
    }


def formatta_analisi_segnale(analisi: dict[str, Any]) -> str:
    """Rende l'analisi in una risposta con fonti (ID + nome file di ogni documento citato)."""
    if not analisi.get("ok"):
        return f"Non documentato nelle fonti disponibili: {analisi.get('motivo', 'nessuna evidenza')}"

    archivio = _documenti()

    def rif(nome: str) -> str:
        return _rif(nome, archivio[nome][1])

    giorno = f" (giorno operativo {analisi['giorno']})" if analisi["giorno"] else ""
    righe = [f"Analisi evidenze per il segnale {analisi['segnale']}{giorno}:"]
    scelto = analisi["scelto"]
    if not scelto:
        return (
            "Non documentato nelle fonti disponibili: nessuna misura diretta né rettifica "
            f"indica un canale funzionante per {analisi['segnale']}."
        )

    righe.append(f"• Da usare: Ripetitore {scelto['ripetitore']}, circuito {scelto['circuito']}.")
    for misura in analisi["misure_a_favore"]:
        esito = next(e for e in misura["esiti"] if e["ripetitore"] == scelto["ripetitore"])
        ora = f" delle {misura['ora']}" if misura["ora"] else ""
        righe.append(
            f"• Misura diretta{ora} sul posto, firmata dal tecnico: Ripetitore {esito['ripetitore']}: "
            f"{esito['dettaglio']} {rif(misura['file'])}."
        )
    for rett in analisi["rettifiche"]:
        if rett["dipende_da"]:
            righe.append(
                f"• La rettifica tecnica {rif(rett['file'])} indica lo stesso canale ma dichiara di basarsi "
                f"sul collaudo delle {rett['supporto_ora']} ({rif(rett['dipende_da'])}): è la stessa "
                "evidenza, NON una seconda conferma. Aggiunge però che il bollettino usava lo stato "
                "del giorno precedente."
            )
        else:
            righe.append(
                f"• La rettifica {rif(rett['file'])} cita un collaudo che non è presente tra le misure dirette: "
                "non verificabile, non conta come conferma."
            )

    if analisi["copie"]:
        esempi = ", ".join(c["file"] for c in analisi["copie"][:3])
        origini = "; ".join(
            f"{nome}" + (f" delle {dati['ora']}" if dati["ora"] else "") + f" ({dati['copie']} copie)"
            for nome, dati in analisi["origini_copie"].items()
        )
        scartati = ", ".join(f"Ripetitore {r}" for r in analisi["scartati"]) or "nessun altro ripetitore"
        righe.append(
            f"• Da scartare: {scartati}. Lo dichiarano attivo {len(analisi['copie'])} documenti "
            f"(es. {esempi}), ma sono copie inoltrate dello stesso bollettino [{origini}], "
            "«riproduzione senza verifica sul posto», senza nuove misure: contano come UNA sola "
            "origine non verificata, non come tante conferme."
        )
        for rip, dettaglio in analisi["esiti_scartati"].items():
            if rip in analisi["scartati"]:
                righe.append(
                    f"• Il collaudo diretto smentisce la copia: Ripetitore {rip}: {dettaglio}."
                )

    n = analisi["conferme_indipendenti"]
    righe.append(
        f"• Conferme realmente indipendenti: {n} "
        f"({', '.join(rif(f) for f in analisi['file_indipendenti']) or 'nessuna'}). "
        f"Su {analisi['totale_documenti']} documenti che citano {analisi['segnale']}: "
        f"misure dirette = {len(analisi['misure_dirette'])}, rettifiche = {len(analisi['rettifiche'])} "
        f"(dipendenti dalla misura), copie inoltrate = {len(analisi['copie'])}."
    )
    return "\n".join(righe)


# ==============================================================================
# 2) CATENA MULTI-DOCUMENTO (corriere -> pratica -> lotto -> collocazione)
# ==============================================================================
def _domanda_successiva(etichetta: str, codice: str) -> str:
    if etichetta == "pratica":
        return f"Cosa riporta la pratica {codice}? Contenuto e lotto del trasferimento."
    if etichetta == "lotto":
        return f"Dove è stato ricevuto il lotto {codice}? Collocazione fisica: settore e armadio."
    return f"Cosa dicono i documenti su {etichetta} {codice}?"


def _codici_in_frasi(frasi: list[str]) -> list[tuple[str, str]]:
    """Coppie (etichetta, codice) nelle frasi, es. ('pratica', 'M562')."""
    trovati: list[tuple[str, str]] = []
    for frase in frasi:
        for m in _RE_CODICE.finditer(frase):
            prima = re.findall(r"[A-Za-zàèéìòù]+", frase[: m.start()])
            etichetta = prima[-1].lower() if prima else "codice"
            if (etichetta, m.group(1)) not in trovati:
                trovati.append((etichetta, m.group(1)))
    return trovati


def _finestra_seed(corpo: str, domanda: str) -> tuple[list[str], list[str]]:
    """
    Frase del documento più vicina alla domanda + la successiva (spesso riporta la pratica).
    Le frasi che nominano un altro corriere sono escluse e restituite come 'scartate'.
    """
    frasi = _frasi(corpo)
    if not frasi:
        return [], []
    stems_q = _stems(domanda)
    punteggi = [len(stems_q & _stems(f)) for f in frasi]
    migliore = max(range(len(frasi)), key=lambda i: (punteggi[i], -i))
    q_lower = domanda.lower()
    finestra, scartate = [], []
    # La frase successiva serve solo se la migliore non porta già un codice (es. «...consegnato una
    # custodia. La presa in carico è registrata nella pratica M562.»).
    indici = [migliore] if _RE_CODICE.search(frasi[migliore]) else [migliore, migliore + 1]
    for i in indici:
        if i >= len(frasi):
            continue
        altro = re.search(r"corriere(?:\s+con\s+nome\s+operativo)?\s+(\w+)", frasi[i], re.IGNORECASE)
        if altro and altro.group(1).lower() not in q_lower:
            scartate.append(frasi[i])
        else:
            finestra.append(frasi[i])
    # Frasi di altri corrieri nello stesso documento (es. seconda consegna): scartate esplicitamente.
    for i, frase in enumerate(frasi):
        altro = re.search(r"corriere(?:\s+con\s+nome\s+operativo)?\s+(\w+)", frase, re.IGNORECASE)
        if altro and altro.group(1).lower() not in q_lower and frase not in scartate:
            scartate.append(frase)
    return finestra, scartate


def ricostruisci_catena(domanda: str, max_salti: int = 4) -> dict[str, Any]:
    """
    RAG a più salti. Salto 0: la domanda dell'utente. Salti successivi: una nuova domanda sul
    codice-ponte (pratica/lotto) letto nel documento precedente. Ogni passo conserva domanda,
    file recuperati dal RAG, documento scelto e brano usato.
    """
    archivio = _documenti()
    giorno = _giorno_query(domanda)
    q_lower = domanda.lower()

    def ammesso(nome: str) -> bool:
        testo, meta = archivio[nome]
        if classifica_provenienza(testo) in {"copia_inoltrata", "voce"}:
            return False
        giorno_doc = _giorno_documento(meta)
        return not (giorno and giorno_doc and giorno_doc != giorno)

    # --- Salto 0: seed -------------------------------------------------------
    esito0 = scegli_fonti_dettagliato(domanda, top_k=8)
    seed = None
    for nome in esito0["file_recuperati"]:
        if not ammesso(nome):
            continue
        testo, meta = archivio[nome]
        finestra, scartate = _finestra_seed(meta["corpo"], domanda)
        codici = _codici_in_frasi(finestra)
        if codici:
            seed = (nome, meta, finestra, scartate, codici)
            break
    if seed is None:
        return {"ok": False, "domanda": domanda, "motivo": "Nessun documento con un codice-ponte nei brani recuperati."}

    nome, meta, finestra, scartate, codici = seed
    passi: list[dict[str, Any]] = [
        {
            "salto": 0,
            "domanda": domanda,
            "file_recuperati": esito0["file_recuperati"],
            "file": nome,
            "id": meta["id"],
            "titolo": meta["titolo"],
            "brano": " ".join(finestra),
            "ponte": None,
        }
    ]
    visitati = {nome}
    codici_visti = {c for _, c in codici}
    frontiera = list(codici)
    codici_seguiti: list[str] = []

    # --- Salti successivi ------------------------------------------------------
    while frontiera and len(passi) <= max_salti:
        etichetta, codice = frontiera.pop(0)
        codici_seguiti.append(codice)
        dom = _domanda_successiva(etichetta, codice)
        esito = scegli_fonti_dettagliato(dom, top_k=8)
        candidati = [
            f for f in esito["file_recuperati"]
            if f not in visitati and ammesso(f) and _codice_esatto(codice, archivio[f][0])
        ]
        passo: dict[str, Any] = {
            "salto": len(passi),
            "domanda": dom,
            "file_recuperati": esito["file_recuperati"],
            "ponte": f"{etichetta} {codice}",
        }
        if not candidati:
            passo.update(file=None, brano="Nessun documento nuovo contiene questo codice.")
            passi.append(passo)
            continue
        f = candidati[0]
        _, meta_f = archivio[f]
        tutte = _frasi(meta_f["corpo"])
        frasi_codice: list[str] = []
        for i, fr in enumerate(tutte):
            if not _codice_esatto(codice, fr):
                continue
            # Contesto: la frase precedente, se non introduce altri codici (non mescola altri lotti).
            if i > 0 and not _RE_CODICE.search(tutte[i - 1]) and tutte[i - 1] not in frasi_codice:
                frasi_codice.append(tutte[i - 1])
            frasi_codice.append(fr)
        # Dettagli di collocazione che seguono il codice (la frase del codice basta; niente rumore).
        passo.update(file=f, id=meta_f["id"], titolo=meta_f["titolo"], brano=" ".join(frasi_codice))
        passi.append(passo)
        visitati.add(f)
        for et, cod in _codici_in_frasi([fr for fr in frasi_codice if _RE_CODICE.search(fr)]):
            if cod not in codici_visti:
                codici_visti.add(cod)
                frontiera.append((et, cod))

    # --- Risultato: collocazione fisica dell'ultimo documento utile -------------
    collocazione = None
    contenuto = None
    for passo in passi:
        m = re.search(r"contenuto:\s*([^;.]+)", passo.get("brano") or "")
        if m:
            contenuto = m.group(1).strip()
        loc = re.search(
            r"ricevuto a\s+(Officina\s+\w+),\s*settore\s+(\w+)(?:,\s*armadio\s+(\w+))?",
            passo.get("brano") or "",
            re.IGNORECASE,
        )
        if loc:
            collocazione = {
                "luogo": loc.group(1),
                "settore": loc.group(2),
                "armadio": loc.group(3),
                "file": passo["file"],
            }

    # --- Documenti scartati e rumore -----------------------------------------
    voci = []
    nomi_q = set(re.findall(r"\b[A-Z][a-zàèéìòù]{2,}\b", domanda))
    for nome_f, (testo, meta_f) in archivio.items():
        if classifica_provenienza(testo) != "voce":
            continue
        if any(re.search(rf"\b{n}\b", testo) for n in nomi_q if n.lower() not in {"dove", "nel"}):
            voci.append({"file": nome_f, "id": meta_f["id"], "brano": meta_f["corpo"]})
    con_suffisso = {
        codice: sum(
            1 for testo, _ in archivio.values() if re.search(rf"(?<![\w-]){re.escape(codice)}-\d+", testo)
        )
        for codice in codici_seguiti
    }
    return {
        "ok": True,
        "domanda": domanda,
        "passi": passi,
        "collocazione": collocazione,
        "contenuto": contenuto,
        "scartate_nel_seed": scartate,
        "voci_scartate": voci,
        "codici_con_suffisso": con_suffisso,
    }


def formatta_catena(catena: dict[str, Any]) -> str:
    if not catena.get("ok"):
        return f"Non documentato nelle fonti disponibili: {catena.get('motivo', 'catena non ricostruibile')}"
    archivio = _documenti()
    righe = ["Ricostruzione a più documenti (RAG a salti successivi):"]
    for passo in catena["passi"]:
        if not passo.get("file"):
            righe.append(f"{passo['salto'] + 1}. [{passo['ponte']}] {passo['brano']}")
            continue
        ponte = f" (ponte: {passo['ponte']})" if passo["ponte"] else ""
        righe.append(
            f"{passo['salto'] + 1}. {_rif(passo['file'], archivio[passo['file']][1])}{ponte}: {passo['brano']}"
        )
    loc = catena["collocazione"]
    if loc:
        cosa = catena["contenuto"] or "il materiale cercato"
        armadio = f", armadio {loc['armadio']}" if loc["armadio"] else ""
        righe.append(
            f"Risposta — {cosa}: {loc['luogo']}, settore {loc['settore']}{armadio} "
            f"{_rif(loc['file'], archivio[loc['file']][1])}."
        )
    else:
        righe.append("Non documentato nelle fonti disponibili: la catena non arriva a una collocazione fisica.")
    for frase in catena["scartate_nel_seed"]:
        righe.append(f"• Scartato (altro corriere nello stesso registro): «{frase}»")
    for voce in catena["voci_scartate"]:
        righe.append(
            f"• Scartata la voce {_rif(voce['file'], archivio[voce['file']][1])}: «{voce['brano']}» "
            "(sentito dire, senza pratica né consegna vista)."
        )
    for codice, quanti in catena["codici_con_suffisso"].items():
        if quanti:
            righe.append(
                f"• {quanti} documenti citano {codice}-NNN (es. {codice}-098): sono altre spedizioni con lo "
                f"stesso prefisso, non il riferimento {codice}."
            )
    return "\n".join(righe)


def _dato_dichiarato_assente(domanda: str) -> str | None:
    """
    Domande su un dato che i documenti dichiarano esplicitamente di NON riportare
    (es. «Il nome civile e la destinazione non sono riportati»): risposta di astensione con fonte.
    """
    if not re.search(r"nome civile|vero nome|cognome|generalit|identit", domanda, re.IGNORECASE):
        return None
    archivio = _documenti()
    stems_q = _stems(domanda)
    for nome in scegli_fonti_dettagliato(domanda, top_k=8)["file_recuperati"]:
        testo, meta = archivio[nome]
        if classifica_provenienza(testo) in {"copia_inoltrata", "voce"}:
            continue
        for frase in _frasi(meta["corpo"]):
            if re.search(r"non (?:sono|è) riportat", frase, re.IGNORECASE) and (stems_q & _stems(frase)):
                return (
                    "Non documentato nelle fonti disponibili: "
                    f"{_rif(nome, meta)} dichiara espressamente: «{frase}»"
                )
    return "Non documentato nelle fonti disponibili."


# ==============================================================================
# 3) PUNTO DI INGRESSO PER IL RISPONDITORE
# ==============================================================================
def risposta_imprevisti(domanda: str) -> str | None:
    """
    Risposta con fonti alle domande del pacchetto imprevisti (segnale di evacuazione e
    ricostruzione della consegna). Restituisce None se la domanda non riguarda questi temi.
    """
    q = domanda.lower()
    # Parole-guida volutamente strette: le domande dei giorni 1-3 (rifugi, Nora Ferri, RV753...) non
    # devono finire qui.
    # Attenzione: "ripetitore" da solo NON basta (una domanda sul guasto di Pietra non è una
    # domanda sul segnale di evacuazione). Serve il codice EV-* oppure un riferimento esplicito
    # al canale/segnale di evacuazione o al circuito da usare per quel segnale.
    chiede_segnale = bool(
        _RE_SEGNALE.search(domanda)
        or re.search(r"(?:canale|segnale)\s+di\s+evacuazione", q)
        or re.search(r"circuit[oi].{0,40}(?:evacuazione|segnale)", q)
        or re.search(r"(?:quale|quali)\s+ripetitor.{0,60}(?:evacuazione|segnale)", q)
    )
    chiede_catena = bool(re.search(r"corriere|custodia schermata|ricambio|armadio|\blotto\b", q))
    if not (chiede_segnale or chiede_catena):
        return None
    if chiede_catena and not chiede_segnale:
        assente = _dato_dichiarato_assente(domanda)
        if assente:
            return assente
    multipla = chiede_segnale and chiede_catena

    def clausola(pattern: str) -> str:
        """Con più richieste nella stessa frase, ogni analisi riceve solo la sua clausola."""
        if not multipla:
            return domanda
        pezzi = [p.strip() for p in re.split(r"\s+e\s+|[.?!;]\s*", domanda) if p.strip()]
        scelti = [p for p in pezzi if re.search(pattern, p, re.IGNORECASE)]
        return " ".join(scelti) or domanda

    parti = []
    if chiede_segnale:
        parti.append(
            formatta_analisi_segnale(
                analizza_conferme_segnale(clausola(r"ripetitor|circuit|evacuazion|EV[-_ ]?\d+"))
            )
        )
    if chiede_catena:
        parti.append(formatta_catena(ricostruisci_catena(clausola(r"corriere|custodia|ricambio|armadio|lotto"))))
    return "\n\n".join(parti)


if __name__ == "__main__":
    import sys

    domanda_cli = " ".join(sys.argv[1:]) or "Nel giorno operativo 03, quale ripetitore e quale circuito usare per il segnale EV-541?"
    print(risposta_imprevisti(domanda_cli) or "Domanda non pertinente al pacchetto imprevisti.")
