"""
Backend/verifica_collegamenti.py — Verifica dei collegamenti tra documenti e della qualità
delle risposte multi-fonte.

Esegue il programma reale (RAG sull'archivio unito + risponditore locale deterministico) su
domande che prima fallivano:
  - rumore Wikipedia (ARPANET, Corno del Renon) che scavalcava i reperti;
  - focolaio risposto con una timeline generica invece di San Mauro 01:12;
  - catena Nora Ferri -> pratica RV753 -> contenitore LUME;
  - domanda senza prova (autorizzazione) e collegamento non documentato.

Uso:
    python Backend/verifica_collegamenti.py
    python Backend/verifica_collegamenti.py --con-qwen   # abilita anche il modello locale Qwen
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

from Backend import collegamenti, modello_locale, router, sources  # noqa: E402

USA_QWEN = "--con-qwen" in sys.argv
if not USA_QWEN:
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
    return router.genera_risposta_ibrida(
        domanda, sources.carica_fonti(), modalita="locale", memoria=[]
    )


def mostra(domanda: str) -> dict:
    esito = chiedi(domanda)
    out(f"\nDOMANDA: {domanda}")
    out(f"FILE RAG: {', '.join(esito['file_recuperati_rag'])}")
    out("RISPOSTA:")
    for riga in esito["risposta"].splitlines():
        out(f"  {riga}")
    return esito


out("VERIFICA COLLEGAMENTI TRA DOCUMENTI")
out(f"Modalità: {'Qwen + estrattore' if USA_QWEN else 'estrattore deterministico'}")

# 1. Rumore Wikipedia: prima rispondeva ARPANET.
esito = mostra("Chi ha cercato di fermare il progetto?")
risp = esito["risposta"]
controllo(
    "Nessuna voce Wikipedia nelle fonti recuperate",
    not any(n.lower().startswith("documento_") and "wiki" in d["fase"].lower() for n, d in
            zip(esito["file_recuperati_rag"], esito["dettagli_rag"]))
    and "WIKI-" not in " ".join(esito["file_recuperati_rag"]),
)
controllo("Risposta: Nora Ferri, non ARPANET", "Nora Ferri" in risp and "ARPANET" not in risp)
controllo("Fonte corretta [ARCH-3097]", "[ARCH-3097]" in risp)

# 2. Primo focolaio: prima restituiva una timeline di orari non pertinenti.
esito = mostra("Dove è scoppiato il primo focolaio e a che ora?")
risp = esito["risposta"]
controllo("Risposta secca: San Mauro e 01:12", "San Mauro" in risp and "01:12" in risp)
controllo("Fonte del registro originale [G2-01]", "[G2-01]" in risp)
controllo("Nessun orario estraneo (06:25 / 06:40) nella risposta principale",
          "06:25" not in risp and "06:40" not in risp)

# 3. Rifugi: prima rispondeva con una voce enciclopedica (Corno del Renon).
esito = mostra("Cosa è successo nei rifugi?")
risp = esito["risposta"]
controllo("Risposta: i rifugi sono stati usati per estendere il contagio",
          "estendere il contagio" in risp)
controllo("Fonte [ARCH-1842] e nessun Corno del Renon",
          "[ARCH-1842]" in risp and "Corno del Renon" not in risp)

# 4. Catena Nora Ferri -> RV753 -> LUME.
esito = mostra("Quali documenti collegano Nora Ferri al contenitore LUME?")
risp = esito["risposta"]
controllo("Collega almeno tre documenti (Nora, RV753, LUME)",
          sum(1 for x in ("[ARCH-3097]", "[ARCH-5721]", "RV753") if x in risp) == 3)
controllo("Mostra il percorso ARCH-3097 -> ARCH-5721",
          "PERCORSO" in risp and "ARCH-3097" in risp and "ARCH-5721" in risp)
analisi = collegamenti.analizza_collegamenti(
    "Quali documenti collegano Nora Ferri al contenitore LUME?",
    sources.scegli_fonti_dettagliato("Quali documenti collegano Nora Ferri al contenitore LUME?", top_k=10)["fonti"],
)
percorso = analisi.get("percorso") or {}
controllo(
    "Percorso verificato sulle entità condivise (rv753)",
    [p.get("ponte") for p in percorso.get("passi", [])] == ["nora ferri", "rv753"],
)

# 5. Domanda senza prova: non inventare chi ha autorizzato.
esito = mostra("Chi ha autorizzato il trasferimento del contenitore LUME?")
risp = esito["risposta"]
controllo("Dichiara 'non documentato' citando ARCH-5721",
          risp.startswith("Non documentato") and "ARCH-5721" in risp)

# 6. Regressione Giorno 3: persona + pratica.
esito = mostra("Quale persona si è opposta al progetto LAZZARO aprendo una pratica per proteggere il materiale?")
risp = esito["risposta"]
controllo("Nora Ferri + RV753 + ARCH-3097",
          all(x in risp for x in ("Nora Ferri", "RV753", "[ARCH-3097]")))

# 6b. Nessuna colpa senza prova: prima rispondeva con schede di reparto irrilevanti.
esito = mostra("Chi ha manomesso il Ripetitore Pietra?")
risp = esito["risposta"]
controllo(
    "Non attribuisce la manomissione a una persona (astensione con G2-07)",
    risp.startswith("Non documentato") and "G2-07" in risp,
)

# 6c. Luogo completo: trasferimento + planimetria (Forte Cenere, settore D6).
esito = mostra("Dove si trova il contenitore LUME?")
risp = esito["risposta"]
controllo(
    "Risponde Forte Cenere, settore D6 con [ARCH-5721] e [ARCH-6408]",
    all(x in risp for x in ("Forte Cenere", "settore D6", "[ARCH-5721]", "[ARCH-6408]")),
)

# 7. Collegamento non documentato: non inventare un nesso guasto/focolaio.
esito = mostra("Come si collega il guasto del Ripetitore Pietra al primo focolaio?")
risp = esito["risposta"]
controllo("Dichiara che il collegamento diretto non è documentato",
          "Nessun collegamento diretto documentato" in risp)
controllo("Riporta comunque le fonti del guasto (LX5-6396 / LX5-8823)",
          "LX5-6396" in risp or "LX5-8823" in risp)

out(f"\nRisultato: {sum(ESITI)}/{len(ESITI)} controlli superati")

destinazione = ROOT_DIR / "prove_g3" / "verifica_collegamenti.txt"
destinazione.write_text("\n".join(RIGHE) + "\n", encoding="utf-8")
print(f"(resoconto salvato in {destinazione})")
sys.exit(0 if all(ESITI) else 1)
