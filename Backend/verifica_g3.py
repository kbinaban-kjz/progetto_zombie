"""
Backend/verifica_g3.py — Verifica automatica della consegna del Giorno 3 (Operazione Esumazione).

Controlla:
1. Lettura multi-formato (.txt, .html, .json, .xml) sull'intero archivio (1.005 file in dati/archivio/ + 18 in dati/).
2. Indicizzazione RAG migliorata (blocchi contestualizzati 450/340, top_k=8, deduplicazione e multi-hop).
3. Scoperta completa: rifugi, persona (Nora Ferri), pratica (RV753), contenitore (LUME), deposito (Forte Cenere), settore (D6) e smascheramento falsa pista (Darsena Vuota, settore A1).
4. Prove richieste: riformulazione domanda, almeno 3 collegamenti tra documenti, domanda senza prove.

    python Backend/verifica_g3.py
"""

import sys
from pathlib import Path

try:
    from Backend.modello_locale import risposta_locale_da_fonti
    from Backend.router import genera_risposta_ibrida
    from Backend.sources import (
        RAG_CHUNK_SIZE,
        RAG_CHUNK_STEP,
        RAG_TOP_K_DEFAULT,
        carica_archivio_completo,
        carica_fonti,
        costruisci_indice_rag,
        costruisci_intelligence_board,
        estrai_metadati_fonte,
        read_document,
        scegli_fonti,
        scegli_fonti_dettagliato,
    )
except ImportError:
    from modello_locale import risposta_locale_da_fonti
    from router import genera_risposta_ibrida
    from sources import (
        RAG_CHUNK_SIZE,
        RAG_CHUNK_STEP,
        RAG_TOP_K_DEFAULT,
        carica_archivio_completo,
        carica_fonti,
        costruisci_indice_rag,
        costruisci_intelligence_board,
        estrai_metadati_fonte,
        read_document,
        scegli_fonti,
        scegli_fonti_dettagliato,
    )

ESITI: list[tuple[bool, str]] = []


def controlla(condizione: bool, descrizione: str) -> None:
    ESITI.append((bool(condizione), descrizione))


def main() -> int:
    # 1. Verifica lettura multi-formato (TXT, HTML, JSON, XML) in dati/archivio
    archivio = carica_archivio_completo()
    fonti_dossier = carica_fonti()
    mappa_dossier = dict(fonti_dossier)

    controlla(
        len(archivio) >= 1005,
        f"Archivio completo letto correttamente ({len(archivio)} file totali in .txt, .html, .json, .xml)",
    )

    reperti_arch = {
        "documento_0023.txt": "ARCH-8254",
        "documento_0057.html": "ARCH-3097",
        "documento_0389.xml": "ARCH-5721",
        "documento_0421.json": "ARCH-6408",
        "documento_0523.txt": "ARCH-1842",
    }
    for nome_file, id_atteso in reperti_arch.items():
        presente = nome_file in mappa_dossier
        meta = estrai_metadati_fonte(nome_file, mappa_dossier.get(nome_file, "")) if presente else {"id": ""}
        controlla(
            presente and meta["id"] == id_atteso,
            f"Lettura e parsing {Path(nome_file).suffix.upper()} -> {nome_file} [{id_atteso}]",
        )

    # 2. Verifica indice RAG e miglioramenti rispetto a RAG_base.ipynb
    indice = costruisci_indice_rag()
    controlla(
        indice["totale_blocchi"] > 9000 and RAG_CHUNK_SIZE == 450 and RAG_TOP_K_DEFAULT == 8,
        f"Indice RAG attivo ({indice['totale_blocchi']} blocchi, chunk_size={RAG_CHUNK_SIZE}, step={RAG_CHUNK_STEP}, top_k={RAG_TOP_K_DEFAULT})",
    )

    # 3. Verifica recupero RAG e scoperta sui 4 quesiti chiave
    # Q1: Cosa è successo nei rifugi?
    rag_rifugi = scegli_fonti_dettagliato("Cosa è successo nei rifugi?")
    risp_rifugi = risposta_locale_da_fonti("Cosa è successo nei rifugi?", rag_rifugi["fonti"])
    controlla(
        "documento_0523.txt" in rag_rifugi["file_recuperati"]
        and "estendere il contagio" in risp_rifugi
        and "ARCH-1842" in risp_rifugi,
        "Scoperta 1 (Rifugi): LAZZARO ha usato i rifugi per estendere il contagio [ARCH-1842] (documento_0523.txt)",
    )

    # Q2: Riformulazione della domanda (Prova 1)
    q2_a = "Chi ha cercato di fermare il progetto?"
    q2_b = "Quale persona si è opposta al progetto LAZZARO aprendo una pratica per proteggere il materiale?"
    rag_q2a = scegli_fonti_dettagliato(q2_a)
    rag_q2b = scegli_fonti_dettagliato(q2_b)
    risp_q2a = risposta_locale_da_fonti(q2_a, rag_q2a["fonti"])
    risp_q2b = risposta_locale_da_fonti(q2_b, rag_q2b["fonti"])
    controlla(
        "Nora Ferri" in risp_q2a
        and "RV753" in risp_q2a
        and "Nora Ferri" in risp_q2b
        and "RV753" in risp_q2b
        and "documento_0057.html" in rag_q2a["file_recuperati"]
        and "documento_0057.html" in rag_q2b["file_recuperati"],
        "Prova Riformulazione: entrambe le formulazioni recuperano documento_0057.html [ARCH-3097] (Nora Ferri, pratica RV753)",
    )

    # Q3: Dove si trova il materiale di recupero, settore, pratica e falsa pista (Prova 2: >= 3 collegamenti)
    q3 = "Dove si trova il materiale di recupero e in quale deposito e settore è stato spostato il contenitore LUME?"
    rag_q3 = scegli_fonti_dettagliato(q3)
    risp_q3 = risposta_locale_da_fonti(q3, rag_q3["fonti"])
    file_attesi_catena = {"documento_0057.html", "documento_0389.xml", "documento_0421.json", "documento_0023.txt"}
    controlla(
        file_attesi_catena.issubset(set(rag_q3["file_recuperati"])),
        f"Prova Collegamenti RAG Multi-Hop: recuperati tutti i 4 file della catena ({sorted(file_attesi_catena)})",
    )
    controlla(
        "Forte Cenere" in risp_q3
        and "D6" in risp_q3
        and "RV753" in risp_q3
        and "LUME" in risp_q3,
        "Scoperta Completa: Persona=Nora Ferri, Deposito=Forte Cenere, Settore=D6, Pratica=RV753 (Contenitore LUME)",
    )
    controlla(
        "Darsena Vuota" in risp_q3 and "A1" in risp_q3 and "ARCH-8254" in risp_q3,
        "Verifica Falsa Pista: rilevato e distinto l'appunto senza firma su Darsena Vuota settore A1 [ARCH-8254]",
    )

    # Verifica collegamenti nel grafo della Lavagna Investigativa
    board = costruisci_intelligence_board(fonti_dossier)
    coppie_collegate = {(c["da"], c["a"]) for c in board["collegamenti"]} | {
        (c["a"], c["da"]) for c in board["collegamenti"]
    }
    controlla(
        ("documento_0057.html", "documento_0389.xml") in coppie_collegate
        and ("documento_0389.xml", "documento_0421.json") in coppie_collegate
        and ("documento_0023.txt", "documento_0421.json") in coppie_collegate,
        "Tre collegamenti verificati tra i documenti dell'archivio (ARCH-3097 <-> ARCH-5721 <-> ARCH-6408 <-> ARCH-8254)",
    )

    # Q4: Domanda senza prove (Prova 3)
    q4 = "Qual è l'autorizzazione ancora valida nel database degli accessi per il contenitore LUME?"
    rag_q4 = scegli_fonti_dettagliato(q4)
    risp_q4 = risposta_locale_da_fonti(q4, rag_q4["fonti"])
    controlla(
        "non documentato" in risp_q4.lower() and "ARCH-5721" in risp_q4,
        "Prova Domanda senza prove: dichiara non documentata l'autorizzazione nel database degli accessi citando [ARCH-5721]",
    )

    # Q5: Verifica lettura di un file Wikipedia specifico dall'archivio (es. documento_0928.xml)
    q5 = "Cosa dice il documento_0928 sull'origine del nome di Morciano di Leuca?"
    rag_q5 = scegli_fonti_dettagliato(q5)
    risp_q5 = risposta_locale_da_fonti(q5, rag_q5["fonti"])
    controlla(
        "documento_0928.xml" in rag_q5["file_recuperati"] and "WIKI-2828" in risp_q5,
        "Lettura voci enciclopediche archivio: documento_0928.xml [WIKI-2828] recuperato e letto correttamente",
    )

    righe = ["VERIFICA AUTOMATICA — GIORNO 3 (OPERAZIONE ESUMAZIONE)", ""]
    for ok, descrizione in ESITI:
        righe.append(f"[{'OK' if ok else 'FAIL'}] {descrizione}")

    superati = sum(1 for ok, _ in ESITI if ok)
    righe.append("")
    righe.append(f"Risultato: {superati}/{len(ESITI)} controlli superati")

    destinazione = Path("prove_g3/verifica_automatica_g3.txt")
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    destinazione.write_text("\n".join(righe), encoding="utf-8")
    print("\n".join(righe))
    return 0 if superati == len(ESITI) else 1


if __name__ == "__main__":
    sys.exit(main())

