# Datei: chatbot_util.py
import re
from datetime import datetime, timedelta, timezone
import dateparser
import xml.etree.ElementTree as ET
import requests


tage = {
    'montag': 0, 'dienstag': 1, 'mittwoch': 2,
    'donnerstag': 3, 'freitag': 4, 'samstag': 5, 'sonntag': 6
}

def replace_date_keywords(text: str) -> str:
    pattern = re.compile(r'\b(heute|gestern|morgen|übermorgen|nächsten?\s+\w+)\b', re.IGNORECASE)

    def repl(match):
        frag = match.group(0)
        frag_norm = re.sub(r'(?i)\bnächsten\b', 'nächster', frag)

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

        dt = dateparser.parse(frag_norm, settings={'PREFER_DATES_FROM': 'future'}, languages=['de'])
        if dt:
            return dt.strftime('%Y-%m-%d')

        return frag

    return pattern.sub(repl, text)

def get_text(elem, path, ns):
    sub = elem.find(path, ns)
    return sub.text if sub is not None and sub.text is not None else ''

def stop_place_lookup(ort_name: str):
    from streamlit import secrets

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml_body = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<OJP xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"
     xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\"
     xmlns=\"http://www.siri.org.uk/siri\"
     xmlns:ojp=\"http://www.vdv.de/ojp\"
     version=\"1.0\"
     xsi:schemaLocation=\"http://www.siri.org.uk/siri ../ojp-xsd-v1.0/OJP.xsd\">
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
</OJP>"""

    url = "https://api.opentransportdata.swiss/ojp2020"
    headers = {
        "Content-Type": "application/xml",
        "Authorization": f"Bearer {secrets['OJP_API_KEY']}"
    }
    resp = requests.post(url, data=xml_body.encode("utf-8"), headers=headers)
    if resp.status_code != 200:
        return None

    ns = {'ojp': 'http://www.vdv.de/ojp', 's': 'http://www.siri.org.uk/siri'}
    tree = ET.fromstring(resp.text)
    results = []
    for sp in tree.findall('.//ojp:StopPlace', ns):
        ref  = sp.findtext('.//ojp:StopPlaceRef', namespaces=ns)
        name = sp.findtext('.//ojp:StopPlaceName/ojp:Text', namespaces=ns)
        if ref and name:
            results.append((ref, name))

    return results if results else None

def parse_trips(xml_text: str):
    ns = {'ojp': 'http://www.vdv.de/ojp'}
    root = ET.fromstring(xml_text)
    trips = root.findall('.//ojp:TripResult/ojp:Trip', ns)
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
                dep_times.append(board.find('.//ojp:TimetabledTime', ns).text)
                arr_times.append(alight.find('.//ojp:TimetabledTime', ns).text)
        if dep_times:
            dep_dt = datetime.fromisoformat(dep_times[0].rstrip('Z'))
            arr_dt = datetime.fromisoformat(arr_times[-1].rstrip('Z'))
            duration = arr_dt - dep_dt
            trip_durations.append((trip, duration))

    if not trip_durations:
        return [], []

    sorted_trips = sorted(trip_durations, key=lambda x: x[1])
    best_trip = sorted_trips[0][0]
    alts = [t[0] for t in sorted_trips[1:]]

    def build_steps(trip):
        steps = []
        for leg in trip.findall('ojp:TripLeg', ns):
            t = leg.find('ojp:TimedLeg', ns)
            if t is not None:
                board   = t.find('ojp:LegBoard', ns)
                alight  = t.find('ojp:LegAlight', ns)
                service = t.find('ojp:Service', ns)
                steps.append({
                    'type':     'ride',
                    'line':     service.find('.//ojp:PublishedLineName/ojp:Text', ns).text,
                    'dep_sta':  board.find('.//ojp:StopPointName/ojp:Text', ns).text,
                    'dep_time': board.find('.//ojp:TimetabledTime', ns).text.split('T')[-1].rstrip('Z'),
                    'dep_quay': get_text(board, 'ojp:PlannedQuay/ojp:Text', ns) or '–',
                    'arr_sta':  alight.find('.//ojp:StopPointName/ojp:Text', ns).text,
                    'arr_time': alight.find('.//ojp:TimetabledTime', ns).text.split('T')[-1].rstrip('Z'),
                    'arr_quay': get_text(board, 'ojp:PlannedQuay/ojp:Text', ns) or '–',
                })
            else:
                trf = leg.find('ojp:TransferLeg', ns)
                if trf is not None:
                    steps.append({
                        'type':     'walk',
                        'mode':     trf.find('.//ojp:TransferMode', ns).text,
                        'from':     trf.find('.//ojp:LegStart/ojp:LocationName/ojp:Text', ns).text,
                        'to':       trf.find('.//ojp:LegEnd/ojp:LocationName/ojp:Text', ns).text,
                        'duration': trf.find('ojp:Duration', ns).text.lstrip('PT').lower()
                    })
        return steps

    return build_steps(best_trip), [build_steps(t) for t in alts]
