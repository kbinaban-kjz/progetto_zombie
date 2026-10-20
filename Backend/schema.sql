-- Schema del database SQLite per l'Investigatore AI (Protocollo Lazzaro)

-- Tabella per la cronologia di domande, risposte e fonti utilizzate
CREATE TABLE IF NOT EXISTS cronologia_chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domanda TEXT NOT NULL,
    risposta TEXT NOT NULL,
    fonti TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Tabella per i metadati di instradamento del routing ibrido (Locale vs Cloud)
CREATE TABLE IF NOT EXISTS instradamento_chat (
    id_messaggio INTEGER PRIMARY KEY,
    motore TEXT NOT NULL,
    modello_usato TEXT NOT NULL,
    complessita TEXT NOT NULL,
    motivo_routing TEXT NOT NULL,
    durata_ms INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (id_messaggio) REFERENCES cronologia_chat(id) ON DELETE CASCADE
);
