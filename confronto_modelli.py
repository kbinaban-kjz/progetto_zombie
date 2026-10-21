"""Confronto di velocità tra modelli, usando modello_openai.py.

Mettere questo file nella cartella principale del progetto (accanto a
modello_openai.py).

1) Vedere quali modelli sono DAVVERO disponibili con le tue chiavi
   (i nomi cambiano spesso e i modelli vengono ritirati):

       python confronto_modelli.py --lista

2) Confrontare due modelli scelti dall'elenco:

       python confronto_modelli.py --gemini gemini-3.5-flash-lite --nvidia NOME_MODELLO

   Si può confrontare anche un solo provider (basta omettere l'altro).

Per ogni modello e domanda misura:
  - Primo testo: secondi dall'invio al primo testo (quello che l'utente percepisce)
  - Totale: secondi fino alla fine della risposta
Poi stampa le mediane e indica il modello più veloce.
"""

import argparse
import statistics
import time

from openai import OpenAI

import modello_openai as m

RIPETIZIONI = 3  # quante volte si ripete ogni domanda (la prima chiamata serve da riscaldamento)

DOMANDE = [
    "Chi ha lasciato il messaggio? Rispondi citando la fonte.",
    "Cosa ordina la centrale ai superstiti?",
    "Cosa hanno di strano le chiamate della centrale?",
]

# Impostazioni forzate durante il test. None = "come se la variabile non esistesse"
# (ignora anche quello che c'è nel .env, così i test non si influenzano).
_OVERRIDE: dict[str, str | None] = {
    "LLM_MAX_MODELLI": "1",   # niente modelli di riserva: si misura solo quello scelto
    "LLM_TIMEOUT": "30",      # evita che il timeout a 8 s falsi il confronto
    "LLM_MAX_TOKENS": "200",  # stessa lunghezza massima per tutti
    "LLM_TEMPERATURE": "0",
}
_config_originale = m._config


def _config_con_override(nome: str):
    if nome in _OVERRIDE:
        return _OVERRIDE[nome]
    return _config_originale(nome)


m._config = _config_con_override  # le funzioni di modello_openai usano questa


def _chiave(provider: str) -> str | None:
    if provider == "gemini":
        return m._chiave_gemini()
    return _config_originale("NVIDIA_API_KEY")


def _base_url(provider: str) -> str:
    return m.GEMINI_BASE_URL if provider == "gemini" else m.NVIDIA_BASE_URL


def elenca_modelli() -> None:
    """Stampa i modelli che il provider dichiara disponibili per la tua chiave."""
    for provider in ("gemini", "nvidia"):
        print(f"\n=== {provider.upper()} ===")
        chiave = _chiave(provider)
        if not chiave:
            print("Nessuna chiave nel .env: saltato.")
            continue
        try:
            client = OpenAI(api_key=chiave, base_url=_base_url(provider), timeout=30)
            nomi = sorted(x.id.removeprefix("models/") for x in client.models.list())
        except Exception as errore:
            print(f"Impossibile leggere l'elenco ({type(errore).__name__}): {errore}")
            continue
        for nome in nomi:
            print(" ", nome)
        print(f"({len(nomi)} modelli)")
    print(
        "\nScegli modelli piccoli/veloci (nomi con 'flash-lite', 'nano', 'mini', '8b', '3b'...) "
        "e poi lancia:\n  python confronto_modelli.py --gemini NOME --nvidia NOME"
    )


def _misura(domanda: str, fonti, modello: str) -> tuple[float, float]:
    inizio = time.perf_counter()
    primo = None
    for evento in m.genera_risposta_stream(domanda, fonti, modello=modello):
        if "delta" in evento and primo is None:
            primo = time.perf_counter() - inizio
    totale = time.perf_counter() - inizio
    if primo is None:
        raise RuntimeError("risposta vuota")
    return primo, totale


def confronta(candidati: list[dict]) -> None:
    percorsi = sorted(m.DATA_DIR.glob("*.txt"))
    if not percorsi:
        print(f"Nessun file .txt in {m.DATA_DIR}")
        return
    fonti = [(p.name, p.read_text(encoding="utf-8")) for p in percorsi]

    risultati = []
    for c in candidati:
        print(f"\n=== {c['nome']} ===")
        if not _chiave(c["provider"]):
            print(f"Saltato: manca la chiave {c['provider']} nel .env.")
            continue

        _OVERRIDE["LLM_PROVIDER"] = c["provider"]
        _OVERRIDE["LLM_REASONING_EFFORT"] = c["reasoning"]

        ttft, tot = [], []
        try:
            # Riscaldamento: la prima chiamata paga la connessione HTTPS, non va contata.
            _misura("ok", fonti, c["modello"])
            for domanda in DOMANDE:
                for _ in range(RIPETIZIONI):
                    t1, t2 = _misura(domanda, fonti, c["modello"])
                    ttft.append(t1)
                    tot.append(t2)
                print(f"  ok: {domanda[:50]}")
        except Exception as errore:
            print(f"  ERRORE ({type(errore).__name__}): {errore}")
            continue

        risultati.append((c["nome"], statistics.median(ttft), statistics.median(tot)))

    print("\n=== RISULTATI (mediane, secondi) ===")
    if not risultati:
        print("Nessun modello ha prodotto risultati.")
        return
    print(f"{'Modello':52} {'Primo testo':>12} {'Totale':>8}")
    for nome, t1, t2 in sorted(risultati, key=lambda r: r[1]):
        print(f"{nome:52} {t1:>12.2f} {t2:>8.2f}")
    print(f"\nPiù veloce al primo testo: {min(risultati, key=lambda r: r[1])[0]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Confronto di velocità tra modelli.")
    ap.add_argument("--lista", action="store_true", help="mostra i modelli disponibili con le tue chiavi")
    ap.add_argument("--gemini", metavar="MODELLO", help="modello Gemini da provare")
    ap.add_argument("--nvidia", metavar="MODELLO", help="modello NVIDIA da provare")
    ap.add_argument(
        "--reasoning-gemini", metavar="VALORE", default=None,
        help="reasoning_effort per Gemini (es. minimal, low). Se omesso non viene inviato.",
    )
    args = ap.parse_args()

    if args.lista:
        elenca_modelli()
        return

    candidati = []
    if args.gemini:
        candidati.append({
            "nome": f"{args.gemini} (Gemini)", "provider": "gemini",
            "modello": args.gemini, "reasoning": args.reasoning_gemini,
        })
    if args.nvidia:
        candidati.append({
            "nome": f"{args.nvidia} (NVIDIA)", "provider": "nvidia",
            "modello": args.nvidia, "reasoning": None,
        })
    if not candidati:
        ap.error("indica almeno un modello con --gemini e/o --nvidia (usa --lista per vedere i nomi)")
    confronta(candidati)


if __name__ == "__main__":
    main()
