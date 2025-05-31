import os
import requests
from datetime import datetime
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()
OJP_API_KEY = os.getenv("OJP_API_KEY")

def stop_place_lookup(ort_name):
    """
    Sucht eine Haltestelle via OJP und gibt (stop_id, stop_name) zurück.
    Im Fehlerfall oder wenn nichts gefunden wurde, (None, None).
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
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
        <MessageIdentifier>mi-{int(datetime.utcnow().timestamp())}</MessageIdentifier>
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
    else:
        # 3. Fallback: erster Treffer
        name, ref = results[0]
        print(f"ℹ️ Kein exakter Treffer, nehme ersten: {name!r} (ID: {ref})")

    # WICHTIG: hier zurückgeben im Format (ID, Name)
    return ref, name


# Beispiel-Aufruf:
start_id, start_name = stop_place_lookup("Kriens, Mattenhof")
print("Start-ID:", start_id, "Start-Name:", start_name)
