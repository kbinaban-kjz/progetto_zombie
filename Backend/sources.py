"""
Backend/sources.py — Gestione, caricamento e formattazione dei documenti del dossier.

Responsabilità:
- Risoluzione della cartella contenente i dossier (dati/ o data/).
- Caricamento con caching ad alte prestazioni basato sui timestamp dei file.
- Formattazione strutturata per i modelli ([ID] (Titolo): Corpo).
- Ricerca testuale e per parole chiave nei documenti.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from Backend.config import DATI_DIR, ROOT_DIR
except ImportError:
    from config import DATI_DIR, ROOT_DIR

_cache_fonti_chiave: tuple[tuple[str, int], ...] | None = None
_cache_fonti_valore: list[tuple[str, str]] = []


def risolvi_cartella_dati() -> Path:
    """Individua la cartella dei dossier (privilegiando dati/ rispetto a percorsi alternativi)."""
    if DATI_DIR.is_dir():
        return DATI_DIR
    if (ROOT_DIR / "dati").is_dir():
        return ROOT_DIR / "dati"
    if (ROOT_DIR / "data").is_dir():
        return ROOT_DIR / "data"
    return DATI_DIR


def carica_fonti() -> list[tuple[str, str]]:
    """
    Carica tutti i file .txt della cartella dati/ con cache automatica.
    Ricarica solo se i file sono stati modificati o aggiunti.
    """
    global _cache_fonti_chiave, _cache_fonti_valore
    cartella = risolvi_cartella_dati()
    if not cartella.is_dir():
        return []

    percorsi = sorted(cartella.glob("*.txt"))
    chiave = tuple((p.name, p.stat().st_mtime_ns) for p in percorsi)
    if chiave != _cache_fonti_chiave:
        _cache_fonti_valore = [(p.name, p.read_text(encoding="utf-8")) for p in percorsi]
        _cache_fonti_chiave = chiave
    return _cache_fonti_valore


def estrai_metadati_fonte(nome: str, testo: str) -> dict[str, str]:
    """Estrae ID, titolo e corpo da un testo formattato di un dossier."""
    righe = [r.strip() for r in testo.strip().splitlines() if r.strip()]
    doc_id = righe[0].replace("ID ", "").strip() if righe else nome.replace(".txt", "")
    titolo = righe[1] if len(righe) > 1 else "Documento"
    corpo = " ".join(righe[2:]) if len(righe) > 2 else testo.strip()
    return {
        "file": nome,
        "id": doc_id,
        "titolo": titolo,
        "corpo": corpo,
        "lunghezza": str(len(testo)),
    }


def formatta_fonte(nome: str, testo: str) -> str:
    """Formatta la fonte nel formato standard di indagine: [ID] (Titolo): Corpo."""
    meta = estrai_metadati_fonte(nome, testo)
    return f"[{meta['id']}] ({meta['titolo']}): {meta['corpo']}"


def formatta_blocco_openai(fonti: Sequence[tuple[str, str]]) -> str:
    """Formatta le fonti nel blocco compatibile con i modelli cloud OpenAI/NVIDIA."""
    return "\n\n".join(f"--- Fonte: {nome} ---\n{contenuto}" for nome, contenuto in fonti)


def cerca_in_fonti(
    query: str, fonti: Sequence[tuple[str, str]] | None = None
) -> list[dict[str, Any]]:
    """
    Cerca termini o frasi all'interno dei testi delle fonti caricate.
    Restituisce una lista di corrispondenze con punteggio di rilevanza.
    """
    fonti_effettive = fonti if fonti is not None else carica_fonti()
    parole_chiave = [p for p in re.findall(r"\w+", query.lower()) if len(p) > 2]
    if not parole_chiave:
        return []

    risultati = []
    for nome, testo in fonti_effettive:
        meta = estrai_metadati_fonte(nome, testo)
        testo_lower = testo.lower()
        occorrenze = sum(testo_lower.count(p) for p in parole_chiave)
        if occorrenze > 0:
            risultati.append(
                {
                    "file": nome,
                    "id": meta["id"],
                    "titolo": meta["titolo"],
                    "estratto": meta["corpo"][:200] + ("..." if len(meta["corpo"]) > 200 else ""),
                    "rilevanza": occorrenze,
                }
            )

    risultati.sort(key=lambda x: x["rilevanza"], reverse=True)
    return risultati


if __name__ == "__main__":
    elenco = carica_fonti()
    print(f"Fonti caricate da {risolvi_cartella_dati()}: {[n for n, _ in elenco]}")
    for n, t in elenco:
        print("  -", formatta_fonte(n, t))

