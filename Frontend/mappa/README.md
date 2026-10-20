# Mappa interattiva — Protocollo Lazzaro

Mappa del globo in stile apocalittico per il progetto **Operazione Silenzio**.
Nessuna libreria JavaScript esterna: solo HTML, CSS e JavaScript (Canvas 2D).

## Avvio

Apri `index.html` nel browser. Funziona anche da `file://`, senza server.

Se preferisci servire la cartella in locale:

```bash
python -m http.server 8080
# poi apri http://127.0.0.1:8080/Frontend/mappa/
```

## Interazioni

- **Hover su un nodo** — mostra tooltip, reticolo e dossier completo nel pannello destro.
- **Click su un nodo** — fissa il dossier e interrompe la rotazione automatica.
- **Trascina** — ruota il globo; **rotella** — zoom.
- **Lista "Nodi di rete"** — hover per l'anteprima, click per centrare il globo sul nodo.
- **Filtri** — attiva/disattiva rifugi, focolai, segnali e anomalie.
- **Reset** — ripristina vista e rotazione.
- **✕ nel dossier (mobile)** — chiude la scheda.

## File

```text
Frontend/mappa/
├── index.html          # struttura HUD, pannelli, ticker
├── css/style.css       # estetica apocalittica, responsive, animazioni
├── js/data.js          # nodi, collegamenti, testi del ticker
├── js/landmask.js      # maschera terrestre (Natural Earth 110m, 288×144)
└── js/app.js           # globo Canvas, hover picking, zoom, rotazione, UI
```

## Personalizzare i nodi

In `js/data.js` modifica l'array `nodes`. Ogni nodo accetta:

```js
{
  id: 'laz01',            // univoco, usato anche nei links
  code: 'LAZ-01',
  name: 'La Centrale',
  place: 'Ravenna',
  region: 'Emilia-Romagna, IT',
  lat: 44.4184, lon: 12.2035,
  type: 'bunker',         // bunker | outbreak | signal | anomaly
  status: 'OPERATIVO',
  threat: 2,              // 1–5
  survivors: '214',
  contact: 'T-00:00',
  source: 'G1-01',
  reliability: 92,        // percentuale
  tags: ['COMANDO'],
  desc: '...'
}
```

I collegamenti tra nodi stanno in `links`:

```js
['laz01', 'genova'],
```

I colori dei tipi e le etichette sono in `types`, sempre in `js/data.js`.

> Scenario e contenuti sono di finzione. I riferimenti `G1-*` richiamano i dossier presenti in `../../dati/`.
