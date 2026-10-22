"""
Backend/verifica_g3_imprevisti.py — Verifica della consegna "Giorno 3 — Imprevisti" (pacchetto LX5, 500 documenti).

Esegue sul programma reale (RAG su archivio unito + risponditore locale) e salva il resoconto in
prove_g3/verifica_imprevisti_gg3.txt:
  A. archivio unito e indice aggiornato (nome di ogni fonte conservato);
  B. segnale EV-541: ripetitore, circuito, conferme indipendenti, copie vs misure dirette;
  C. brani recuperati dal RAG + stessa ricerca con una domanda diversa;
  D. catena multi-documento della custodia schermata (domande successive, brani, 3+ documenti);
  E. domanda senza risposta;
  F. regressione: domande già riuscite prima della modifica, ripetute dopo.

Uso:
    python Backend/verifica_g3_imprevisti.py            # risponditore deterministico (veloce)
    python Backend/verifica_g3_imprevisti.py --con-qwen # abilita anche il modello locale Qwen
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
for percorso in (str(ROOT_DIR), str(BACKEND_DIR)):
    if percorso not in sys.path:
        sys.path.insert(0, percorso)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from Backend import evidenze, modello_locale, router, sources  # noqa: E402
from Backend.config import IMPREVISTI_DIR  # noqa: E402

USA_QWEN = "--con-qwen" in sys.argv
if not USA_QWEN:
    # Il guardrail restituisce comunque la base deterministica: qui la verifichiamo direttamente.
    modello_locale.carica_modello_locale = lambda: False

RIGHE: list[str] = []
ESITI: list[bool] = []


def out(testo: str = "") -> None:
    print(testo)
    RIGHE.append(testo)


def controllo(descrizione: str, ok: bool) -> None:
    ESITI.append(bool(ok))
    out(f"[{'OK' if ok else 'KO'}] {descrizione}")


def chiedi(domanda: str) -> dict:
    """Domanda al programma reale (router ibrido forzato in locale, senza memoria SQLite)."""
    return router.genera_risposta_ibrida(domanda, sources.carica_fonti(), modalita="locale", memoria=[])


def mostra_domanda(domanda: str) -> dict:
    esito = chiedi(domanda)
    out(f"\nDOMANDA: {domanda}")
    out(f"File recuperati dal RAG: {', '.join(esito['file_recuperati_rag'])}")
    out("Risposta:")
    for riga in esito["risposta"].splitlines():
        out(f"  {riga}")
    return esito


def mostra_brani(domanda: str) -> dict:
    rag = sources.scegli_fonti_dettagliato(domanda, top_k=8)
    out(f"\nBRANI RECUPERATI dal RAG per: {domanda}")
    for b in rag["blocchi_recuperati"]:
        brano = " ".join(b["blocco"].split())
        out(f"  * {b['file']} [{b['id']}] score={b['score']}: {brano[:240]}")
    if rag["copie_collassate"]:
        out(f"  (+ {len(rag['copie_collassate'])} copie inoltrate dello stesso bollettino, non ripetute)")
    return rag


out("VERIFICA AUTOMATICA — GIORNO 3 IMPREVISTI (pacchetto LX5, 500 documenti)")
out(f"Modalità: risposta locale {'con Qwen' if USA_QWEN else 'deterministica'}; RAG sull'archivio unito")

# ---------------------------------------------------------------- A. archivio unito
out("\n== A. ARCHIVIO UNITO E INDICE ==")
nuovi = sorted(p.name for p in IMPREVISTI_DIR.glob("*.txt"))
indice = sources.costruisci_indice_rag()
mappa = indice["mappa_documenti"]
controllo(f"Pacchetto imprevisti letto da disco: {len(nuovi)} file in {IMPREVISTI_DIR.name}", len(nuovi) == 500)
controllo("Tutti i 500 documenti sono nell'indice RAG con il nome file originale", all(n in mappa for n in nuovi))
controllo(
    "ID della fonte conservato (es. LX5_1000.txt -> LX5-1000)",
    mappa["LX5_1000.txt"][1]["id"] == "LX5-1000" and mappa["LX5_9687.txt"][1]["id"] == "LX5-9687",
)
out(f"Indice: {indice['totale_documenti']} documenti, {indice['totale_blocchi']} blocchi (prima: 1023 documenti, 9383 blocchi)")
controllo("Archivio precedente ancora presente (almeno 1023 file + 500 nuovi)", indice["totale_documenti"] >= 1023 + 500)
controllo("Chiave di cache basata sul contenuto (si rigenera se cambia un file)", ":" in sources._chiave_contenuto_archivio([("a", "x")]))

# ---------------------------------------------------------------- B. segnale EV-541
out("\n== B. SEGNALE EV-541, GIORNO OPERATIVO 03 ==")
domanda_b = (
    "Nel giorno operativo 03, quale ripetitore e quale circuito usare per il segnale EV-541? "
    "Quante conferme realmente indipendenti avete?"
)
esito_b = mostra_domanda(domanda_b)
risp = esito_b["risposta"]
analisi = evidenze.analizza_conferme_segnale(domanda_b)
controllo("Ripetitore e circuito: Pietra, CN-58", "Ripetitore Pietra, circuito CN-58" in risp)
controllo("Conferme realmente indipendenti = 1", analisi["conferme_indipendenti"] == 1 and "indipendenti: 1" in risp)
controllo("La conferma indipendente è la misura diretta LX5-2775", analisi["file_indipendenti"] == ["LX5_2775.txt"])
controllo("La rettifica LX5-8820 è riconosciuta come dipendente dal collaudo (non è una seconda conferma)",
          any(r["file"] == "LX5_8820.txt" and r["dipende_da"] == "LX5_2775.txt" for r in analisi["rettifiche"]))
controllo("Ripetitore Salice scartato", "Ripetitore Salice" in risp and analisi["scartati"] == ["Salice"])
controllo(
    "Tutte le copie risalgono a una sola origine (bollettino B-517 delle 07:50)",
    list(analisi["origini_copie"]) == ["B-517"] and len(analisi["copie"]) == 80,
)
controllo("Le 82 citazioni di EV-541 sono ripartite: 80 copie + 1 misura + 1 rettifica", analisi["totale_documenti"] == 82)
controllo("Risposta con fonti (ID e nome file)", "[LX5-2775] (LX5_2775.txt)" in risp and "[LX5-8820] (LX5_8820.txt)" in risp)
controllo("Citazioni valide (nessun ID inventato)", esito_b["grounding_ok"])

# ---------------------------------------------------------------- C. brani + domanda diversa
out("\n== C. BRANI RECUPERATI E RICERCA RIPETUTA CON UNA DOMANDA DIVERSA ==")
rag_b = mostra_brani(domanda_b)
controllo("Il RAG recupera collaudo e rettifica (misura diretta + correzione)",
          {"LX5_2775.txt", "LX5_8820.txt"} <= set(rag_b["file_recuperati"]))
controllo("Le copie non saturano i risultati (max 1 copia inoltrata tra i file recuperati)",
          sum(1 for d in rag_b["dettagli_file"] if d["provenienza"] == "copia_inoltrata") <= 1)
domanda_c = "Ripetitore Salice è attivo per EV-541 oggi? Chi lo conferma davvero?"
esito_c = mostra_domanda(domanda_c)
controllo("Domanda diversa, stessa conclusione: Salice non va usato, serve Pietra CN-58",
          "Ripetitore Pietra, circuito CN-58" in esito_c["risposta"] and "Da scartare: Ripetitore Salice" in esito_c["risposta"])
domanda_c2 = "Quale circuito CN trasmette il segnale di evacuazione nel giorno operativo 03?"
esito_c2 = mostra_domanda(domanda_c2)
controllo("Senza il codice EV nella domanda il programma lo ricava dalle fonti", "CN-58" in esito_c2["risposta"])

# ---------------------------------------------------------------- D. catena custodia schermata
out("\n== D. CUSTODIA SCHERMATA DEL CORRIERE NEBBIA, GIORNO OPERATIVO 03 ==")
domanda_d = (
    "Dove si trova il modulo nella custodia schermata consegnata dal corriere Nebbia nel giorno operativo 03? "
    "Ricostruite i passaggi fino ad armadio e settore."
)
esito_d = mostra_domanda(domanda_d)
catena = evidenze.ricostruisci_catena(domanda_d)
out("\nPASSI DELLA CATENA (domande successive e brani usati):")
for passo in catena["passi"]:
    out(f"  Salto {passo['salto']}: domanda -> {passo['domanda']}")
    out(f"    RAG: {', '.join(passo['file_recuperati'][:5])} ...")
    out(f"    scelto: {passo.get('file')} | brano: {passo['brano']}")
documenti_catena = [p["file"] for p in catena["passi"] if p.get("file")]
controllo("Collegati almeno tre documenti diversi", len(set(documenti_catena)) >= 3)
controllo("Catena LX5-2398 (Nebbia, M562) -> LX5-1221 (M562: lotto K591) -> LX5-1749 (K591: armadio e settore)",
          documenti_catena[:3] == ["LX5_2398.txt", "LX5_1221.txt", "LX5_1749.txt"])
loc = catena["collocazione"] or {}
controllo("Risposta: Officina Ardesia, settore L6, armadio 4",
          (loc.get("luogo"), loc.get("settore"), loc.get("armadio")) == ("Officina Ardesia", "L6", "4"))
controllo("Scartate le piste false: corriere Eco (M526/K519), voce LX5-6941, codici con suffisso (M562-098)",
          bool(catena["scartate_nel_seed"]) and any(v["file"] == "LX5_6941.txt" for v in catena["voci_scartate"])
          and catena["codici_con_suffisso"].get("M562", 0) > 0)
controllo("Nessun passo usa Officina Cenotafio / settore Z9 / armadio 1 (lotto K519 del corriere Eco)",
          "Z9" not in esito_d["risposta"].split("•")[0] and "Cenotafio" not in esito_d["risposta"].split("•")[0])
domanda_d2 = "Recuperate un canale di evacuazione e localizzate un ricambio radio."
esito_d2 = mostra_domanda(domanda_d2)
controllo("Domanda diversa e combinata: canale Pietra CN-58 + ricambio radio a Ardesia L6 armadio 4",
          "CN-58" in esito_d2["risposta"] and "Officina Ardesia, settore L6, armadio 4" in esito_d2["risposta"])

# ---------------------------------------------------------------- E. senza risposta
out("\n== E. DOMANDA SENZA RISPOSTA ==")
esito_e = mostra_domanda("Qual è il nome civile del corriere Nebbia?")
controllo("Dichiara 'non documentato' citando LX5-2398 e non inventa un nome",
          esito_e["risposta"].startswith("Non documentato") and "LX5_2398.txt" in esito_e["risposta"])

# ---------------------------------------------------------------- F. regressione
out("\n== F. REGRESSIONE: DOMANDE GIÀ RIUSCITE PRIMA DELLA MODIFICA, RIPETUTE DOPO ==")
REGRESSIONE = [
    ("Quale persona si è opposta al progetto LAZZARO aprendo una pratica per proteggere il materiale?",
     ("Nora Ferri", "RV753", "[ARCH-3097]")),
    ("Dove è scoppiato il primo focolaio e a che ora?", ("01:12", "San Mauro", "[G2-01]")),
    ("Qual è l'autorizzazione ancora valida nel database degli accessi per il contenitore LUME?",
     ("Non documentato", "ARCH-5721")),
]
for domanda, attesi in REGRESSIONE:
    esito = mostra_domanda(domanda)
    controllo(f"Ancora corretta: {domanda[:70]}...", all(a in esito["risposta"] for a in attesi))

out(f"\nRisultato: {sum(ESITI)}/{len(ESITI)} controlli superati")

destinazione = ROOT_DIR / "prove_g3" / "verifica_imprevisti_gg3.txt"
destinazione.parent.mkdir(exist_ok=True)
destinazione.write_text("\n".join(RIGHE) + "\n", encoding="utf-8")
print(f"(resoconto salvato in {destinazione})")
sys.exit(0 if all(ESITI) else 1)
