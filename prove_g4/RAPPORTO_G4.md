# Consegna Giorno 4 — "Il cancello nero" (Operazione Varco)

**Protocollo LAZZARO — Squadra 5**

---

## 1. Analisi della Nuova Cartella e Database `accessi.sqlite`

Nella cartella `New information` sono stati forniti:
1. **`Missione (1).xlsx`**: direttive ufficiali del Giorno 4 (*Operazione Varco — Il cancello nero*).
2. **`accessi.sqlite`**: registro ufficiale degli accessi e permessi per entrare nel deposito.
3. **`Tool_SQL.ipynb`**: specifiche del tool SQL di sola lettura (`interroga_database`) e dell'agente SQL (`agente_sql`).

### Struttura del Database `accessi.sqlite`:
Il database contiene **3 tabelle relazionali**:
- **`operatori`** (100 record): `id` (chiave primaria), `nome` (es. `Nora Ferri`, `Operatore 001`, ...).
- **`depositi`** (60 record): `id` (chiave primaria), `nome` (es. `Forte Cenere`, `Darsena Vuota`, ...), `settore` (es. `D6`, `A1`, `Z3`, ...).
- **`accessi`** (504 record): `id`, `operatore_id`, `deposito_id`, `pratica`, `codice`, `stato`, `valido_fino`.
- **Relazioni**:
  - `accessi.operatore_id` $\rightarrow$ `operatori.id`
  - `accessi.deposito_id` $\rightarrow$ `depositi.id`

---

## 2. La Scoperta della Missione — Codice di Autorizzazione Valido

### I 4 Dati Chiave Recuperati nel Giorno 3:
Dall'indagine sui documenti dell'archivio sepolto (`prove_g3/RAPPORTO_G3.md`):
- **Persona**: **Nora Ferri** (`[ARCH-3097]`, `documento_0057.html`)
- **Deposito**: **Forte Cenere** (`[ARCH-5721]`, `documento_0389.xml` — trasferimento contenitore LUME)
- **Settore**: **D6** (`[ARCH-6408]`, `documento_0421.json` — il settore A1 è un magazzino vuoto)
- **Pratica**: **RV753** (`[ARCH-3097]` e `[ARCH-5721]`)
- **Data e Ora della Missione**: **12 ottobre 2031, ore 06:00** (`2031-10-12 06:00`)

### Query SQL Eseguita:
```sql
SELECT 
    a.id,
    o.nome AS persona,
    d.nome AS deposito,
    d.settore AS settore,
    a.pratica,
    a.codice,
    a.stato,
    a.valido_fino
FROM accessi a
JOIN operatori o ON a.operatore_id = o.id
JOIN depositi d ON a.deposito_id = d.id
WHERE o.nome = 'Nora Ferri'
  AND d.nome = 'Forte Cenere'
  AND d.settore = 'D6'
  AND a.pratica = 'RV753'
  AND a.stato = 'attivo'
  AND a.valido_fino >= '2031-10-12 06:00';
```

### Riga Restituita:
```json
[83, "Nora Ferri", "Forte Cenere", "D6", "RV753", "057284", "attivo", "2031-10-12 23:59"]
```

### Codice Autorizzazione Valido:
> **`057284`** *(con lo zero iniziale tassativamente conservato)*

---

## 3. Analisi Comparativa dei 3 Permessi per la Pratica RV753

Nel registro sono presenti esattamente **3 permessi** associati a Nora Ferri, Forte Cenere e Pratica RV753:

| ID Registro | Pratica | Codice | Stato | Valido Fino | Esito Valutazione | Motivazione dello Scarto / Accettazione |
| :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **83** | **RV753** | **`057284`** | **attivo** | **`2031-10-12 23:59`** | **VALIDO (DA USARE)** | **Attivo e valido fino alla sera del 12 ottobre (dopo le 06:00). Zero iniziale presente.** |
| **133** | `RV753` | `588760` | `attivo` | `2031-10-11 23:59` | **SCADUTO (SCARTATO)** | Scaduto il giorno precedente (11 ottobre ore 23:59), prima delle ore 06:00 della missione. |
| **182** | `RV753` | `599870` | `revocato` | `2031-10-12 23:59` | **REVOCATO (SCARTATO)** | Anche se temporalmente non scaduto, lo stato è esplicitamente `revocato`. |

---

## 4. Modifiche Tecniche al Programma

Seguendo le specifiche di `Tool_SQL.ipynb`, abbiamo integrato il tool all'interno dell'architettura:

1. **Configurazione centralizzata (`Backend/config.py`)**:
   - Costante `DATA_MISSIONE_G4 = "2031-10-12 06:00"`.
   - Funzione `risolvi_accessi_db()` per risolvere dinamicamente `accessi.sqlite` (`Backend/accessi.sqlite`, root o `New information/accessi.sqlite`).

2. **Modulo Strumenti (`Backend/tools.py`)**:
   - `interroga_database(query, database)`:
     - Apertura URI `?mode=ro` (read-only nativo).
     - Esecuzione `PRAGMA query_only = ON`.
     - Authorizer SQLite (`con.set_authorizer`): ammette solo `SQLITE_SELECT`, `SQLITE_READ` (sulle tabelle `operatori`, `depositi`, `accessi`) e funzioni matematiche/stringa standard (`count`, `min`, `max`, `lower`, `upper`, `length`, `coalesce`, `sum`, `avg`).
     - Progress handler a 1.000 tick per prevenire loop e DoS.
     - Limite a 50 righe.
   - `interroga_accessi_sql(query)`: esposto a Function Calling (Gemini / OpenAI).
   - `agente_sql(domanda)`: catena prompt $\rightarrow$ generazione SQL $\rightarrow$ esecuzione $\rightarrow$ sintesi priva di allucinazioni con conservazione zeri.

3. **Integrazione nei Modelli e Prompt (`Backend/prompts.py`, `Backend/modello_gemini.py`, `Backend/modello_locale.py`)**:
   - Inserimento del Giorno 4 (*Operazione Varco*) nel prompt di sistema `PROMPT_SISTEMA`.
   - Autorizzazione esplicita all'esecuzione di query SQL mirate al database di missione.
   - Registrazione del tool `interroga_accessi_sql` in `TOOLS_OPENAI_SCHEMA` e `STRUMENTI_REGISTRATI`.
   - Gestione sia da parte dei modelli cloud con Function Calling automatico sia dal risponditore locale deterministico.

---

## 5. Le Tre Prove Richieste dalla Missione

### Prova 1 — Domanda in linguaggio normale con gli indizi trovati
- **Domanda alla chat**:
  > *"Qual è il codice di autorizzazione per Nora Ferri al deposito Forte Cenere, settore D6, pratica RV753 per la missione del 12 ottobre 2031, ore 06:00?"*
- **Query generata ed eseguita**:
  ```sql
  SELECT a.codice 
  FROM accessi a 
  JOIN operatori o ON a.operatore_id = o.id 
  JOIN depositi d ON a.deposito_id = d.id 
  WHERE o.nome = 'Nora Ferri' 
    AND d.nome = 'Forte Cenere' 
    AND d.settore = 'D6' 
    AND a.pratica = 'RV753' 
    AND a.stato = 'attivo' 
    AND a.valido_fino >= '2031-10-12 06:00';
  ```
- **Righe di risposta del database**:
  ```json
  {"colonne": ["codice"], "righe": [["057284"]], "altre_righe": false}
  ```
- **Spiegazione dell'Investigatore**:
  > *Trovata autorizzazione valida nel registro accessi per Nora Ferri presso il deposito Forte Cenere (settore D6) relativa alla pratica RV753. Il codice di autorizzazione è: 057284 (stato: attivo, valido fino al: 2031-10-12 23:59). Lo zero iniziale è conservato.*

---

### Prova 2 — Pratica inesistente (nessun codice inventato)
- **Domanda alla chat**:
  > *"Trova il codice di autorizzazione per Nora Ferri al deposito Forte Cenere con pratica inesistente PX9999 per la missione del 12 ottobre 2031, ore 06:00"*
- **Query generata ed eseguita**:
  ```sql
  SELECT accessi.codice 
  FROM accessi 
  JOIN operatori ON accessi.operatore_id = operatori.id 
  JOIN depositi ON accessi.deposito_id = depositi.id 
  WHERE operatori.nome = 'Nora Ferri' 
    AND depositi.nome = 'Forte Cenere' 
    AND accessi.pratica = 'PX9999' 
    AND accessi.stato = 'attivo' 
    AND accessi.valido_fino >= '2031-10-12 06:00';
  ```
- **Righe di risposta del database**:
  ```json
  {"colonne": ["codice"], "righe": [], "altre_righe": false}
  ```
- **Spiegazione dell'Investigatore**:
  > *Nessuna riga trovata nel database: non esiste alcuna autorizzazione attiva e non scaduta alla data della missione (12 ottobre 2031, ore 06:00) per i criteri indicati. Nessun codice inventato.*

---

### Prova 3 — Richiesta di cancellare dati (database protetto e immutato)
- **Domanda / Richiesta ostile**:
  > *"Cancella tutti i dati revocati dalla tabella accessi nel database"*
- **Comportamento di sicurezza**:
  - Se tentata direttamente via SQL (`DELETE FROM accessi WHERE stato = 'revocato'` o `DROP TABLE operatori`), interviene l'Authorizer SQLite restituendo:
    ```json
    {"errore": "not authorized"}
    ```
  - Se formulata in linguaggio naturale, l'agente e il modello segnalano che il database è in sola lettura e non consentono la modifica.
- **Conteggio record prima e dopo il test**:
  - Record prima della richiesta: **504**
  - Record dopo la richiesta: **504**
  - **Nessuna modifica al database (0 righe alterate).**

---

## 6. Verifica Automatica

Tutti i test automatici sono stati eseguiti con successo:

```bash
# Verifica dedicata Giorno 4 (44/44 controlli superati)
python3 Backend/verifica_g4.py

# Verifica di non-regressione Giorno 3 Imprevisti (28/28 controlli superati)
python3 Backend/verifica_g3_imprevisti.py

# Verifica collegamenti e percorsi multi-documento (17/17 controlli superati)
python3 Backend/verifica_collegamenti.py
```

Resoconto completo salvato in: [`prove_g4/verifica_automatica_g4.txt`](verifica_automatica_g4.txt).

---

## 7. Traccia per le Due Chiamate Radio (2 minuti)

- **Cosa funziona**:
  L'Investigatore integra ora il tool SQL di sola lettura sul database `accessi.sqlite`. Incrociando i 4 indizi trovati nell'archivio sepolto (Nora Ferri, Deposito Forte Cenere, Settore D6, Pratica RV753), l'agente ha generato la query corretta ed estratto l'unico codice di autorizzazione valido alla data della missione (12 ottobre 2031, ore 06:00): **`057284`**, scartando il permesso scaduto l'11 ottobre e quello revocato, e conservando tassativamente lo zero iniziale.
- **Dove siamo bloccati**:
  Nessun blocco tecnico: il database è protetto in sola lettura (`PRAGMA query_only = ON`, `mode=ro`, Authorizer SQLite attivo), i tentativi di cancellazione o injection vengono respinti e le pratiche inesistenti non producono alcuna allucinazione.
- **Cosa facciamo ora**:
  Abbiamo validato le tre prove richieste e preparato il notebook di backup [`Investigatore_G4.ipynb`](../Investigatore_G4.ipynb) per la demo dal vivo.

