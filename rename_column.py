import sqlite3

# Verbindung zur Datenbank
conn = sqlite3.connect("user_data.db")
cursor = conn.cursor()

# Spalte umbenennen:
cursor.execute("""
    ALTER TABLE Reisehistorie
    RENAME COLUMN ab_zeit TO uhrzeit
""")

conn.commit()
conn.close()
print("✅ Spalte erfolgreich umbenannt.")
