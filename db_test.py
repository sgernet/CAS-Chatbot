import mysql.connector

# Verbindung zur MAMP-Datenbank
conn = mysql.connector.connect(
    host="127.0.0.1",
    port=8889,  # MAMP verwendet standardmäßig Port 8889
    user="root",
    password="root",
    database="cas_chatbot"  # dein Datenbankname
)

cursor = conn.cursor()

# Test: Alle Einträge aus der Tabelle 'nutzerprofil' anzeigen
cursor.execute("SELECT * FROM nutzerprofil")
rows = cursor.fetchall()
for row in rows:
    print(row)

conn.close()
