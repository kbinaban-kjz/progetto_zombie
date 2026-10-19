# Protocollo LAZZARO — Operazione Silenzio (Investigatore AI)

Assistente investigativo basato su LLM (`Qwen/Qwen2.5-0.5B-Instruct`) progettato per analizzare i documenti e le testimonianze raccolte nella cartella `dati/`, citando puntualmente le fonti ed evitando allucinazioni o manipolazioni (*prompt injection*).

## Struttura del progetto

```text
.
├── Investigatore.ipynb   # Notebook principale (caricamento dati, modello e chat backend)
├── Missione.xlsx         # Specifiche e obiettivi della missione
├── dati/                 # Dossier e testimonianze (.txt)
│   ├── G1-01.txt
│   ├── G1-02.txt
│   └── G1-03.txt
├── diario_chat.jsonl     # Log generato automaticamente con la cronologia domande/risposte
├── requirements.txt      # Dipendenze Python
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

3. **Esegui il notebook:**
   Apri `Investigatore.ipynb` (in VS Code, JupyterLab o Google Colab) ed esegui le celle in ordine:
   - **Cella 1:** Installazione pacchetti.
   - **Cella 2:** Caricamento dei file `.txt` dalla cartella `dati/` (o estrazione automatica da `.zip`).
   - **Cella 3:** Caricamento del modello `Qwen/Qwen2.5-0.5B-Instruct` su CPU.
   - **Cella 4:** Avvio della chat interattiva da backend (`input()`), con salvataggio automatico di ogni domanda e risposta nella lista `cronologia` e nel file `diario_chat.jsonl`.

