# Protocollo LAZZARO — Operazione Silenzio (Investigatore AI)

Assistente investigativo basato su LLM (`Qwen/Qwen2.5-0.5B-Instruct`) progettato per analizzare i documenti e le testimonianze raccolte nella cartella `dati/`, citando puntualmente le fonti ed evitando allucinazioni o manipolazioni (*prompt injection*).

## Struttura del progetto

```text
.
├── Backend/
│   ├── Investigatore.py      # Script Python del Backend (convertito da Investigatore.ipynb + server web)
│   ├── Investigatore.ipynb   # Notebook originale
│   ├── Missione.xlsx         # Specifiche e obiettivi della missione
│   └── diario_chat.jsonl     # Log generato automaticamente con la cronologia domande/risposte
├── Frontend/
│   └── index.html            # Interfaccia web collegata a Backend/Investigatore.py
├── dati/                     # Dossier e testimonianze (.txt)
│   ├── G1-01.txt
│   ├── G1-02.txt
│   └── G1-03.txt
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

3. **Avvia il Backend e il Frontend:**
   - **Avvio con Interfaccia Web (`Frontend/index.html` + `Backend/Investigatore.py`):**
     ```bash
     python Backend/Investigatore.py
     ```
     Apri **`http://127.0.0.1:8000`** nel browser.
   - **Avvio da terminale interattivo (`input()`):**
     ```bash
     python Backend/Investigatore.py --cli
     ```
   - **Esecuzione tramite Notebook (`Backend/Investigatore.ipynb`):**
     Apri `Backend/Investigatore.ipynb` (in VS Code, JupyterLab o Google Colab) ed esegui le celle in ordine:
     - **Cella 1:** Installazione pacchetti.
     - **Cella 2:** Caricamento dei file `.txt` dalla cartella `dati/` (o estrazione automatica da `.zip`).
     - **Cella 3:** Caricamento del modello `Qwen/Qwen2.5-0.5B-Instruct` su CPU.
     - **Cella 4:** Avvio della chat interattiva con salvataggio automatico in `diario_chat.jsonl`.

## Frontend (`Frontend/index.html`)

L'interfaccia web in `Frontend/index.html` fornisce un pannello grafico direttamente collegato a `Backend/Investigatore.py` (tramite le rotte `/api/status`, `/api/sources`, `/api/history`, `/api/chat`, `/api/config` e `/api/upload-zip`) con fallback automatico sui dati locali se aperta direttamente da file:

- **Dossier & Fonti (`dati/`)**: mostra l'elenco dei file `.txt` caricati (`G1-01.txt`, `G1-02.txt`, `G1-03.txt`), permette di caricare nuovi pacchetti `.zip` della squadra e visualizza i documenti formattati con `formatta_fonte(nome, testo)` (`[ID] (Titolo): Corpo`).
- **Parametri Backend**: consente di visualizzare e modificare in tempo reale `NOME_ASSISTENTE` e `ISTRUZIONI` (system prompt anti-allucinazione e anti-*prompt injection*).
- **Chat & Cronologia (`diario_chat.jsonl`)**: carica all'avvio la `cronologia` salvata in `Backend/diario_chat.jsonl`, permette di inviare nuove domande al modello tramite `chat(domanda, cronologia)`, mostra per ogni risposta le `fonti` utilizzate e include il pulsante **`Scarica diario_chat.jsonl`** per esportare il registro aggiornato.


