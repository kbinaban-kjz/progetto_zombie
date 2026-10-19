# Protocollo LAZZARO — Operazione Silenzio (Investigatore AI)

Assistente investigativo basato su LLM (`Qwen/Qwen2.5-0.5B-Instruct` o modelli remoti tramite API) progettato per analizzare i documenti e le testimonianze raccolte nella cartella `dati/`, citando puntualmente le fonti ed evitando allucinazioni o manipolazioni (*prompt injection*).

## Struttura del progetto

```text
.
├── Backend/
│   ├── Investigatore.py      # Script Python del Backend (convertito da Investigatore.ipynb + server web)
│   ├── Investigatore.ipynb   # Notebook originale
│   ├── Missione.xlsx         # Specifiche e obiettivi della missione
│   └── diario_chat.jsonl     # Log generato automaticamente con la cronologia domande/risposte
├── Frontend/
│   └── index.html            # Interfaccia web collegata al Backend
├── dati/                     # Dossier e testimonianze (.txt)
│   ├── G1-01.txt
│   ├── G1-02.txt
│   └── G1-03.txt
├── modello_openai.py         # Modulo alternativo per interrogazioni via API OpenAI / NVIDIA
├── requirements.txt          # Dipendenze Python
└── .gitignore
```

## Installazione e avvio in locale

1. **Clona il repository:**
   ```bash
   git clone https://github.com/kbinaban-kjz/progetto_zombie.git
   cd progetto_zombie
   ```

2. **Installa le dipendenze:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Avvia l'applicazione:**

   - **Opzione A — Frontend Web + Backend (`Frontend/index.html` + `Backend/Investigatore.py`):**
     ```bash
     python Backend/Investigatore.py
     ```
     Apri **`http://127.0.0.1:8000`** nel browser.

   - **Opzione B — Backend interattivo da terminale (`input()`):**
     ```bash
     python Backend/Investigatore.py --cli
     ```

   - **Opzione C — Chiamate con modelli OpenAI / NVIDIA (`modello_openai.py`):**
     Configura `NVIDIA_API_KEY` o `OPENAI_API_KEY` in un file `.env` ed esegui:
     ```bash
     python modello_openai.py
     ```

   - **Opzione D — Esecuzione tramite Notebook (`Backend/Investigatore.ipynb`):**
     Apri `Backend/Investigatore.ipynb` (in VS Code, JupyterLab o Google Colab) ed esegui le celle in ordine:
     - **Cella 1:** Installazione pacchetti (`transformers`, `torch`).
     - **Cella 2:** Caricamento dei file `.txt` da `dati/` (o estrazione automatica da file `.zip`).
     - **Cella 3:** Caricamento del modello `Qwen/Qwen2.5-0.5B-Instruct` su CPU.
     - **Cella 4:** Avvio della chat interattiva con salvataggio automatico in `diario_chat.jsonl`.

## Frontend (`Frontend/index.html`)

L'interfaccia web in `Frontend/index.html` fornisce un terminale operativo direttamente collegato a `Backend/Investigatore.py` (tramite API REST: `/api/status`, `/api/sources`, `/api/history`, `/api/chat`, `/api/config`, `/api/upload-zip`), con fallback locale automatico se aperta direttamente nel browser:

- **Dossier & Fonti (`dati/`)**: mostra i file presenti in `dati/` (`G1-01.txt`, `G1-02.txt`, `G1-03.txt`), consente di caricare archivi `.zip` della squadra con controllo di sicurezza sui percorsi ed elenca i testi formattati tramite `formatta_fonte(nome, testo)` (`[ID] (Titolo): Corpo`).
- **Parametri Backend**: permette di modificare in tempo reale `NOME_ASSISTENTE` e `ISTRUZIONI` (system prompt con regole anti-invenzione e protezione da prompt injection).
- **Chat Investigativa & Cronologia (`diario_chat.jsonl`)**: sincronizza la cronologia con il file `Backend/diario_chat.jsonl`, invia le domande a `chat(domanda, cronologia)`, visualizza per ogni risposta le fonti citate e offre il pulsante **`Scarica diario_chat.jsonl`** per salvare il log della missione.
