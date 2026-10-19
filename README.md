# Protocollo LAZZARO — Operazione Silenzio (Investigatore AI)

Assistente investigativo progettato per analizzare i documenti e le testimonianze raccolte nella cartella `data/` (o `dati/`), citando puntualmente le fonti (es. `[G1-02.txt]`) ed evitando allucinazioni o manipolazioni (*prompt injection*).

## Struttura del progetto

```text
.
├── modello_openai.py         # Backend principale (chiamata OpenAI / NVIDIA sulle fonti fornite)
├── Backend/
│   ├── Investigatore.py      # Server HTTP che collega Frontend/index.html a modello_openai.py
│   ├── Investigatore.ipynb   # Notebook originale
│   ├── Missione.xlsx         # Specifiche e obiettivi della missione
│   └── diario_chat.jsonl     # Log domande/risposte
├── Frontend/
│   └── index.html            # Interfaccia web adattata a modello_openai.py
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

2. **Installa le dipendenze e configura la chiave API:**
   ```bash
   pip install -r requirements.txt
   pip install openai
   ```
   Configura `NVIDIA_API_KEY` oppure `OPENAI_API_KEY` nel file `.env` (o nelle variabili d'ambiente).

3. **Avvia il Backend o il Frontend:**

   - **Da terminale (`modello_openai.py`):**
     ```bash
     python modello_openai.py
     ```

   - **Con Interfaccia Web (`Frontend/index.html` collegata a `modello_openai.py`):**
     ```bash
     python Backend/Investigatore.py
     ```
     Apri poi **`http://127.0.0.1:8000`** nel browser (oppure apri direttamente `Frontend/index.html`).

## Frontend (`Frontend/index.html`)

L'interfaccia in `Frontend/index.html` è adattata direttamente a `modello_openai.py` senza modificarne il codice:

- **Fonti (`fonti: Sequence[tuple[str, str]]`)**: visualizza i file `.txt` nel formato `--- Fonte: {nome} ---\n{contenuto}` usato da `genera_risposta()` e consente di caricare ulteriori file `.txt`.
- **Parametri `genera_risposta(domanda, fonti, *, api_key=None, modello=None)`**: permette di selezionare il `modello` (modello principale NVIDIA `nvidia/nemotron-3-ultra-550b-a55b`, `MODELLI_NVIDIA_RISERVA` o `gpt-4o-mini`), fornire opzionalmente `api_key` (o usare automaticamente `.env`) e consultare le `ISTRUZIONI` di sistema.
- **Terminale Domanda / Risposta**: include `DOMANDA_ESEMPIO` (`"Chi ha lasciato il messaggio? Rispondi citando la fonte."`), gestisce il comando di uscita `esci` e riporta gli stessi messaggi di validazione ed errore di `modello_openai.py`.
