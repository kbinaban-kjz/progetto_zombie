# Protocollo LAZZARO — Operazione Silenzio (Investigatore AI)

Assistente investigativo basato su LLM (`Qwen/Qwen2.5-0.5B-Instruct` o modelli remoti tramite API) progettato per analizzare i documenti e le testimonianze raccolte nella cartella `dati/`, citando puntualmente le fonti ed evitando allucinazioni o manipolazioni (*prompt injection*). Tutta la cronologia di domande e risposte viene salvata automaticamente in un database **SQLite** locale (`Backend/cronologia.db`, tabella `cronologia_chat`).

## Struttura del progetto

```text
.
├── Backend/
│   ├── db_config.py          # Configurazione del percorso database SQLite (Backend/cronologia.db)
│   ├── schema.sql            # Schema SQL della tabella cronologia_chat (id, domanda, risposta, fonti, created_at)
│   ├── database.py           # Inizializzazione dello schema e funzioni di lettura/scrittura su SQLite
│   ├── Investigatore.py      # Script Python del Backend (collegato a SQLite + server HTTP / CLI)
│   ├── Investigatore.ipynb   # Notebook collegato al database SQLite
│   └── Missione.xlsx         # Specifiche e obiettivi della missione
├── Frontend/
│   └── index.html            # Interfaccia web collegata al Backend
├── dati/                     # Dossier e testimonianze (.txt)
│   ├── G1-01.txt
│   ├── G1-02.txt
│   └── G1-03.txt
├── modello_openai.py         # Modulo alternativo per interrogazioni via API OpenAI / NVIDIA
├── requirements.txt          # Dipendenze Python (torch, transformers)
└── .gitignore
```

## Database SQLite (`cronologia_chat`)

- Il percorso del file database è configurato in **`Backend/db_config.py`** (`Backend/cronologia.db` di default, personalizzabile tramite variabile `SQLITE_DB_PATH` nel file `.env`).
- Lo schema in **`Backend/schema.sql`** viene applicato in automatico da **`Backend/database.py`** al primo avvio (non serve installare alcun server esterno).

## Installazione e avvio

1. **Installa le dipendenze:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Avvia l'applicazione:**
   - **Frontend Web + Backend (`http://127.0.0.1:8000`):**
     ```bash
     python Backend/Investigatore.py
     ```
   - **Solo Backend da terminale (`input()`):**
     ```bash
     python Backend/Investigatore.py --cli
     ```
   - **Notebook (`Backend/Investigatore.ipynb`):**
     Esegui le celle in ordine; la Cella 4 salva e legge automaticamente domande e risposte dal database SQLite.
