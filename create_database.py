import sqlite3

# Verbindung zur Datenbank herstellen oder erstellen
conn = sqlite3.connect("user_data.db")
cursor = conn.cursor()

# Tabelle: Nutzerprofil
cursor.execute("""
CREATE TABLE IF NOT EXISTS Nutzerprofil (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    adresse TEXT,
    barrierefrei TEXT,         -- 'ja' oder 'nein'
    rasches_umsteigen TEXT,    -- 'ja' oder 'nein'
    eigenes_velo TEXT,         -- 'ja' oder 'nein'
    leihvelo TEXT,             -- 'ja' oder 'nein'
    eigenes_auto TEXT,         -- 'ja' oder 'nein'
    carsharing TEXT,           -- 'ja' oder 'nein'
    wetterpraeferenzen TEXT    -- 'ja' oder 'nein'
)
""")

# Tabelle: Reisehistorie
cursor.execute("""
CREATE TABLE IF NOT EXISTS Reisehistorie (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    datum TEXT,             -- Format: dd.mm.jjjj
    verkehrsmittel TEXT,
    start TEXT,
    ab_zeit TEXT,           -- Format: hh:mm
    ziel TEXT,
    an_zeit TEXT,           -- Format: hh:mm
    erledigung TEXT,
    FOREIGN KEY (user_id) REFERENCES Nutzerprofil(id)
)
""")

# Beispiel-Eintrag für Nutzerin Silvie
cursor.execute("""
INSERT INTO Nutzerprofil (
    name, adresse, barrierefrei, rasches_umsteigen,
    eigenes_velo, leihvelo, eigenes_auto, carsharing, wetterpraeferenzen
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    "Silvie Gernet",
    "Musterstrasse 1, 3000 Bern",
    "ja",
    "nein",
    "ja",
    "nein",
    "nein",
    "ja",
    "ja"
))

conn.commit()
conn.close()

print("📁 Datenbank mit Nutzerprofil und Reisehistorie wurde erfolgreich erstellt.")
