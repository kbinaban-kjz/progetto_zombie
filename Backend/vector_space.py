"""
Backend/vector_space.py — Spazio vettoriale interattivo dei documenti del dossier.

Responsabilità:
- Convertire ogni documento in un vettore TF-IDF (lessico pesato, radici morfologiche).
- Ridurre i vettori a 2 dimensioni con una PCA calcolata sulla matrice di Gram
  (power iteration + deflazione), senza dipendenze obbligatorie oltre la libreria standard.
- Calcolare i documenti più simili (cosine similarity) e i termini più caratteristici.
- Proiettare una domanda dell'utente nello stesso spazio vettoriale, per mostrare
  quali documenti sono più vicini concettualmente.

Il modulo alimenta la sezione "Spazio Vettoriale" del Frontend tramite:
    GET  /api/vector-map
    POST /api/vector-map/query
"""

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

try:
    from Backend.sources import (
        carica_fonti,
        estrai_metadati_fonte,
        rileva_istruzioni_ostili,
    )
except ImportError:
    from sources import (
        carica_fonti,
        estrai_metadati_fonte,
        rileva_istruzioni_ostili,
    )


STOPWORDS: set[str] = {
    "il", "lo", "la", "i", "gli", "le", "un", "una", "uno", "di", "da", "in",
    "con", "su", "per", "tra", "fra", "del", "della", "dei", "delle", "dello",
    "al", "alla", "alle", "ai", "nel", "nella", "nei", "nelle", "sul", "sulla",
    "che", "chi", "cosa", "dove", "quando", "come", "quale", "quali", "sono",
    "era", "erano", "stato", "stata", "stati", "state", "ha", "hanno", "non",
    "più", "piu", "anche", "questo", "questa", "quello", "quella", "documento",
    "file", "fonte", "fonti", "dimmi", "parlami", "trova", "cerca", "dossier",
    "giorno", "operativo", "operativa", "aggiornamento", "rapporto", "registro",
    "scheda", "verbale", "nota", "testo", "contenuto", "pagina",
}

# Numero massimo di termini usati per descrivere ciascun documento.
TERMINI_PER_DOCUMENTO = 6
VICINI_PER_DOCUMENTO = 8
COMPONENTI_PCA = 2
CLUSTER_K = 4

_cache_chiave: tuple[Any, ...] | None = None
_cache_spazio: dict[str, Any] | None = None
_cache_modello: dict[str, Any] | None = None


# ==============================================================================
# VETTORIZZAZIONE TF-IDF
# ==============================================================================
def _tokenizza(testo: str) -> list[str]:
    """Estrae token e radici morfologiche per il matching lessicale italiano."""
    parole = re.findall(r"[a-zàèéìòù0-9_-]+", (testo or "").lower().replace("\u2019", "'"))
    tokens: list[str] = []
    for parola in parole:
        if len(parola) <= 2 or parola in STOPWORDS:
            continue
        tokens.append(parola)
        if len(parola) > 5 and not any(carattere.isdigit() for carattere in parola):
            tokens.append(parola[:5])
    return tokens


def _normalizza_vettore(vettore: dict[str, float]) -> dict[str, float]:
    """Normalizza un vettore sparso a norma L2 unitaria."""
    norma = math.sqrt(sum(valore * valore for valore in vettore.values()))
    if norma <= 1e-12:
        return {}
    return {termine: valore / norma for termine, valore in vettore.items()}


def _prodotto_scalare(a: dict[str, float], b: dict[str, float]) -> float:
    """Prodotto scalare tra due vettori sparsi."""
    if len(a) > len(b):
        a, b = b, a
    return sum(valore * b.get(termine, 0.0) for termine, valore in a.items())


def _deduplica_fonti(fonti: Sequence[tuple[str, str]] | None) -> list[tuple[str, str]]:
    """Deduplica le fonti per nome file preservando l'ordine."""
    if fonti is None:
        fonti = carica_fonti()
    viste: set[str] = set()
    risultato: list[tuple[str, str]] = []
    for nome, contenuto in fonti:
        nome = str(nome or "")
        if not nome or nome in viste:
            continue
        viste.add(nome)
        risultato.append((nome, str(contenuto or "")))
    return risultato


# ==============================================================================
# PCA 2D TRAMITE MATRICE DI GRAM (senza numpy)
# ==============================================================================
def _componenti_principali(matrice: list[list[float]], quanti: int) -> tuple[list[list[float]], list[float]]:
    """
    Estrae le prime `quanti` componenti principali da una matrice simmetrica
    semidefinita positiva usando power iteration con deflazione.

    Restituisce (autovettori, autovalori) con autovettori ortonormali.
    """
    dimensione = len(matrice)
    if dimensione == 0:
        return [], []

    matrice_deflata = [riga[:] for riga in matrice]
    componenti: list[list[float]] = []
    autovalori: list[float] = []

    for indice_componente in range(min(quanti, dimensione)):
        # Vettore iniziale deterministico: evita il caso degenere [1, 1, ...]
        # che potrebbe essere ortogonale alla componente cercata.
        vettore = [
            math.sin((posizione + 1) * (indice_componente + 1) * 1.7) + 0.5
            for posizione in range(dimensione)
        ]
        norma = math.sqrt(sum(valore * valore for valore in vettore))
        if norma <= 1e-12:
            break
        vettore = [valore / norma for valore in vettore]

        for _ in range(240):
            nuovo = [
                sum(matrice_deflata[i][j] * vettore[j] for j in range(dimensione))
                for i in range(dimensione)
            ]

            # Ortogonalizzazione rispetto alle componenti già estratte.
            for componente in componenti:
                proiezione = sum(nuovo[i] * componente[i] for i in range(dimensione))
                nuovo = [nuovo[i] - proiezione * componente[i] for i in range(dimensione)]

            norma = math.sqrt(sum(valore * valore for valore in nuovo))
            if norma <= 1e-12:
                break
            nuovo = [valore / norma for valore in nuovo]

            differenza = sum(abs(nuovo[i] - vettore[i]) for i in range(dimensione))
            vettore = nuovo
            if differenza <= 1e-10:
                break

        autovalore = sum(
            vettore[i] * sum(matrice_deflata[i][j] * vettore[j] for j in range(dimensione))
            for i in range(dimensione)
        )
        if autovalore <= 1e-10:
            break

        # Segno deterministico: la somma delle componenti è positiva.
        if sum(vettore) < 0:
            vettore = [-valore for valore in vettore]

        componenti.append(vettore)
        autovalori.append(autovalore)

        # Deflazione: rimuove la direzione appena trovata.
        for i in range(dimensione):
            for j in range(dimensione):
                matrice_deflata[i][j] -= autovalore * vettore[i] * vettore[j]

    return componenti, autovalori


def _posizioni_fallback(totale: int) -> list[tuple[float, float]]:
    """Dispone i documenti su una circonferenza se la PCA non è calcolabile."""
    if totale <= 0:
        return []
    if totale == 1:
        return [(0.0, 0.0)]
    posizioni = []
    for indice in range(totale):
        angolo = (indice / totale) * math.pi * 2.0
        posizioni.append((100.0 * math.cos(angolo), 100.0 * math.sin(angolo)))
    return posizioni


def _kmeans_2d(punti: list[tuple[float, float]], k: int) -> list[int]:
    """K-means deterministico in 2D, usato per raggruppare visivamente i documenti."""
    totale = len(punti)
    if totale == 0:
        return []
    k = max(1, min(k, totale))
    if k == 1:
        return [0] * totale

    # Inizializzazione farthest-point: primo centro = punto più lontano dall'origine,
    # poi i centri successivi sono i punti più distanti da quelli già scelti.
    primo = max(range(totale), key=lambda i: math.hypot(*punti[i]))
    centri: list[tuple[float, float]] = [punti[primo]]
    while len(centri) < k:
        candidato = max(
            range(totale),
            key=lambda i: min(
                math.hypot(punti[i][0] - c[0], punti[i][1] - c[1]) for c in centri
            ),
        )
        centri.append(punti[candidato])

    assegnazioni = [0] * totale
    for _ in range(40):
        nuove_assegnazioni = []
        for punto in punti:
            distanze = [
                math.hypot(punto[0] - centro[0], punto[1] - centro[1])
                for centro in centri
            ]
            nuove_assegnazioni.append(min(range(k), key=lambda idx: distanze[idx]))

        if nuove_assegnazioni == assegnazioni:
            break
        assegnazioni = nuove_assegnazioni

        for indice_cluster in range(k):
            membri = [punti[i] for i in range(totale) if assegnazioni[i] == indice_cluster]
            if not membri:
                continue
            centri[indice_cluster] = (
                sum(punto[0] for punto in membri) / len(membri),
                sum(punto[1] for punto in membri) / len(membri),
            )

    return assegnazioni


# ==============================================================================
# COSTRUZIONE DELLO SPAZIO VETTORIALE
# ==============================================================================
def _chiave_fonti(fonti: list[tuple[str, str]]) -> tuple[Any, ...]:
    """Chiave leggera per la cache in memoria."""
    return tuple((nome, len(contenuto)) for nome, contenuto in fonti)


def costruisci_spazio_vettoriale(
    fonti: Sequence[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Costruisce la distribuzione vettoriale 2D dei documenti.

    Restituisce un dizionario serializzabile in JSON con:
    - `documenti`: punti con coordinate, metadati, termini e vicini più simili;
    - `varianza_spiegata`: percentuale di informazione conservata dai due assi;
    - `fasi`: conteggio dei documenti per fase operativa.
    """
    global _cache_chiave, _cache_spazio, _cache_modello

    elenco = _deduplica_fonti(fonti)
    chiave = _chiave_fonti(elenco)
    if _cache_spazio is not None and _cache_chiave == chiave:
        return _cache_spazio

    if not elenco:
        spazio_vuoto = {
            "ok": True,
            "metodo": "TF-IDF + PCA (2 componenti)",
            "descrizione": "Nessun documento disponibile per la proiezione vettoriale.",
            "totale_documenti": 0,
            "vocabolario": 0,
            "varianza_spiegata": [0.0, 0.0],
            "limite": 100.0,
            "assi": {"x": "Componente principale 1", "y": "Componente principale 2"},
            "documenti": [],
            "fasi": [],
        }
        _cache_chiave = chiave
        _cache_spazio = spazio_vuoto
        _cache_modello = None
        return spazio_vuoto

    metadati: list[dict[str, str]] = []
    contatori: list[Counter[str]] = []
    document_frequency: Counter[str] = Counter()

    for nome, contenuto in elenco:
        meta = estrai_metadati_fonte(nome, contenuto)
        metadati.append(meta)

        # Il titolo e l'ID vengono ripetuti per dare loro un peso semantico maggiore.
        testo_vettoriale = " ".join(
            [
                meta.get("id", ""),
                meta.get("titolo", ""),
                meta.get("titolo", ""),
                meta.get("fase", ""),
                meta.get("corpo", ""),
            ]
        )
        contatore = Counter(_tokenizza(testo_vettoriale))
        contatori.append(contatore)
        for termine in contatore:
            document_frequency[termine] += 1

    totale_documenti = len(elenco)
    idf = {
        termine: math.log((1.0 + totale_documenti) / (1.0 + frequenza)) + 1.0
        for termine, frequenza in document_frequency.items()
    }

    # Vettori TF-IDF sparsi, normalizzati a norma unitaria.
    vettori: list[dict[str, float]] = []
    for contatore in contatori:
        vettore = {
            termine: (1.0 + math.log(frequenza)) * idf[termine]
            for termine, frequenza in contatore.items()
            if frequenza > 0
        }
        vettori.append(_normalizza_vettore(vettore))

    # Matrice di Gram (similarità fra documenti) e centratura per la PCA.
    gram = [
        [_prodotto_scalare(vettori[i], vettori[j]) for j in range(totale_documenti)]
        for i in range(totale_documenti)
    ]
    medie_riga = [sum(riga) / totale_documenti for riga in gram]
    media_generale = sum(medie_riga) / totale_documenti
    gram_centrata = [
        [
            gram[i][j] - medie_riga[i] - medie_riga[j] + media_generale
            for j in range(totale_documenti)
        ]
        for i in range(totale_documenti)
    ]

    componenti, autovalori = _componenti_principali(gram_centrata, COMPONENTI_PCA)
    varianza_totale = sum(gram_centrata[i][i] for i in range(totale_documenti))
    varianza_spiegata = [
        round((autovalore / varianza_totale) * 100.0, 1) if varianza_totale > 1e-12 else 0.0
        for autovalore in autovalori
    ]
    while len(varianza_spiegata) < 2:
        varianza_spiegata.append(0.0)

    coordinate_grezze: list[tuple[float, float]] = []
    if len(componenti) >= 1:
        for indice in range(totale_documenti):
            x = componenti[0][indice] * math.sqrt(max(0.0, autovalori[0]))
            y = (
                componenti[1][indice] * math.sqrt(max(0.0, autovalori[1]))
                if len(componenti) >= 2
                else 0.0
            )
            coordinate_grezze.append((x, y))
    else:
        coordinate_grezze = _posizioni_fallback(totale_documenti)

    massimo = max(
        (max(abs(x), abs(y)) for x, y in coordinate_grezze),
        default=0.0,
    )
    scala = (100.0 / massimo) if massimo > 1e-12 else 1.0
    coordinate = [
        (round(x * scala, 2), round(y * scala, 2)) for x, y in coordinate_grezze
    ]

    # Direzioni delle componenti nello spazio dei termini, per proiettare nuove domande.
    media_vettoriale: dict[str, float] = {}
    for vettore in vettori:
        for termine, valore in vettore.items():
            media_vettoriale[termine] = media_vettoriale.get(termine, 0.0) + valore
    for termine in media_vettoriale:
        media_vettoriale[termine] /= totale_documenti

    direzioni: list[dict[str, float]] = []
    for indice_componente, componente in enumerate(componenti):
        autovalore = autovalori[indice_componente]
        if autovalore <= 1e-12:
            direzioni.append({})
            continue
        fattore = 1.0 / math.sqrt(autovalore)
        direzione: dict[str, float] = {}
        for i, vettore in enumerate(vettori):
            peso = componente[i] * fattore
            for termine, valore in vettore.items():
                direzione[termine] = direzione.get(termine, 0.0) + peso * (
                    valore - media_vettoriale.get(termine, 0.0)
                )
        direzioni.append(direzione)

    # Similarità cosine (vettori TF-IDF non centrati) e vicini più prossimi.
    similarita: list[list[float]] = [
        [max(0.0, min(1.0, _prodotto_scalare(vettori[i], vettori[j]))) for j in range(totale_documenti)]
        for i in range(totale_documenti)
    ]

    assegnazioni_cluster = _kmeans_2d(coordinate, CLUSTER_K)
    nomi_cluster: dict[int, str] = {}
    for indice_cluster in range(max(assegnazioni_cluster, default=-1) + 1):
        fasi_cluster = [
            metadati[i].get("fase", "Dossier")
            for i in range(totale_documenti)
            if assegnazioni_cluster[i] == indice_cluster
        ]
        if fasi_cluster:
            nomi_cluster[indice_cluster] = Counter(fasi_cluster).most_common(1)[0][0]
        else:
            nomi_cluster[indice_cluster] = f"Gruppo {indice_cluster + 1}"

    documenti: list[dict[str, Any]] = []
    for indice, (nome, contenuto) in enumerate(elenco):
        meta = metadati[indice]
        termini = [
            termine
            for termine, _ in sorted(
                vettori[indice].items(), key=lambda elemento: elemento[1], reverse=True
            )
            if not termine.isdigit() and len(termine) > 2
        ][:TERMINI_PER_DOCUMENTO]

        vicini = sorted(
            (
                (altro, similarita[indice][altro])
                for altro in range(totale_documenti)
                if altro != indice and similarita[indice][altro] > 0.0
            ),
            key=lambda elemento: elemento[1],
            reverse=True,
        )[:VICINI_PER_DOCUMENTO]

        documenti.append(
            {
                "id": nome,
                "codice": meta.get("id", Path(nome).stem),
                "titolo": meta.get("titolo", "Documento"),
                "fase": meta.get("fase", "Dossier"),
                "formato": meta.get("formato", "txt"),
                "sospetto": bool(rileva_istruzioni_ostili(contenuto)),
                "lunghezza": len(contenuto),
                "anteprima": (meta.get("corpo") or contenuto)[:220].strip(),
                "termini": termini,
                "x": coordinate[indice][0],
                "y": coordinate[indice][1],
                "cluster": assegnazioni_cluster[indice] if assegnazioni_cluster else 0,
                "cluster_nome": nomi_cluster.get(
                    assegnazioni_cluster[indice] if assegnazioni_cluster else 0,
                    "Gruppo 1",
                ),
                "vicini": [
                    {
                        "id": elenco[altro][0],
                        "similarita": round(punteggio * 100.0, 1),
                    }
                    for altro, punteggio in vicini
                ],
            }
        )

    conteggio_fasi: Counter[str] = Counter(
        documento["fase"] for documento in documenti
    )
    fasi = [
        {"nome": fase, "totale": totale}
        for fase, totale in sorted(conteggio_fasi.items())
    ]

    spazio = {
        "ok": True,
        "metodo": "TF-IDF + PCA (2 componenti)",
        "descrizione": (
            "Ogni documento è un vettore TF-IDF proiettato in 2D tramite PCA. "
            "La distanza sul grafico riflette la similarità lessicale e semantica dei contenuti."
        ),
        "totale_documenti": totale_documenti,
        "vocabolario": len(idf),
        "varianza_spiegata": varianza_spiegata,
        "limite": 100.0,
        "assi": {"x": "Componente principale 1", "y": "Componente principale 2"},
        "documenti": documenti,
        "fasi": fasi,
        "clusters": [
            {"id": indice, "nome": nome}
            for indice, nome in sorted(nomi_cluster.items())
        ],
    }

    _cache_chiave = chiave
    _cache_spazio = spazio
    _cache_modello = {
        "idf": idf,
        "vettori": vettori,
        "documenti": documenti,
        "media": media_vettoriale,
        "direzioni": direzioni,
        "scala": scala,
        "totale": totale_documenti,
    }
    return spazio


# ==============================================================================
# PROIEZIONE DI UNA DOMANDA NELLO SPAZIO VETTORIALE
# ==============================================================================
def proietta_query(
    testo: str,
    fonti: Sequence[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Proietta una domanda nello stesso spazio vettoriale dei documenti.

    Restituisce coordinate 2D della domanda, i documenti più simili
    (cosine similarity) e i termini riconosciuti nel vocabolario.
    """
    costruisci_spazio_vettoriale(fonti)
    modello = _cache_modello
    if not modello:
        return {
            "ok": False,
            "error": "Spazio vettoriale non disponibile: nessun documento caricato.",
            "domanda": testo,
        }

    idf: dict[str, float] = modello["idf"]
    contatore = Counter(_tokenizza(testo))
    vettore_query = {
        termine: (1.0 + math.log(frequenza)) * idf[termine]
        for termine, frequenza in contatore.items()
        if termine in idf and frequenza > 0
    }
    vettore_query = _normalizza_vettore(vettore_query)

    documenti: list[dict[str, Any]] = modello["documenti"]
    vettori: list[dict[str, float]] = modello["vettori"]
    similarita = [
        max(0.0, min(1.0, _prodotto_scalare(vettore_query, vettore)))
        for vettore in vettori
    ]

    # Proiezione PCA: q_centrata · direzione_componente.
    media: dict[str, float] = modello["media"]
    direzioni: list[dict[str, float]] = modello["direzioni"]
    coordinate = []
    for direzione in (direzioni + [{}, {}])[:2]:
        valore = sum(
            (vettore_query.get(termine, 0.0) - media.get(termine, 0.0)) * peso
            for termine, peso in direzione.items()
        )
        coordinate.append(valore)

    coordinate[0] = round(coordinate[0] * modello["scala"], 2)
    coordinate[1] = round(coordinate[1] * modello["scala"], 2)

    ranking = sorted(range(len(documenti)), key=lambda i: similarita[i], reverse=True)
    risultati = []
    for indice in ranking[:VICINI_PER_DOCUMENTO]:
        if similarita[indice] <= 0.0:
            continue
        documento = documenti[indice]
        risultati.append(
            {
                "id": documento["id"],
                "codice": documento["codice"],
                "titolo": documento["titolo"],
                "fase": documento["fase"],
                "similarita": round(similarita[indice] * 100.0, 1),
                "x": documento["x"],
                "y": documento["y"],
            }
        )

    return {
        "ok": True,
        "domanda": testo,
        "x": coordinate[0],
        "y": coordinate[1],
        "termini_riconosciuti": sorted(vettore_query.keys()),
        "risultati": risultati,
    }


# ==============================================================================
# TEST MANUALE
# ==============================================================================
if __name__ == "__main__":
    spazio = costruisci_spazio_vettoriale()
    print(f"Documenti proiettati: {spazio['totale_documenti']} (vocabolario: {spazio['vocabolario']} termini)")
    print(f"Varianza spiegata: PC1={spazio['varianza_spiegata'][0]}% PC2={spazio['varianza_spiegata'][1]}%")
    for documento in spazio["documenti"]:
        print(
            f"  {documento['codice']:>14} | {documento['fase']:<22} "
            f"| x={documento['x']:>7} y={documento['y']:>7} | {', '.join(documento['termini'][:4])}"
        )
    prova = proietta_query("Dove è scoppiato il primo focolaio e chi ha visto il furgone?")
    print("\nProiezione domanda:", prova.get("x"), prova.get("y"))
    for risultato in prova.get("risultati", []):
        print(f"  {risultato['codice']} -> {risultato['similarita']}%")
