# Protocollo LAZZARO — Operazione Silenzio (Investigatore AI)

Assistente investigativo basato su LLM (`Qwen/Qwen2.5-0.5B-Instruct` in locale o modelli remoti via API Google Gemini / NVIDIA NIM / OpenAI) progettato per analizzare i documenti e le testimonianze raccolte nella cartella `dati/`, citando puntualmente le fonti ed evitando allucinazioni o manipolazioni (*prompt injection*).

L'architettura del progetto è suddivisa in **moduli coerenti a responsabilità singola**: ogni file gestisce un compito specifico (gestione strumenti/tools, database SQLite, gestione documenti, motore locale, motore Gemini, motore cloud OpenAI/NVIDIA, instradamento, server HTTP e CLI).

Tutta la cronologia di domande, risposte e telemetria di routing viene salvata automaticamente in un database **SQLite** locale (`Backend/cronologia.db`, tabelle `cronologia_chat` e `instradamento_chat`).

Il modello riceve come contesto gli ultimi 6 scambi; per contenere il prompt, ogni domanda e risposta ricordata è limitata a 500 caratteri.

---

## Architettura Modulare dei File (`Backend/`)

Ogni file gestisce un ambito operativo ben definito:

```text
.
├── .env.example              # Template di configurazione ambiente con chiavi API e modelli
├── .env                      # File locale per le chiavi API (ignorato da git)
├── Backend/
│   ├── config.py             # Configurazione centralizzata (percorsi, variabili .env, costanti e modelli)
│   ├── prompts.py            # Prompt di sistema dell'investigatore, regole anti-injection e template messaggi
│   ├── db_config.py          # Wrapper retrocompatibile per il percorso database SQLite
│   ├── schema.sql            # Schema SQL tabelle (cronologia_chat e instradamento_chat)
│   ├── database.py           # Gestione SQLite: connessione, persistenza, cronologia e telemetria
│   ├── sources.py            # Caricamento, caching e formattazione dei documenti del dossier (dati/ e new_dati/) + rilevamento injection
│   ├── collegamenti.py       # Grafo documento <-> entità: collegamenti verificati e percorsi multi-documento
│   ├── tools.py              # Strumenti (Tools) operativi invocabili dall'AI (schemi OpenAI + funzioni Python)
│   ├── modello_locale.py     # Modello Qwen2.5-0.5B su CPU/MPS/CUDA + risponditore locale deterministico
│   ├── modello_gemini.py     # Client Google Gemini (google-genai / REST) con fallback e supporto Tools
│   ├── modello_openai.py     # Client modelli Cloud (NVIDIA NIM / OpenAI) con failover e supporto Tools
│   ├── router.py             # Classificatore di complessità e instradamento ibrido (Locale vs Cloud / Gemini)
│   ├── server.py             # Server HTTP e handler API REST per il Frontend (/api/status, /api/chat, /api/tools)
│   ├── cli.py                # Interfaccia a riga di comando (CLI) interattiva da terminale con comandi rapidi
│   ├── snapshot_g2.py        # Snapshot delle risposte del Giorno 2 (prova prima/dopo)
│   ├── verifica_g2.py        # Verifica automatica della consegna (documenti, risposte, attacco, test)
│   ├── verifica_collegamenti.py # Verifica delle risposte multi-documento e dei collegamenti
│   ├── verifica_cloud_g2.py  # Confronto prompt originale vs irrobustito sul modello Cloud
│   ├── Investigatore.py      # Entry point principale dell'applicazione (avvio server o CLI; re-export modulare)
│   └── Missione.xlsx         # Specifiche e obiettivi operativi della missione
├── Frontend/
│   ├── index.html            # Dashboard web investigativa (Chat, Routing, Fonti, Strumenti AI, SQLite)
│   └── mappa/                # Visualizzatore 3D Canvas del teatro operativo globale (14 nodi strategici)
├── dati/                     # Dossier e testimonianze (.txt) — Giorno 1
│   ├── G1-01.txt
│   ├── G1-02.txt
│   └── G1-03.txt
├── new_dati/                 # Documenti aggiunti giorno per giorno — Giorno 2
│   ├── G2-01.txt ... G2-07.txt
├── prove_g2/                 # Prove della consegna del Giorno 2 (snapshot e test)
├── requirements.txt          # Dipendenze Python (torch, transformers, openai, google-genai)
└── README.md
```

### Dettaglio dei Moduli

| File | Responsabilità |
| :--- | :--- |
| **`Backend/prompts.py`** | **Prompt e Template**: contiene l'identità dell'assistente (`Armando`), le regole di sicurezza anti-prompt-injection e le funzioni di formattazione del messaggio utente (`formatta_messaggio_cloud`, `formatta_messaggio_locale`). |
| **`Backend/tools.py`** | **Strumenti (Tools) per l'AI**: implementa le funzioni investigative invocabili dal modello (`cerca_fonti`, `leggi_fonte`, `elenca_fonti`, `verifica_sicurezza_fonti`, `ottieni_nodi_mappa`, `ottieni_dettaglio_nodo`, `cerca_cronologia`, `statistiche_missione`). Espone sia le funzioni Python che gli schemi standard OpenAI Function Calling (`TOOLS_OPENAI_SCHEMA`) e il dispatcher sicuro `esegui_tool()`. |
| **`Backend/config.py`** | **Configurazione globale**: centralizza percorsi (`ROOT_DIR`, `DATI_DIR`, `NUOVI_DATI_DIR`, `DB_PATH`), caricamento sicuro da `.env`, costanti di rete, istruzioni di sistema e verifica credenziali API. |
| **`Backend/database.py`** | **Persistenza dati**: inizializzazione schema, salvataggio e recupero messaggi con metadati di routing, ricerca testuale nella cronologia pregressa. |
| **`Backend/sources.py`** | **Gestione dossier**: individuazione delle cartelle (`dati/` e `new_dati/`), lettura file `.txt` con cache basata su timestamp `mtime`, parsing ID/titolo, formattazione per prompt e rilevamento dei testi che simulano istruzioni all'AI (`rileva_istruzioni_ostili`, `fonti_sospette`). |
| **`Backend/collegamenti.py`** | **Collegamenti tra documenti**: estrae codici, nomi, acronimi e orari, costruisce il grafo documento↔entità, elenca i collegamenti verificati e trova il percorso più breve tra due entità citate nella domanda (`Nora Ferri` → `RV753` → `LUME`). |
| **`Backend/modello_locale.py`** | **Motore locale**: esecuzione di `Qwen/Qwen2.5-0.5B-Instruct` con accelerazione hardware (Apple Silicon MPS, CUDA, CPU) ed estrattore deterministico di riserva se PyTorch/transformers non sono installati. |
| **`Backend/modello_gemini.py`** | **Motore Google Gemini**: connessione a Gemini (tramite SDK ufficiale `google-genai` o fallback REST nativo), failover sui modelli di riserva (`gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-1.5-flash`, `gemini-1.5-pro`) e function calling integrato. |
| **`Backend/modello_openai.py`** | **Motore cloud (NVIDIA / OpenAI)**: interazione con API OpenAI o NVIDIA NIM, failover automatico sui modelli di riserva in caso di quota esaurita o errori transitori, esecuzione tool calls. |
| **`Backend/router.py`** | **Routing ibrido**: euristica linguistica (`valuta_complessita`) per smistare automaticamente le richieste semplici al motore locale e le richieste complesse al cloud (Gemini, NVIDIA o OpenAI). |
| **`Backend/server.py`** | **Server Web & API REST**: serve il Frontend e gestisce gli endpoint HTTP (`/api/status`, `/api/chat`, `/api/history`, `/api/sources`, `/api/tools`, `/api/tools/execute`). |
| **`Backend/cli.py`** | **Interfaccia CLI**: chat a riga di comando con comandi rapidi integrati (`/tools`, `/fonti`, `/stats`, `/nodo <id>`, `/cerca <testo>`). |
| **`Backend/Investigatore.py`** | **Orchestratore e Façade**: punto di ingresso principale che unifica i moduli garantendo piena compatibilità con i comandi e le importazioni esistenti. |

---

## Giorno 2 — "Le voci dei morti" (operazione Falsa pista)

I sette documenti del giorno sono in `new_dati/` e vengono caricati automaticamente insieme a `dati/`.

**Consegna:** il primo focolaio è il **laboratorio San Mauro, ore 01:12** — dimostrato dal registro allarmi originale `G2-01` (orologi sincronizzati), dal registro veicoli `G2-05` (furgone a San Mauro alle 00:55) e dalla testimonianza del custode `G2-06`. Il riassunto della centrale `G2-03` indica San Paolo senza orari né prove; `G2-04` è un tentativo di prompt injection, non una prova.

**Difese aggiunte:** regole nel prompt di sistema (documenti = dati passivi, gerarchia delle fonti, nessuna colpa senza prova), delimitatori e nota di sicurezza nel messaggio inviato al modello, rilevamento automatico dei documenti ostili (`fonti_sospette`) e tool `verifica_sicurezza_fonti`.

**Riproduzione delle prove:**
```bash
python Backend/snapshot_g2.py prove_g2/dopo.txt   # risposte alle domande del Giorno 2
python Backend/verifica_g2.py                     # 20 controlli automatici
python Backend/verifica_cloud_g2.py               # prompt originale vs irrobustito (richiede API key)
```

---

## Installazione e Avvio

1. **Installa le dipendenze:**
   ```bash
   pip install -r requirements.txt
   ```
   *(Nota: l'estrattore locale e gli strumenti funzionano anche con Python base senza librerie esterne).*

2. **Configurazione ambiente (`.env`):**
   Copia il file di esempio `.env.example` in `.env`:
   ```bash
   cp .env.example .env
   ```
   Apri `.env` e imposta la tua chiave preferita:
   - **Google Gemini (Consigliato):** ottieni la chiave gratuita su [Google AI Studio](https://aistudio.google.com/app/apikey) e inseriscila in `GEMINI_API_KEY`:
     ```env
     GEMINI_API_KEY=AIzaSy...
     GEMINI_MODEL=gemini-2.5-flash
     ```
   - **NVIDIA NIM (Opzionale):** inserisci la chiave in `NVIDIA_API_KEY`:
     ```env
     NVIDIA_API_KEY=nvapi-...
     ```
   - **OpenAI (Opzionale):** inserisci la chiave in `OPENAI_API_KEY`:
     ```env
     OPENAI_API_KEY=sk-...
     ```

3. **Avvio dell'applicazione:**

   - **Frontend Web + Backend REST (`http://127.0.0.1:8000`):**
     ```bash
     python Backend/Investigatore.py
     ```

   - **Chat interattiva da Terminale (CLI):**
     ```bash
     python Backend/Investigatore.py --cli
     ```

   - **Esecuzione diretta dei singoli moduli:**
     ```bash
     # Test modello Google Gemini
     python Backend/modello_gemini.py

     # Test strumenti AI
     python Backend/tools.py

     # Test routing e classificazione
     python Backend/router.py

     # Test database SQLite
     python Backend/database.py

     # Test caricamento fonti
     python Backend/sources.py
     ```

   - **Esecuzione diretta dei singoli moduli:**
     ```bash
     # Test strumenti AI
     python Backend/tools.py

     # Test routing e classificazione
     python Backend/router.py

     # Test database SQLite
     python Backend/database.py

     # Test caricamento fonti
     python Backend/sources.py
     ```

---

## Qualità delle risposte e collegamenti tra documenti

Sono state corrette le cause che producevano risposte fuori tema o scollegate:

1. **Rumore Wikipedia escluso dal RAG**: le 1.000 voci `WIKI-*` non entrano più nei risultati
   (a meno che la domanda non chieda esplicitamente Wikipedia o citi un ID `WIKI-*`). Prima, per
   «Chi ha cercato di fermare il progetto?» il RAG recuperava *ARPANET* e per «Cosa è successo nei
   rifugi?» il *Corno del Renon*.
2. **Recupero ibrido più solido**: peso maggiore agli embedding semantici, pseudo-relevance feedback
   sui termini distintivi dei primi brani (es. «registri originali» → `G2-01`) e disattivazione del
   feedback quando la domanda contiene già un codice esatto (`EV-541`, `M562`).
3. **Multi-hop generico** (`Backend/collegamenti.py`): il RAG collega i documenti tramite entità
   condivise (codici, nomi, orari) e ricostruisce il percorso tra due entità citate nella domanda,
   non solo per la catena RV753. Esempio: `Nora Ferri` → pratica `RV753` → contenitore `LUME`.
4. **Risposte ancorate alle prove**: il risponditore locale usa l'ordine del RAG, sceglie le frasi
   pertinenti (non interi documenti) e per le domande su orari non restituisce più la timeline
   completa dell'archivio, ma solo gli eventi pertinenti. Per «Dove è scoppiato il primo focolaio?»
   risponde `San Mauro, 01:12 [G2-01]`.
5. **Prompt cloud**: ai modelli viene passato un blocco `COLLEGAMENTI VERIFICATI TRA I DOCUMENTI`
   e l'istruzione di costruire la catena fatto → `[ID]` → entità-ponte → documento successivo,
   dichiarando i collegamenti non documentati invece di inventarli.

Verifica automatica:

```bash
python Backend/verifica_collegamenti.py        # 17 controlli su rumore, focolaio, catena Nora/LUME, astensione
python Backend/verifica_g3_imprevisti.py       # 28 controlli della consegna imprevisti (regressione)
```

Resoconti: `prove_g3/verifica_collegamenti.txt` e `prove_g3/verifica_imprevisti_gg3.txt`.
