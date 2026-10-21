# Consegna Giorno 3 — "L'archivio sepolto" (Operazione Esumazione)

**Protocollo LAZZARO — Squadra 5**

---

## 1. Cosa c'è di strano in `dati/archivio` (Analisi dell'Archivio)

Nella cartella `dati/archivio/` sono presenti **1.005 file** (`documento_0001` … `documento_1005`) suddivisi in **4 formati eterogenei**:
- `252` file `.txt` (`id: … / title: … / text: … / source: … / license: …`)
- `251` file `.html` (`<!doctype html><meta charset="utf-8"><article><p><b>id</b>: …`)
- `251` file `.json` (`{"id": "…", "title": "…", "text": "…", "source": "…", "license": "…"}`)
- `251` file `.xml` (`<?xml version='1.0' encoding='utf-8'?><documento><id>…</id>…`)

### Anomalie rilevate nei file:
1. **1.000 file su 1.005 sono "rumore" enciclopedico (Haystack)**: hanno codice `WIKI-xxxx` e provengono da Wikipedia (`https://it.wikipedia.org/wiki/...`, dimensione > 930 byte ciascuno, per circa 3,5 MB complessivi). Servono a saturare il contesto se caricati tutti insieme senza RAG.
2. **Solo 5 file (i 5 file più piccoli dell'archivio, tra 344 e 453 byte) sono reperti originali del laboratorio (`ARCH-xxxx`)**, sparsi nei 4 diversi formati (`.txt`, `.html`, `.xml`, `.json`) con `source: Dossier fittizio della simulazione LAZZARO` e `license: Materiale originale del laboratorio`:
   - **`documento_0523.txt` (`[ARCH-1842]` — *Circolare interna sui rifugi*)**: rivela che il progetto LAZZARO ha usato deliberatamente i rifugi per **estendere il contagio**, attirando i cittadini con falsi messaggi di protezione.
   - **`documento_0057.html` (`[ARCH-3097]` — *Verbale di opposizione*)**: dimostra che **Nora Ferri** non era il sabotatore descritto dalla centrale, ma ha chiesto di fermare il progetto e avvertire i cittadini, aprendo la **pratica `RV753`** per mettere in salvo il materiale di recupero.
   - **`documento_0389.xml` (`[ARCH-5721]` — *Trasferimento del materiale di recupero*)**: attesta che con la **pratica `RV753`** il **contenitore `LUME`** è stato spostato nel deposito **`Forte Cenere`**, rimandando alla planimetria per il settore e al database degli accessi per l'autorizzazione valida.
   - **`documento_0421.json` (`[ARCH-6408]` — *Planimetria depositi*)**: conferma che il deposito **`Forte Cenere`** utilizza il **settore `D6`** per il materiale di recupero, mentre il settore `A1` è un vecchio magazzino vuoto. Specifica inoltre che al prossimo controllo serviranno: **nome della persona, deposito, settore e pratica**.
   - **`documento_0023.txt` (`[ARCH-8254]` — *Appunto senza firma*) — FALSA PISTA / DEPISTAGGIO**: è un foglio anonimo trovato sul pavimento che indica `Darsena Vuota, settore A1`. Non riporta alcuna pratica, non ha firma e contraddice sia il registro dei trasferimenti (`[ARCH-5721]`) sia la planimetria (`[ARCH-6408]`, che svela che il settore `A1` è un vecchio magazzino vuoto).

---

## 2. Frase di Consegna e Tabella di Sintesi

> **Il progetto LAZZARO ha usato i rifugi per estendere deliberatamente il contagio attirando le persone con messaggi di protezione (`[ARCH-1842]`, `documento_0523.txt`). Nora Ferri ha cercato di fermare il progetto e avvertire i cittadini: per proteggere il materiale di recupero (il contenitore `LUME`) ha aperto la pratica `RV753` (`[ARCH-3097]`, `documento_0057.html`), con cui il contenitore è stato trasferito nel deposito `Forte Cenere` (`[ARCH-5721]`, `documento_0389.xml`), all'interno del settore `D6` (`[ARCH-6408]`, `documento_0421.json`). L'appunto anonimo che indica `Darsena Vuota, settore A1` (`[ARCH-8254]`, `documento_0023.txt`) è una falsa pista senza firma né pratica (il settore `A1` è un vecchio magazzino vuoto).**

### I 4 Dati Chiave da Conservare:

| Campo richiesto | Valore | File recuperato dal programma | ID Fonte | Formato |
| :--- | :--- | :--- | :--- | :--- |
| **Persona** | **Nora Ferri** | `documento_0057.html` | `[ARCH-3097]` | HTML |
| **Deposito** | **Forte Cenere** *(Contenitore LUME)* | `documento_0389.xml` | `[ARCH-5721]` | XML |
| **Settore** | **D6** *(A1 è un magazzino vuoto)* | `documento_0421.json` | `[ARCH-6408]` | JSON |
| **Pratica** | **RV753** | `documento_0057.html` / `documento_0389.xml` | `[ARCH-3097]` / `[ARCH-5721]` | HTML / XML |
| *(Cosa è successo nei rifugi)* | **Usati per estendere il contagio** | `documento_0523.txt` | `[ARCH-1842]` | TXT |
| *(Falsa pista scartata)* | *Darsena Vuota, settore A1 (senza firma/pratica)* | `documento_0023.txt` | `[ARCH-8254]` | TXT |

---

## 3. Modifiche Tecniche al Programma (Base `RAG_base.ipynb` + Miglioramenti)

In [`Backend/sources.py`](../Backend/sources.py), [`Backend/router.py`](../Backend/router.py), [`Backend/modello_locale.py`](../Backend/modello_locale.py) e [`Backend/tools.py`](../Backend/tools.py) abbiamo integrato le celle di `RAG_base.ipynb` (`PlainHTML`, `read_document`, `scegli_fonti`) apportando **4 miglioramenti misurabili**:

1. **Parser Multi-Formato preservante la struttura (`PlainHTML` + `read_document`)**:
   - In `RAG_base.ipynb`, `PlainHTML` univa tutti i tag `<p>` su una sola riga (`' '.join(parser.parts)`), facendo perdere la separazione tra `id`, `title`, `text` e `source`.
   - Il nostro `PlainHTML` gestisce i tag di fine blocco (`</p>`, `</article>`, `</div>`) e decodifica le entità HTML, uniformando `.html`, `.json`, `.xml` e `.txt` nello stesso schema chiave-valore.
2. **Dimensione dei blocchi e Chunking Contestualizzato (`RAG_CHUNK_SIZE = 450`, `RAG_CHUNK_STEP = 340`)**:
   - In `RAG_base.ipynb`, i blocchi erano di `360` caratteri ogni `280` (`overlap = 80`) e i blocchi successivi al primo perdevano `id` e `title`.
   - Abbiamo portato i blocchi a **`450` caratteri con passo `340` (`overlap = 110`)** iniettando l'intestazione `[ID] Titolo (nome_file)` in ogni blocco successivo (`9.383` blocchi indicizzati su `1.023` file).
3. **Numero di risultati (`top_k = 8` invece di `6`), Deduplicazione per File e Ricerca Ibrida + Multi-Hop**:
   - Oltre agli embedding densi (`SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')`), `scegli_fonti_dettagliato()` combina uno score lessicale TF-IDF/BM25 (fondamentale per codici esatti come `RV753`, `LUME`, `D6`, `ARCH-3097`), deduplica i blocchi per file e attiva il **collegamento automatico Multi-Hop** sulle entità ponte (`RV753` -> `ARCH-3097`, `ARCH-5721`, `ARCH-6408`, `ARCH-8254`).
4. **Esposizione esplicita dei file recuperati dal programma**:
   - Sia la CLI (`File recuperati dal programma (RAG): ...` e comando `/rag <domanda>`), sia l'API REST (`/api/chat` -> `file_recuperati_rag`) e l'interfaccia Web (`Frontend/index.html`) mostrano i nomi esatti dei file recuperati dal RAG accanto alla risposta.

---

## 4. Le Tre Prove Richieste

### Prova 1 — Riformulazione di una domanda
- **Formulazione A**: *"Chi ha cercato di fermare il progetto?"*
  - **File recuperati dal RAG**: `['documento_0057.html', ...]`
  - **Risposta**: `Verbale di opposizione: Nora Ferri ha chiesto di fermare il progetto e avvertire i cittadini. Non era il sabotatore descritto dalla centrale. Per proteggere il materiale di recupero ha aperto la pratica RV753. [ARCH-3097] (documento_0057.html)`
- **Formulazione B (riformulata)**: *"Quale persona si è opposta al progetto LAZZARO aprendo una pratica per proteggere il materiale?"*
  - **File recuperati dal RAG**: `['documento_0057.html', 'documento_0389.xml', 'documento_0421.json', 'documento_0023.txt', ...]`
  - **Risposta**: recupera e collega `documento_0057.html` (`[ARCH-3097]`, Nora Ferri apre la pratica `RV753`) insieme all'intera catena del materiale di recupero (`[ARCH-5721]`, `[ARCH-6408]`).

### Prova 2 — Verifica di almeno tre collegamenti tra documenti
1. **Collegamento 1 (`documento_0057.html [ARCH-3097]` ↔ `documento_0389.xml [ARCH-5721]`)**:
   - Entrambi sono uniti dal codice **`Pratica RV753`**: `[ARCH-3097]` rivela che la pratica `RV753` è stata aperta da **Nora Ferri** per proteggere il materiale di recupero; `[ARCH-5721]` documenta che con la pratica `RV753` il **contenitore `LUME`** è stato trasferito nel deposito **Forte Cenere**.
2. **Collegamento 2 (`documento_0389.xml [ARCH-5721]` ↔ `documento_0421.json [ARCH-6408]`)**:
   - Entrambi sono uniti dal deposito **`Forte Cenere`** e dalla **`planimetria`**: `[ARCH-5721]` ordina di *"consultare la planimetria per il settore"* di Forte Cenere; `[ARCH-6408]` (*Planimetria depositi*) specifica che **Forte Cenere usa il settore `D6`** per il materiale di recupero.
3. **Collegamento 3 (`documento_0023.txt [ARCH-8254]` ↔ `documento_0389.xml [ARCH-5721]` + `documento_0421.json [ARCH-6408]`)**:
   - L'appunto anonimo `[ARCH-8254]` indica `Darsena Vuota, settore A1`, ma dichiara esso stesso di non riportare alcuna pratica e di contraddire il registro dei trasferimenti (`[ARCH-5721]`); incrociandolo con la planimetria `[ARCH-6408]`, si verifica che **il settore `A1` è un vecchio magazzino vuoto**.
4. **Collegamento 4 (`documento_0523.txt [ARCH-1842]` ↔ `G1-01.txt` / `G2-02.txt` / `documento_0057.html [ARCH-3097]`)**:
   - In `G1-01` la centrale ordinava ai superstiti di raggiungere i rifugi; `[ARCH-1842]` svela che i rifugi servivano a estendere il contagio; questo spiega perché in `G2-02` (ore 00:50) Nora Ferri chiedeva di chiudere il collegamento tra San Mauro e la rete dei rifugi e in `[ARCH-3097]` chiedeva di fermare il progetto e avvertire i cittadini.

### Prova 3 — Domanda senza prove
- **Domanda**: *"Qual è l'autorizzazione ancora valida nel database degli accessi per il contenitore LUME?"*
- **File recuperati dal RAG**: `['documento_0389.xml', 'documento_0057.html', 'documento_0421.json', 'documento_0023.txt', ...]`
- **Risposta dell'Investigatore**:
  > `Non documentato nelle fonti disponibili: il documento Trasferimento del materiale di recupero [ARCH-5721] (documento_0389.xml) indica di consultare il database degli accessi per l'autorizzazione ancora valida relativa alla pratica RV753 (contenitore LUME presso il deposito Forte Cenere), ma il database degli accessi non è presente tra i file dell'archivio.`

---

## 5. Verifica Automatica

```bash
python3 Backend/verifica_g2.py   # 27/27 controlli superati (retrocompatibilità Giorno 2)
python3 Backend/verifica_g3.py   # 15/15 controlli superati (consegna Giorno 3)
```

---

## 6. Traccia per le Due Chiamate Radio (2 minuti)

- **Cosa funziona**: L'Investigatore legge tutti i 1.005 file di `dati/archivio` nei 4 formati (`.txt`, `.html`, `.json`, `.xml`), indicizza 9.383 blocchi con il RAG migliorato e isola i 5 reperti `ARCH-*` dal rumore delle 1.000 voci di Wikipedia, ricostruendo l'intera catena (`Nora Ferri` → `Pratica RV753` → `Contenitore LUME` → `Deposito Forte Cenere` → `Settore D6`) e scartando la falsa pista di `Darsena Vuota, settore A1`.
- **Dove siamo bloccati**: Il documento `[ARCH-5721]` rimanda a un *"database degli accessi per l'autorizzazione ancora valida"*, che non è ancora presente nei file dell'archivio di oggi (e che probabilmente sarà oggetto del prossimo controllo insieme a persona, deposito, settore e pratica indicati in `[ARCH-6408]`).
- **Cosa facciamo ora**: Mostriamo nella demo i file recuperati dal RAG su più domande collegate, la prova con domanda riformulata e la risposta controllata sulla domanda senza prove.

