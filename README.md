# Protocollo LAZZARO — Operazione Silenzio (Investigatore AI)

Assistente investigativo basato su LLM (`Qwen/Qwen2.5-0.5B-Instruct` in locale o modelli remoti via API NVIDIA / OpenAI) progettato per analizzare i documenti e le testimonianze raccolte nella cartella `dati/`, citando puntualmente le fonti ed evitando allucinazioni o manipolazioni (*prompt injection*).

L'architettura del progetto è suddivisa in **moduli coerenti a responsabilità singola**: ogni file gestisce un compito specifico (gestione strumenti/tools, database SQLite, gestione documenti, motore locale, motore cloud, instradamento, server HTTP e CLI).

Tutta la cronologia di domande, risposte e telemetria di routing viene salvata automaticamente in un database **SQLite** locale (`Backend/cronologia.db`, tabelle `cronologia_chat` e `instradamento_chat`).

---

## Architettura Modulare dei File (`Backend/`)

Ogni file gestisce un ambito operativo ben definito:

```text
.
├── Backend/
│   ├── config.py             # Configurazione centralizzata (percorsi, variabili .env, costanti e modelli)
│   ├── prompts.py            # Prompt di sistema dell'investigatore, regole anti-injection e template messaggi
│   ├── db_config.py          # Wrapper retrocompatibile per il percorso database SQLite
│   ├── schema.sql            # Schema SQL tabelle (cronologia_chat e instradamento_chat)
│   ├── database.py           # Gestione SQLite: connessione, persistenza, cronologia e telemetria
│   ├── sources.py            # Caricamento, caching e formattazione dei documenti del dossier (dati/*.txt)
│   ├── tools.py              # Strumenti (Tools) operativi invocabili dall'AI (schemi OpenAI + funzioni Python)
│   ├── modello_locale.py     # Modello Qwen2.5-0.5B su CPU/MPS/CUDA + risponditore locale deterministico
│   ├── modello_openai.py     # Client modelli Cloud (NVIDIA NIM / OpenAI) con failover e supporto Tools
│   ├── router.py             # Classificatore di complessità e instradamento ibrido (Locale vs Cloud)
│   ├── server.py             # Server HTTP e handler API REST per il Frontend (/api/status, /api/chat, /api/tools)
│   ├── cli.py                # Interfaccia a riga di comando (CLI) interattiva da terminale con comandi rapidi
│   ├── Investigatore.py      # Entry point principale dell'applicazione (avvio server o CLI; re-export modulare)
│   └── Missione.xlsx         # Specifiche e obiettivi operativi della missione
├── Frontend/
│   ├── index.html            # Dashboard web investigativa (Chat, Routing, Fonti, Strumenti AI, SQLite)
│   └── mappa/                # Visualizzatore 3D Canvas del teatro operativo globale (14 nodi strategici)
├── dati/                     # Dossier e testimonianze (.txt)
│   ├── G1-01.txt
│   ├── G1-02.txt
│   └── G1-03.txt
├── requirements.txt          # Dipendenze Python (torch, transformers, openai)
└── README.md
```

### Dettaglio dei Moduli

| File | Responsabilità |
| :--- | :--- |
| **`Backend/prompts.py`** | **Prompt e Template**: contiene l'identità dell'assistente (`Armando`), le regole di sicurezza anti-prompt-injection e le funzioni di formattazione del messaggio utente (`formatta_messaggio_cloud`, `formatta_messaggio_locale`). |
| **`Backend/tools.py`** | **Strumenti (Tools) per l'AI**: implementa le funzioni investigative invocabili dal modello (`cerca_fonti`, `leggi_fonte`, `elenca_fonti`, `ottieni_nodi_mappa`, `ottieni_dettaglio_nodo`, `cerca_cronologia`, `statistiche_missione`). Espone sia le funzioni Python che gli schemi standard OpenAI Function Calling (`TOOLS_OPENAI_SCHEMA`) e il dispatcher sicuro `esegui_tool()`. |
| **`Backend/config.py`** | **Configurazione globale**: centralizza percorsi (`ROOT_DIR`, `DATI_DIR`, `DB_PATH`), caricamento sicuro da `.env`, costanti di rete, istruzioni di sistema e verifica credenziali API. |
| **`Backend/database.py`** | **Persistenza dati**: inizializzazione schema, salvataggio e recupero messaggi con metadati di routing, ricerca testuale nella cronologia pregressa. |
| **`Backend/sources.py`** | **Gestione dossier**: individuazione della cartella dati, lettura file `.txt` con cache basata su timestamp `mtime`, parsing ID/titolo e formattazione per prompt. |
| **`Backend/modello_locale.py`** | **Motore locale**: esecuzione di `Qwen/Qwen2.5-0.5B-Instruct` con accelerazione hardware (Apple Silicon MPS, CUDA, CPU) ed estrattore deterministico di riserva se PyTorch/transformers non sono installati. |
| **`Backend/modello_openai.py`** | **Motore cloud**: interazione con API OpenAI o NVIDIA NIM, failover automatico sui modelli di riserva in caso di quota esaurita o errori transitori, esecuzione tool calls. |
| **`Backend/router.py`** | **Routing ibrido**: euristica linguistica (`valuta_complessita`) per smistare automaticamente le richieste semplici al motore locale e le richieste complesse al cloud. |
| **`Backend/server.py`** | **Server Web & API REST**: serve il Frontend e gestisce gli endpoint HTTP (`/api/status`, `/api/chat`, `/api/history`, `/api/sources`, `/api/tools`, `/api/tools/execute`). |
| **`Backend/cli.py`** | **Interfaccia CLI**: chat a riga di comando con comandi rapidi integrati (`/tools`, `/fonti`, `/stats`, `/nodo <id>`, `/cerca <testo>`). |
| **`Backend/Investigatore.py`** | **Orchestratore e Façade**: punto di ingresso principale che unifica i moduli garantendo piena compatibilità con i comandi e le importazioni esistenti. |

---

## Installazione e Avvio

1. **Installa le dipendenze (opzionali per il cloud e il modello locale neuronale):**
   ```bash
   pip install -r requirements.txt
   ```
   *(Nota: l'estrattore locale e gli strumenti funzionano anche con Python base senza librerie esterne).*

2. **Configurazione opzionale (`.env` nella radice del progetto):**
   ```env
   NVIDIA_API_KEY=nvapi-...
   # oppure
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

