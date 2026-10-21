# Consegna Giorno 3 — Imprevisti (pacchetto `dati_imprevisti_gg3`)

Tutte le risposte sotto sono prodotte dal programma (RAG sull'archivio unito + `Backend/evidenze.py`),
non scritte a mano. Resoconto completo e riproducibile: `prove_g3/verifica_imprevisti_gg3.txt`
(`python Backend/verifica_g3_imprevisti.py` → 28/28 controlli).

## 1. Archivio unito e indice aggiornato

- Prima: 1.023 documenti, 9.383 blocchi. Dopo: **1.523 documenti, 10.366 blocchi** (+500 file `LX5_*.txt`).
- Il nome di ogni fonte è conservato (file `LX5_2775.txt`, ID `LX5-2775`) e compare in ogni risposta.
- Il loader non entrava nelle sottocartelle di `dati/`: `dati/dati_imprevisti_gg3` è stato aggiunto alle cartelle dell'archivio
  (`config.IMPREVISTI_DIR`, `sources.risolvi_cartelle_dati`).
- La cache dell'indice usava solo (numero file, primo, ultimo): ora usa un'impronta del contenuto, anche per la cache degli embedding.

## 2. Canale di evacuazione EV-541, giorno operativo 03

**Usare Ripetitore Pietra, circuito CN-58.**

| Documento | Cosa dice | Tipo |
| :-- | :-- | :-- |
| `LX5_2775.txt` [LX5-2775] collaudo 08:20 | Pietra: alimentazione presente, CN-58, invio riuscito, ricevuta. Salice: alimentazione assente, invio fallito. «Misure eseguite direttamente sul posto», firmato | **misura diretta** |
| `LX5_8820.txt` [LX5-8820] rettifica 08:30 | Salice fuori servizio, «Usare Ripetitore Pietra, circuito CN-58», «sostenuta dal collaudo delle 08:20» | rettifica, **dipende da LX5-2775** |
| 80 documenti (es. `LX5_1001.txt`, `LX5_1062.txt`, `LX5_1226.txt`) | «Ripetitore Salice è attivo» | **copie inoltrate** del bollettino B-517 delle 07:50 |

**Conferme realmente indipendenti: 1** (il collaudo LX5-2775). Su 82 documenti che citano EV-541: 1 misura diretta, 1 rettifica
che si appoggia a quella misura, 80 copie che ripetono la stessa origine (B-517, stato del giorno precedente, «riproduzione senza
verifica sul posto», «non sono state raccolte nuove misurazioni»).

### Come distinguiamo copie e misure dirette

`sources.classifica_provenienza()` classifica ogni documento da marcatori testuali: `misura_diretta` («eseguite direttamente sul posto»,
«esito firmato»), `rettifica`, `copia_inoltrata` («riproduzione senza verifica», «ha copiato l'indicazione», «catena di inoltro»…),
`voce` («ho sentito dire»…), `registro`. `evidenze.analizza_conferme_segnale()` raggruppa le copie per origine (B-517 → un'origine),
collega ogni rettifica alla misura che cita (stesso orario del collaudo) e conta come indipendenti solo le misure dirette.
Il RAG tiene una sola copia per ricerca (`copie_collassate`), così 80 inoltri non occupano i top-k.

## 3. Brani recuperati e ricerca ripetuta con domande diverse

Domanda A: «Nel giorno operativo 03, quale ripetitore e quale circuito usare per il segnale EV-541? Quante conferme realmente
indipendenti avete?» → RAG: `LX5_8820.txt`, `LX5_2775.txt` in testa (brani nel resoconto, sezione C).

Domande diverse, stessa conclusione:
- «Ripetitore Salice è attivo per EV-541 oggi? Chi lo conferma davvero?» → Pietra CN-58, Salice scartato.
- «Quale circuito CN trasmette il segnale di evacuazione nel giorno operativo 03?» (senza codice EV) → il programma ricava EV-541 dalle misure.

## 4. Il modulo nella custodia schermata del corriere Nebbia

**Officina Ardesia, settore L6, armadio 4** (modulo di ricambio per radio secondaria).

RAG a salti, ogni salto è una nuova domanda sul codice-ponte del documento precedente:

1. «Dove si trova il modulo nella custodia schermata consegnata dal corriere Nebbia…?» → `LX5_2398.txt`: Nebbia ha consegnato una custodia schermata, presa in carico nella **pratica M562**.
2. «Cosa riporta la pratica M562?» → `LX5_1221.txt`: pratica M562 = **lotto K591**, contenuto «modulo di ricambio per radio secondaria».
3. «Dove è stato ricevuto il lotto K591?» → `LX5_1749.txt`: lotto K591 ricevuto a **Officina Ardesia, settore L6, armadio 4**.

Scartato dal programma: seconda consegna del corriere Eco (pratica M526, lotto K519, «supporto vuoto», Officina Cenotafio Z9);
la voce `LX5_6941.txt` («ho sentito dire… Cenotafio», nessuna pratica, nessuna consegna vista); 90 documenti con codici a suffisso
(`M562-098`, `K591-098`) che sono altre spedizioni, non il riferimento M562/K591.

Domanda diversa: «Recuperate un canale di evacuazione e localizzate un ricambio radio.» → stessa risposta (Pietra CN-58 + Ardesia L6 armadio 4),
arrivando alla catena dal documento del ricambio (`LX5_1221`) e risalendo a Nebbia.
Domanda senza risposta: «Qual è il nome civile del corriere Nebbia?» → «Non documentato», con la frase di `LX5_2398` che lo dichiara.

## 5. Modifiche al programma

| File | Modifica |
| :-- | :-- |
| `Backend/config.py`, `Backend/sources.py` | Cartella `dati_imprevisti_gg3` nell'archivio unito; cache basata sul contenuto; `classifica_provenienza`; collasso delle copie nel RAG; `provenienza` e `copie_collassate` nei risultati |
| `Backend/evidenze.py` (nuovo) | Analisi copie/misure/rettifiche e conferme indipendenti; RAG a salti con domande successive; astensione su dati dichiarati assenti |
| `Backend/modello_locale.py`, `Backend/tools.py`, `Backend/cli.py` | Integrazione nel risponditore, tool `analizza_evidenze`, comando `/catena`, `/rag` mostra brani, provenienza e copie escluse |
| `Backend/verifica_g3_imprevisti.py` (nuovo) | 28 controlli automatici, inclusa la regressione |

## 6. Regressione dopo la modifica

Domande già riuscite prima, ripetute dopo (stessa risposta): «Quale persona si è opposta al progetto LAZZARO aprendo una pratica…»
(Nora Ferri, RV753, `[ARCH-3097]`), «Dove è scoppiato il primo focolaio e a che ora?» (San Mauro 01:12, `[G2-01]`), la domanda LUME
senza prova (`Non documentato`, `[ARCH-5721]`). Confronto prima/dopo fatto anche con Qwen attivo: risposte identiche.

Problemi **già presenti prima** e non risolti da questa consegna: «Chi ha cercato di fermare il progetto?» solleva `Troppi documenti`
con Qwen, e «Cosa è successo nei rifugi?» risponde con una voce di Wikipedia (il responder deterministico sceglie per radici di parole).
