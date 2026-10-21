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
- **Click su un nodo** — fissa il dossier.
- **Trascina** — ruota il globo manualmente; **rotella** — zoom.
- **Lista "Nodi di rete"** — hover per l'anteprima, click per centrare il globo sul nodo.
- **Filtri** — attiva/disattiva rifugi, focolai, segnali e anomalie.
- **Reset** — ripristina la vista (vista fissa incentrata sull'Italia).
- **✕ nel dossier (mobile)** — chiude la scheda.

## Vista iniziale

La mappa **non ruota più da sola**: resta ferma e apre già incentrata sull'Italia.
Il riquadro è in `js/app.js`:

```js
const ITALY_VIEW = { lat: 43.0, lon: 11.5, zoom: 5 };
```

Modificando `lat`, `lon` e `zoom` cambiano il centro e il livello di dettaglio iniziali
(anche del pulsante RESET). Lo zoom massimo è impostato in `setZoom`.

## File

```text
Frontend/mappa/
├── index.html          # struttura HUD, pannelli
├── css/style.css       # estetica apocalittica, responsive, animazioni
├── js/data.js          # nodi e collegamenti
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

> Scenario e contenuti sono di finzione. I riferimenti `G1-*`, `G2-*` e `LX5-*` richiamano i dossier presenti in `../../dati/`.
