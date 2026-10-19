-- Schema del database SQLite per la cronologia dell'Investigatore AI

CREATE TABLE IF NOT EXISTS cronologia_chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domanda TEXT NOT NULL,
    risposta TEXT NOT NULL,
    fonti TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
