import requests
from datetime import datetime, timedelta

# -------- API-Konfiguration --------
API_KEY = "eyJvcmciOiI2NDA2NTFhNTIyZmEwNTAwMDEyOWJiZTEiLCJpZCI6IjY3MGNiODRhZGY1MDQ0OTNhOTNhNDUyNWMyODg4MWRhIiwiaCI6Im11cm11cjEyOCJ9"  # ersetze mit deinem Key

# -------- Reiseparameter --------
start_id = "8503000"       # Bern
start_name = "Bern"
ziel_id = "8505000"        # Luzern
ziel_name = "Luzern"
uhrzeit = "10:00"
datum = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")  # morgen

# -------- XML-Body erstellen --------
xml_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<OJP xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
     xmlns:xsd="http://www.w3.org/2001/XMLSchema" 
     xmlns="http://www.siri.org.uk/siri" 
     version="1.0" 
     xmlns:ojp="http://www.vdv.de/ojp" 
     xsi:schemaLocation="http://www.siri.org.uk/siri ../ojp-xsd-v1.0/OJP.xsd">
  <OJPRequest>
    <ServiceRequest>
      <RequestTimestamp>{datum}T{uhrzeit}:00Z</RequestTimestamp>
      <RequestorRef>{API_KEY}</RequestorRef>
      <ojp:OJPTripRequest>
        <RequestTimestamp>{datum}T{uhrzeit}:00Z</RequestTimestamp>
        <ojp:Origin>
          <ojp:PlaceRef>
            <ojp:StopPlaceRef>{start_id}</ojp:StopPlaceRef>
            <ojp:LocationName>
              <ojp:Text>{start_name}</ojp:Text>
            </ojp:LocationName>
          </ojp:PlaceRef>
        </ojp:Origin>
        <ojp:Destination>
          <ojp:PlaceRef>
            <ojp:StopPlaceRef>{ziel_id}</ojp:StopPlaceRef>
            <ojp:LocationName>
              <ojp:Text>{ziel_name}</ojp:Text>
            </ojp:LocationName>
          </ojp:PlaceRef>
        </ojp:Destination>
        <ojp:Params>
          <ojp:NumberOfResults>10</ojp:NumberOfResults>
          <ojp:OptimisationMethod>fastest</ojp:OptimisationMethod>
        </ojp:Params>
      </ojp:OJPTripRequest>
    </ServiceRequest>
  </OJPRequest>
</OJP>"""

# -------- Anfrage senden --------
url = "https://api.opentransportdata.swiss/ojp2020"
headers = {
    "Content-Type": "application/xml",
    "Authorization": f"Bearer {API_KEY}"
}

response = requests.post(url, data=xml_body, headers=headers)

# -------- Antwort anzeigen --------
if response.status_code == 200:
    print("✅ Anfrage erfolgreich.")
    print(response.text[:2000])  # nur erster Teil der Antwort
else:
    print("❌ Fehler bei der Anfrage:", response.status_code)
    print(response.text)


import xml.etree.ElementTree as ET

# XML parsen
baum = ET.fromstring(response.text)

# Namespace definieren
ns = {
    'ojp': 'http://www.vdv.de/ojp'
}

# Alle Trips durchgehen
trips = baum.findall('.//ojp:Trip', ns)
print(f"{len(trips)} Verbindungen gefunden.")

for i, trip in enumerate(trips):
    print(f"\n🔹 Verbindung {i + 1}:")
    
    # Alle Legs dieser Verbindung
    legs = trip.findall('.//ojp:TripLeg', ns)
    print(f"   Anzahl Legs: {len(legs)}")

    for leg in legs:
        # Prüfung: hat dieses Leg die erwartete Struktur?
        try:
            board = leg.find('.//ojp:ServiceDeparture/ojp:TimetabledTime', ns)
            alight = leg.find('.//ojp:ServiceArrival/ojp:TimetabledTime', ns)
            line_elem = leg.find('.//ojp:PublishedLineName/ojp:Text', ns)

            if board is not None and alight is not None:
                abfahrt = board.text
                ankunft = alight.text
                linie = line_elem.text if line_elem is not None else "unbekannte Linie"

                print(f"   🕒 {abfahrt} → {ankunft}, Linie: {linie}")
            else:
                print("   ⚠️ Leg ohne Abfahrts- oder Ankunftszeit (evtl. Fußweg?)")

        except AttributeError:
            print("   ❌ Fehler beim Verarbeiten dieses Legs (strukturell unerwartet)")
