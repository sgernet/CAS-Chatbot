import os
from openai import OpenAI
from dotenv import load_dotenv

# .env-Datei laden
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=api_key)

# Benutzereingabe
eingabe = input("Wohin möchtest du reisen? ")

# Anfrage an OpenAI senden
antwort = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {
            "role": "system",
            "content": (
                "Extrahiere Start, Ziel und Uhrzeit aus einem Reisesatz "
                "und gib sie im JSON-Format mit den Schlüsseln 'start_name', 'ziel_name', 'zeit' zurück."
            )
        },
        {"role": "user", "content": eingabe}
    ]
)

# Ausgabe anzeigen
print("\nErkannte Informationen:")
print(antwort.choices[0].message.content)
