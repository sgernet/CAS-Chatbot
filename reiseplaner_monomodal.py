import os
import json
import re
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from openai import OpenAI
import xml.etree.ElementTree as ET
import dateparser
from datetime import datetime, timezone
from dateparser.search import search_dates
import re
import json


# ------------------ Vorbereitung ------------------
load_dotenv()
try:
    OPENAI_KEY = os.environ["OPENAI_API_KEY"]
    OJP_API_KEY   = os.environ["OJP_API_KEY"]
except KeyError as e:
    raise RuntimeError(f"Umgebungsvariable {e.args[0]} fehlt!") from None

client = OpenAI(api_key=OPENAI_KEY)


# ------------------ Vorbereitung Chat & System ------------------
messages = [{
    "role": "system",
    "content": (
        "Du bist ein freundlicher und hilfsbereiter Mobilitäts-Chatbot."
        "Du planst für den Nutzer eine Reise mit dem öffentlichen Verkehr in der Schweiz."
        "Dein Ziel ist es, die Informationen zur Reiseplanung vom Nutzer zu sammeln: Startort, Zielort, Datum und Uhrzeit. "
        "Führe einen natürlichen und lockeren Dialog per Du. Stelle gezielte Rückfragen, wenn etwas fehlt. "
        "Sobald du alle Infos hast, gib **ausschließlich** ein JSON-Objekt aus:\n"
        "{\"start\": \"...\", \"ziel\": \"...\", \"datum\": \"YYYY-MM-DD\", \"uhrzeit\": \"HH:MM:SS\"}"
        "Direkt nachdem die Verbindungen angezeigt wurden, frage den Nutzer, ob alles klar ist, ob er die Reise durchführt "
        "und welche Verbindung er wählen wird. Führe den Dialog so lange fort, bis "
        "der Nutzer keine Fragen mehr hat, und dir die Reise bestätigt hat. "
        "Beende das Gespräch und wünsche ihm eine gute Reise. Sei kreativ und überraschend."
        "Schreibe am Ende deiner letzten Antwort auf einer eigenen Zeile nur '<ENDE>'."
    )
},
{
    "role": "assistant",
    "content": "Wohin möchtest du reisen und wann?"  # Erste Frage kommt vom Chatbot
}]

reiseinfos = None  # Wird später gesetzt

# Erste Bot-Frage ausgeben
print("🤖 Bot:", messages[1]["content"])

# ------------------ Hilfsfunktion Datumerkennung ------------------
# 1) Mappe deutsche Wochentags-Namen auf Zahlen
tage = {
    'montag': 0, 'dienstag': 1, 'mittwoch': 2,
    'donnerstag': 3, 'freitag': 4, 'samstag': 5, 'sonntag': 6
}

def replace_date_keywords(text: str) -> str:
    """
    Ersetzt in `text`:
      - 'nächsten <Wochentag>' per Hand in das nächste Datum
      - alle anderen relativen Ausdrücke via dateparser
    """
    # Finde alle relativen Fragmente
    pattern = re.compile(r'\b(heute|gestern|morgen|übermorgen|nächsten?\s+\w+)\b', re.IGNORECASE)

    def repl(match):
        frag = match.group(0)                             # z.B. "nächsten Montag"
        # 2) Normalisieren: 'nächsten' → 'nächster'
        frag_norm = re.sub(r'(?i)\bnächsten\b', 'nächster', frag)

        # 3) Manuelle Wochentags-Berechnung, falls 'nächster <Tag>'
        m = re.match(r'(?i)nächster\s+(\w+)', frag_norm)
        if m:
            tag = m.group(1).lower()
            if tag in tage:
                heute = datetime.now()
                ziel_wd = tage[tag]
                delta = (ziel_wd - heute.weekday() + 7) % 7
                if delta == 0:
                    delta = 7
                dt = heute + timedelta(days=delta)
                return dt.strftime('%Y-%m-%d')

        # 4) Sonst: dateparser bemühen (z.B. 'morgen', 'übermorgen')
        dt = dateparser.parse(
            frag_norm,
            settings={'PREFER_DATES_FROM': 'future'},
            languages=['de']
        )
        if dt:
            return dt.strftime('%Y-%m-%d')

        # 5) Falls alles scheitert, gib das Original zurück
        return frag

    return pattern.sub(repl, text)

# ------------------ Chat-Schleife ------------------
while True:
    # 1) Frage den User
    user_input = input("🧳 Du: ")
    cleaned_input = replace_date_keywords(user_input)
    if cleaned_input != user_input:
        print(f"ℹ️ Datumsausdruck ersetzt:\n  {user_input!r}\n→ {cleaned_input!r}")
    messages.append({"role": "user", "content": cleaned_input})

    # 2) Anfrage an OpenAI
    antwort = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    reply = antwort.choices[0].message.content.strip()
    print("🤖 Bot:", reply)

    # 3) JSON-Extraktion und Validierung
    match = re.search(r'\{.*\}', reply, re.DOTALL)
    if match:
        try:
            reiseinfos = json.loads(match.group(0))
            print("\n✅ JSON erfolgreich erkannt:")
            print(json.dumps(reiseinfos, indent=2))
            break   # **Schleife hier verlassen** – kein weiteres input() nötig
        except json.JSONDecodeError:
            # fand zwar `{…}`, war aber kein valides JSON → weiterfragen
            pass

    # 4) kein valides JSON → Bot-Antwort merken und Schleife fortsetzen
    messages.append({"role": "assistant", "content": reply})

    reiseinfos = {
        "start": "Zürich",
        "ziel": "Luzern",
        "datum": datetime.now().strftime("%Y-%m-%d"),
        "uhrzeit": "08:00:00"
    }

today = datetime.now()
# Hat der User im Roh-Input kein Jahr genannt?
user_hat_jahr = bool(re.search(r'\b\d{4}\b', cleaned_input))

# Parsed-Datum aus GPT
datum = reiseinfos.get("datum", "")

try:
    dt = datetime.strptime(datum, "%Y-%m-%d")
    # Wenn GPT ein anderes Jahr als heute verwendet hat und
    # der User selbst kein Jahr genannt hat: Jahr ersetzen
    if dt.year != today.year and not user_hat_jahr:
        dt = dt.replace(year=today.year)
        print(f"ℹ️ Jahr auf {today.year} korrigiert.")
    datum = dt.strftime("%Y-%m-%d")
except ValueError:
    print("⚠️ Ungültiges Datum. Verwende heutiges Datum.")
    datum = today.strftime("%Y-%m-%d")

# … Post-Processing, das `datum = dt.strftime(...)` setzt …

# zurückschreiben:
reiseinfos["datum"] = datum

# und dann weiter mit:
uhrzeit = reiseinfos.get("uhrzeit", "08:00:00")



# ------------------ Funktion zur Ortssuche per API ------------------
def stop_place_lookup(ort_name):
    """
    Sucht eine Haltestelle via OJP und gibt (stop_id, stop_name) zurück.
    Im Fehlerfall oder wenn nichts gefunden wurde, (None, None).
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<OJP xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xmlns:xsd="http://www.w3.org/2001/XMLSchema"
     xmlns="http://www.siri.org.uk/siri"
     xmlns:ojp="http://www.vdv.de/ojp"
     version="1.0"
     xsi:schemaLocation="http://www.siri.org.uk/siri ../ojp-xsd-v1.0/OJP.xsd">
  <OJPRequest>
    <ServiceRequest>
      <RequestTimestamp>{timestamp}</RequestTimestamp>
      <RequestorRef>IRMA</RequestorRef>
      <ojp:OJPLocationInformationRequest>
        <RequestTimestamp>{timestamp}</RequestTimestamp>
        <MessageIdentifier>mi-{int(datetime.now(timezone.utc).timestamp())}</MessageIdentifier>
        <ojp:InitialInput>
          <ojp:LocationName>{ort_name}</ojp:LocationName>
        </ojp:InitialInput>
        <ojp:Restrictions>
          <ojp:Type>stop</ojp:Type>
          <ojp:IncludePtModes>true</ojp:IncludePtModes>
        </ojp:Restrictions>
      </ojp:OJPLocationInformationRequest>
    </ServiceRequest>
  </OJPRequest>
</OJP>
"""

    url = "https://api.opentransportdata.swiss/ojp2020"
    headers = {
        "Content-Type": "application/xml",
        "Authorization": f"Bearer {OJP_API_KEY}"
    }

    print(f"🔍 Suche Ort: {ort_name!r}")
    resp = requests.post(url, data=xml_body.encode("utf-8"), headers=headers)
    print("Statuscode:", resp.status_code)
    if resp.status_code != 200:
        print(f"❌ Fehler bei Ortssuche: {resp.status_code}")
        return None, None

    ns = {
        'ojp': 'http://www.vdv.de/ojp',
        's': 'http://www.siri.org.uk/siri'
    }
    tree = ET.fromstring(resp.text)

    # 1. Sammle alle StopPlace-Treffer
    results = []
    for sp in tree.findall('.//ojp:StopPlace', ns):
        ref = sp.findtext('.//ojp:StopPlaceRef', namespaces=ns)
        name = sp.findtext('.//ojp:StopPlaceName/ojp:Text', namespaces=ns)
        if ref and name:
            results.append((name, ref))

    if not results:
        print("⚠️ Kein gültiger Ort gefunden.")
        return None, None

    # 2. Versuch einer exakten Übereinstimmung zur Eingabe (ohne Fallunterscheidung)
    ort_lower = ort_name.strip().lower()
    exact = [(n, r) for n, r in results if n.strip().lower() == ort_lower]

    if exact:
        name, ref = exact[0]
        print(f"✅ Exakt gefunden: {name!r} (ID: {ref})")
    elif len(results) > 1:
        # 2.b) Mehrere Treffer, aber kein exakter → User-Auswahl
        print("🔍 Ich habe mehrere Haltestellen gefunden. Bitte wähle die Nummer:")
        for i, (n, _) in enumerate(results, start=1):
            print(f"  {i}) {n}")
        # Solange fragen, bis valide Zahl kommt
        while True:
            choice = input("🧳 Du (Nummer eingeben): ")
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(results):
                    name, ref = results[idx]
                    print(f"✅ Du hast gewählt: {name!r} (ID: {ref})")
                    break
            print(f"⚠️ Ungültig. Bitte Zahl zwischen 1 und {len(results)}.")

    else:
        # 2.c) Kein exakter Treffer, aber nur ein Element → Fallback
        name, ref = results[0]
        print(f"ℹ️ Kein exakter Treffer, nehme ersten: {name!r} (ID: {ref})")

    # WICHTIG: hier zurückgeben im Format (ID, Name)
    return ref, name


# ------------------ Datum und Uhrzeit prüfen ------------------
datum = reiseinfos.get("datum", datetime.now().strftime("%Y-%m-%d"))
uhrzeit = reiseinfos.get("uhrzeit", "08:00:00")

# 1) Jahr ergänzen, wenn nur MM-DD angegeben
#    Erlaubt ein- oder zweistellige Mon/Day, mit einem Bindestrich
if re.match(r'^\d{1,2}-\d{1,2}$', datum):
    today = datetime.now()
    month, day = map(int, datum.split('-'))
    try:
        # Erstelle ein Datum mit dem aktuellen Jahr
        dt = datetime(year=today.year, month=month, day=day)
        datum = dt.strftime("%Y-%m-%d")
        print(f"ℹ️ Jahr ergänzt, neues Datum: {datum}")
    except ValueError:
        # Ungültiges Datum (z.B. 02-30)
        print("⚠️ Ungültiges Datum ohne Jahr. Verwende heutiges Datum.")
        datum = today.strftime("%Y-%m-%d")

# 2) Vollständiges Datum validieren (YYYY-MM-DD)
try:
    datetime.strptime(datum, "%Y-%m-%d")
except ValueError:
    print("⚠️ Ungültiges Datumsformat. Verwende heutiges Datum.")
    datum = datetime.now().strftime("%Y-%m-%d")

# 3) Uhrzeit normalisieren
uhrzeit_match = re.match(r"^(\d{1,2}):?(\d{2})?:?(\d{2})?$", uhrzeit)
if uhrzeit_match:
    std = uhrzeit_match.group(1).zfill(2)
    min = uhrzeit_match.group(2) if uhrzeit_match.group(2) else "00"
    sek = uhrzeit_match.group(3) if uhrzeit_match.group(3) else "00"
    uhrzeit = f"{std}:{min}:{sek}"
else:
    print("⚠️ Ungültiges Uhrzeitformat. Verwende 08:00:00.")
    uhrzeit = "08:00:00"

# Debug-Ausgabe
print(f"\n📅 Abfahrtsdatum: {datum}")
print(f"⏰ Uhrzeit: {uhrzeit}")



# ------------------ Start- und Zielort dynamisch holen ------------------
start_id, start_name = stop_place_lookup(reiseinfos["start"])
ziel_id, ziel_name = stop_place_lookup(reiseinfos["ziel"])

# Aktuelle UTC-Zeit im passenden Format für RequestTimestamp
now_utc = datetime.now().strftime("%Y-%m-%dT%H:%M")

# ------------------ XML-Abfrage an OJP-TripRequest ------------------
xml_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<OJP xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xmlns:xsd="http://www.w3.org/2001/XMLSchema"
     xmlns="http://www.siri.org.uk/siri"
     version="1.0"
     xmlns:ojp="http://www.vdv.de/ojp"
     xsi:schemaLocation="http://www.siri.org.uk/siri ../ojp-xsd-v1.0/OJP.xsd">
  <OJPRequest>
    <ServiceRequest>
      <RequestTimestamp>{now_utc}:00Z</RequestTimestamp>
      <RequestorRef>test</RequestorRef>
      <ojp:OJPTripRequest>
        <RequestTimestamp>{now_utc}:00Z</RequestTimestamp>
        <ojp:Origin>
          <ojp:PlaceRef>
            <ojp:StopPlaceRef>{start_id}</ojp:StopPlaceRef>
            <ojp:LocationName>
              <ojp:Text>{start_name}</ojp:Text>
            </ojp:LocationName>
          </ojp:PlaceRef>
          <ojp:DepArrTime>{datum}T{uhrzeit}Z</ojp:DepArrTime>
        </ojp:Origin>
        <ojp:Destination>
          <ojp:PlaceRef>
            <ojp:StopPlaceRef>{ziel_id}</ojp:StopPlaceRef>
            <ojp:LocationName>
              <ojp:Text>{ziel_name}</ojp:Text>
            </ojp:LocationName>
          </ojp:PlaceRef>
          <ojp:DepArrTime>{datum}T{uhrzeit}Z</ojp:DepArrTime>
        </ojp:Destination>
        <ojp:Params>
          <ojp:NumberOfResults>5</ojp:NumberOfResults>
          <ojp:OptimisationMethod>fastest</ojp:OptimisationMethod>
        </ojp:Params>
      </ojp:OJPTripRequest>
    </ServiceRequest>
  </OJPRequest>
</OJP>
"""

# ------------------ Anfrage senden ------------------
url = "https://api.opentransportdata.swiss/ojp2020"
headers = {
    "Content-Type": "application/xml",
    "Authorization": f"Bearer {OJP_API_KEY}"
}

response = requests.post(url, data=xml_body, headers=headers)

if response.status_code != 200:
    print("\n❌ Fehler bei der Anfrage:", response.status_code)
    print(response.text)
    exit()

# ------------------ Antwort speichern ------------------

with open("response.xml", "w", encoding="utf-8") as f:
    f.write(response.text)

print("✅ Die Antwort wurde als 'response.xml' gespeichert.")

# ------------------ XML-Antwort verarbeiten ------------------


# XML einlesen
#!/usr/bin/env python3
import xml.etree.ElementTree as ET
from datetime import datetime
import sys, os

def get_text(elem, path, ns):
    sub = elem.find(path, ns)
    return sub.text if sub is not None and sub.text is not None else ''

def parse_and_sort_trips(xml_path):
    ns = {'siri': 'http://www.siri.org.uk/siri', 'ojp': 'http://www.vdv.de/ojp'}
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # 1. Alle Trip-Elemente finden
    trips = root.findall('.//ojp:TripResult/ojp:Trip', ns)
    if not trips:
        print("Keine Trip-Daten in der XML gefunden.")
        sys.exit(1)

    # 2. Für jeden Trip Abfahrts- und Ankunftszeit auslesen und Dauer berechnen
    trip_durations = []
    for trip in trips:
        legs = trip.findall('ojp:TripLeg', ns)
        dep_times = []
        arr_times = []
        for leg in legs:
            t = leg.find('ojp:TimedLeg', ns)
            if t is not None:
                board  = t.find('ojp:LegBoard', ns)
                alight = t.find('ojp:LegAlight', ns)

                dep_str = board.find('.//ojp:TimetabledTime', ns).text
                arr_str = alight.find('.//ojp:TimetabledTime', ns).text

                dep_times.append(dep_str)
                arr_times.append(arr_str)

        if not dep_times:
            continue

        dep_dt = datetime.fromisoformat(dep_times[0].rstrip('Z'))
        arr_dt = datetime.fromisoformat(arr_times[-1].rstrip('Z'))
        duration = arr_dt - dep_dt
        trip_durations.append((trip, duration))
 



    if not trip_durations:
        print("Keine fahrplanmäßigen Legs gefunden.")
        sys.exit(1)

    # 3. Trips aufsteigend nach Dauer sortieren
    sorted_trips = sorted(trip_durations, key=lambda x: x[1])

    # Schnellste Verbindung abtrennen
    best_trip, best_duration = sorted_trips[0]
    alternatives = sorted_trips[1:]

    def build_steps(trip):
        steps = []
        for leg in trip.findall('ojp:TripLeg', ns):
            t = leg.find('ojp:TimedLeg', ns)
            if t is not None:
                board   = t.find('ojp:LegBoard', ns)
                alight  = t.find('ojp:LegAlight', ns)
                service = t.find('ojp:Service', ns)
                steps.append({
                    'type': 'ride',
                    'line':      get_text(service, 'ojp:PublishedLineName/ojp:Text', ns),
                    'dep_sta':   get_text(board,  'ojp:StopPointName/ojp:Text', ns),
                    'dep_time':  get_text(board,  './/ojp:TimetabledTime', ns).split('T')[-1].rstrip('Z'),
                    'dep_quay':  get_text(board,  'ojp:PlannedQuay/ojp:Text', ns),
                    'arr_sta':   get_text(alight, 'ojp:StopPointName/ojp:Text', ns),
                    'arr_time':  get_text(alight, './/ojp:TimetabledTime', ns).split('T')[-1].rstrip('Z'),
                    'arr_quay':  get_text(alight, 'ojp:PlannedQuay/ojp:Text', ns)
                })
            else:
                tr = leg.find('ojp:TransferLeg', ns)
                if tr is not None:
                    steps.append({
                        'type':     'walk',
                        'mode':     get_text(tr, 'ojp:TransferMode', ns),
                        'from':     get_text(tr, 'ojp:LegStart/ojp:LocationName/ojp:Text', ns),
                        'to':       get_text(tr, 'ojp:LegEnd/ojp:LocationName/ojp:Text', ns),
                        'duration': get_text(tr, 'ojp:Duration', ns).lstrip('PT').lower()
                    })
        return steps

    # 4. Ausgabe

    # --- Beste Verbindung ---
    print("Schnellste Verbindung:")
    print(f"Dauer: {best_duration}")
    best_steps = build_steps(best_trip)
    for i, s in enumerate(best_steps, 1):
        if s['type'] == 'ride':
            print(f"{i}. 🚆 {s['line']}: {s['dep_sta']} ({s['dep_time']} Uhr, Gleis {s['dep_quay'] or '–'}) → "
                  f"{s['arr_sta']} ({s['arr_time']} Uhr, Gleis {s['arr_quay'] or '–'})")
        else:
            print(f"{i}. 🚶 {s['mode'].capitalize()} von {s['from']} nach {s['to']} (Dauer {s['duration']})")

    # --- Alternative Verbindungen ---
    if alternatives:
        print("\nAlternative Verbindungen:")
        for idx, (trip, dur) in enumerate(alternatives, 1):
            print(f"\nAlternative {idx} (Dauer: {dur}):")
            alt_steps = build_steps(trip)
            for i, s in enumerate(alt_steps, 1):
                if s['type'] == 'ride':
                    print(f"{i}. 🚆 {s['line']}: {s['dep_sta']} ({s['dep_time']} Uhr, Gleis {s['dep_quay'] or '–'}) → "
                          f"{s['arr_sta']} ({s['arr_time']} Uhr, Gleis {s['arr_quay'] or '–'})")
                else:
                    print(f"{i}. 🚶 {s['mode'].capitalize()} von {s['from']} nach {s['to']} (Dauer {s['duration']})")

if __name__ == '__main__':
    xml_file = sys.argv[1] if len(sys.argv) > 1 else 'response.xml'
    xml_file = os.path.expanduser(xml_file)
    print(f"Verarbeite XML-Datei: {xml_file}\n")
    parse_and_sort_trips(xml_file)

#----------------------------- Chatbot-Interaktion für Abschluss ------------------

#Anfrage an OpenAI
antwort = client.chat.completions.create(
    model="gpt-4o",
    messages=messages
)
reply = antwort.choices[0].message.content.strip()
print("🤖 Bot:", reply)

while True:
    user_input = input("🧳 Du: ").strip()
    if not user_input:
        print("🤖 Bot: Ich habe dich nicht verstanden. Kannst du das bitte wiederholen?")
        continue

    messages.append({"role": "user", "content": user_input})

    antwort = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    bot_reply = antwort.choices[0].message.content.strip()

    if "<ENDE>" in bot_reply:
        sauberer_teil = bot_reply.replace("<ENDE>", "").strip()
        if sauberer_teil:
            print("🤖 Bot:", sauberer_teil)
        break

    print("🤖 Bot:", bot_reply)
    messages.append({"role": "assistant", "content": bot_reply})