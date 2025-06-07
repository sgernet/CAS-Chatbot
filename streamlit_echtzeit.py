import os
import requests
import xml.etree.ElementTree as ET
from google.transit import gtfs_realtime_pb2
from datetime import datetime, timedelta, timezone
import streamlit as st

# ------------------------- 1) API-Keys aus secrets laden -------------------------
GTFS_RT_API_KEY = st.secrets.get("GTFS_RT_API_KEY")
OJP_API_KEY    = st.secrets.get("OJP_API_KEY")

if not GTFS_RT_API_KEY:
    st.error("❌ Bitte lege in .streamlit/secrets.toml GTFS_RT_API_KEY an.")
    st.stop()
if not OJP_API_KEY:
    st.error("❌ Bitte lege in .streamlit/secrets.toml OJP_API_KEY an.")
    st.stop()

# ------------------------- 2) OJP Stop-Place-Lookup Funktion -------------------------
def stop_place_lookup(ort_name: str):
    """
    Sucht eine Haltestelle via OJP API. Gibt Liste von (stop_id, stop_name) oder None zurück.
    """
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
      <RequestorRef>DelayBot</RequestorRef>
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
    headers = {"Content-Type": "application/xml", "Authorization": f"Bearer {OJP_API_KEY}"}
    resp = requests.post(url, data=xml_body.encode('utf-8'), headers=headers)
    if resp.status_code != 200:
        return None
    ns = {'ojp': 'http://www.vdv.de/ojp', 's': 'http://www.siri.org.uk/siri'}
    tree = ET.fromstring(resp.text)
    results = []
    for sp in tree.findall('.//ojp:StopPlace', ns):
        ref = sp.findtext('.//ojp:StopPlaceRef', namespaces=ns)
        name = sp.findtext('.//ojp:StopPlaceName/ojp:Text', namespaces=ns)
        if ref and name:
            results.append((ref, name))
    return results or None

# ------------------------- 3) GTFS-RT Fetch & Parser -------------------------
def fetch_gtfs_rt(api_key: str) -> gtfs_realtime_pb2.FeedMessage:
    """Lädt GTFS-Realtime-Feed herunter und gibt FeedMessage zurück."""
    url = "https://api.opentransportdata.swiss/la/gtfs-rt"
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": "streamlit-delay-bot/1.0", "Accept": "application/octet-stream"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        st.error(f"❌ GTFS-RT Abruf fehlgeschlagen: {resp.status_code}")
        st.stop()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed

def parse_delays_for_stop(feed: gtfs_realtime_pb2.FeedMessage, stop_id: str):
    """Extrahiert StopTimeUpdates für eine stop_id und liefert sortierte Liste von Diktaten."""
    delays = []
    for entity in feed.entity:
        if not entity.HasField('trip_update'):
            continue
        tu = entity.trip_update
        for stu in tu.stop_time_update:
            if stu.stop_id != stop_id:
                continue
            event = stu.arrival if stu.HasField('arrival') and stu.arrival.time else stu.departure if stu.HasField('departure') and stu.departure.time else None
            if not event:
                continue
            delay_s = event.delay or 0
            pred_dt = datetime.fromtimestamp(event.time, timezone.utc)
            sched_dt = pred_dt - timedelta(seconds=delay_s)
            delays.append({
                'route_id': tu.trip.route_id,
                'trip_id': tu.trip.trip_id,
                'scheduled': sched_dt,
                'predicted': pred_dt,
                'delay_min': delay_s // 60
            })
    return sorted(delays, key=lambda x: x['scheduled'])

# ------------------------- 4) Session-State & UI -------------------------
if 'stage' not in st.session_state:
    st.session_state.stage = 'chat'
    st.session_state.messages = [
        {'role': 'system', 'content': 'Du bist ein freundlicher Chatbot für ÖV-Verspätungen.'},
        {'role': 'assistant', 'content': 'Welche Haltestelle möchtest du abfragen?'}
    ]
    st.session_state.stop_id = None
    st.session_state.stop_name = None

st.set_page_config(page_title='🚦 ÖV-Verspätungs-Chatbot', layout='wide')
st.title('🚦 ÖV-Verspätungs-Chatbot')
st.write('Frag mich nach aktuellen Verspätungen an deiner Haltestelle.')
st.write('---')
# Chat-Historie
for msg in st.session_state.messages:
    st.chat_message(msg['role']).write(msg['content'])

# Stage: chat -> lookup
if st.session_state.stage == 'chat':
    user_input = st.chat_input('🧳 Haltestelle (Name oder ID) eingeben:')
    if user_input:
        st.session_state.messages.append({'role': 'user', 'content': user_input})
        st.session_state.stop_name = user_input
        st.session_state.messages.append({'role': 'assistant', 'content': 'Suche Haltestelle...'})
        st.session_state.stage = 'lookup'
        st.rerun()

# Stage: lookup -> select stop
if st.session_state.stage == 'lookup':
    candidates = stop_place_lookup(st.session_state.stop_name)
    if not candidates:
        st.error('Keine Haltestellen gefunden. Bitte erneut versuchen.')
        st.session_state.stage = 'chat'
        st.stop()
    st.markdown('**Bitte wähle die genaue Haltestelle aus:**')
    stop_map = {name: ref for ref, name in candidates}
    choice = st.selectbox('Haltestelle auswählen', list(stop_map.keys()))
    if st.button('Bestätigen'):
        st.session_state.stop_id = stop_map[choice]
        st.session_state.messages.append({'role': 'assistant', 'content': f'Du hast {choice} ausgewählt.'})
        st.session_state.stage = 'delay'
        st.rerun()

# Stage: delay -> fetch & display
if st.session_state.stage == 'delay':
    st.session_state.messages.append({'role': 'assistant', 'content': 'Hole Verspätungsdaten...'})
    st.chat_message('assistant').write('Hole Verspätungsdaten...')
    feed = fetch_gtfs_rt(GTFS_RT_API_KEY)
    delays = parse_delays_for_stop(feed, st.session_state.stop_id)
    if not delays:
        st.info('Keine Verspätungsdaten für diese Haltestelle gefunden.')
    else:
        st.markdown(f"### Verspätungen an {st.session_state.stop_name}")
        for d in delays[:10]:
            sched = d['scheduled'].astimezone().strftime('%H:%M')
            pred = d['predicted'].astimezone().strftime('%H:%M')
            diff = f"(+{d['delay_min']} min)" if d['delay_min'] else '(planmäßig)'
            st.write(f"• Linie **{d['route_id']}** ({d['trip_id']}): {sched} → {pred} {diff}")
    st.session_state.stage = 'done'

# Stage: done -> Restart
if st.session_state.stage == 'done':
    if st.button('Neue Abfrage starten'):
        st.session_state.stage = 'chat'
        st.session_state.messages = [
            {'role': 'system', 'content': 'Du bist ein freundlicher Chatbot für ÖV-Verspätungen.'},
            {'role': 'assistant', 'content': 'Welche Haltestelle möchtest du abfragen?'}
        ]
        st.session_state.stop_id = None
        st.session_state.stop_name = None
        st.experimental_rerun()
