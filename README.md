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

3. **Avvia il Backend (`Backend/Investigatore.py`):**
   - **Con interfaccia Web (`Frontend/index.html`):**
     ```bash
     python Backend/Investigatore.py
     ```
     Apri poi `http://127.0.0.1:8000` nel browser.
   - **Da terminale (`input()`):**
     ```bash
     python Backend/Investigatore.py --cli
     ```

