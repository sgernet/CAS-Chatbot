# streamlit_chatbot.py

import re
import json
import requests
import xml.etree.ElementTree as ET
import dateparser
from datetime import datetime, timedelta, timezone
import streamlit as st
import openai

# ----------------------------------------
# 1) API-Keys aus Streamlit-Secrets lesen
# ----------------------------------------
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
OJP_API_KEY    = st.secrets.get("OJP_API_KEY")

if not OPENAI_API_KEY or not OJP_API_KEY:
    st.error("❌ Bitte lege in .streamlit/secrets.toml sowohl OPENAI_API_KEY als auch OJP_API_KEY an.")
    st.stop()

openai.api_key = OPENAI_API_KEY

# ----------------------------------------
# 2) Datumserkennung: Deutsche Schlüsselwörter ersetzen
# ----------------------------------------
tage = {
    'montag': 0, 'dienstag': 1, 'mittwoch': 2,
    'donnerstag': 3, 'freitag': 4, 'samstag': 5, 'sonntag': 6
}

def replace_date_keywords(text: str) -> str:
    """
    Ersetzt in `text` deutsche relative Datumsausdrücke wie:
    - "heute", "gestern", "morgen", "übermorgen"
    - "nächsten <Wochentag>" manuell
    - Sonstige über dateparser
    """
    pattern = re.compile(r'\b(heute|gestern|morgen|übermorgen|nächsten?\s+\w+)\b', re.IGNORECASE)

    def repl(match):
        frag = match.group(0)
        frag_norm = re.sub(r'(?i)\bnächsten\b', 'nächster', frag)

        # 1) Manuelle Wochentags-Berechnung, falls "nächster <Tag>"
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

        # 2) Dateparser für "heute", "morgen", "übermorgen" usw.
        dt = dateparser.parse(
            frag_norm,
            settings={'PREFER_DATES_FROM': 'future'},
            languages=['de']
        )
        if dt:
            return dt.strftime('%Y-%m-%d')

        # 3) Fallback: Original-Fragment zurückgeben
        return frag

    return pattern.sub(repl, text)

# ----------------------------------------
# 3) Funktion: Haltestellen-Lookup via OJP
# ----------------------------------------
def stop_place_lookup(ort_name: str):
    """
    Sendet eine OJP-Locator-Request, um StopPlaceRef und StopPlaceName zurückzugeben.
    Liefert (None, None), falls kein Treffer oder HTTP-Fehler.
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
      <RequestorRef>StreamlitApp</RequestorRef>
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
        "Authorization": f"Bearer {OJP_API_KEY}"
    }
    resp = requests.post(url, data=xml_body.encode("utf-8"), headers=headers)
    if resp.status_code != 200:
        return None, None

    ns = {'ojp': 'http://www.vdv.de/ojp', 's': 'http://www.siri.org.uk/siri'}
    tree = ET.fromstring(resp.text)
    results = []
    for sp in tree.findall('.//ojp:StopPlace', ns):
        ref  = sp.findtext('.//ojp:StopPlaceRef', namespaces=ns)
        name = sp.findtext('.//ojp:StopPlaceName/ojp:Text', namespaces=ns)
        if ref and name:
            results.append((ref, name))

    if not results:
        return None, None

    # Wir nehmen hier einfach den ersten Treffer
    return results[0]

# ----------------------------------------
# 4) Funktion: Trip-Antwort parsen & sortieren
# ----------------------------------------
def parse_trips(xml_text: str):
    """
    Parst die OJP-TripResponse, sortiert alle Trips nach Dauer
    und gibt ein Tuple zurück:
      (steps_best_trip, [steps_alt1, steps_alt2, ...])
    """
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

    # Sortiere alle Trips nach Dauer (aufsteigend)
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
                    'arr_sta':  alight.find('.//ojp:StopPointName/ojp:Text', ns).text,
                    'arr_time': alight.find('.//ojp:TimetabledTime', ns).text.split('T')[-1].rstrip('Z')
                })
            else:
                trf = leg.find('ojp:TransferLeg', ns)
                if trf is not None:
                    steps.append({
                        'type':     'walk',
                        'mode':     trf.find('.//ojp:TransferMode', ns).text,
                        'from':     trf.find('.//ojp:LegStart/ojp:LocationName/ojp:Text', ns).text,
                        'to':       trf.find('.//ojp:LegEnd/ojp:LocationName/ojp:Text', ns).text,
                        'duration': trf.find('.//ojp:Duration', ns).text.lstrip('PT').lower()
                    })
        return steps

    best_steps = build_steps(best_trip)
    alt_steps_list = [build_steps(t) for t in alts]
    return best_steps, alt_steps_list

# ----------------------------------------
# 5) Session State initialisieren
# ----------------------------------------
if "messages" not in st.session_state:
    # System-Prompt + erste Bot-Nachricht
    st.session_state.messages = [
        {
            "role": "system",
            "content": (
                "Du bist ein freundlicher Mobilitäts‐Chatbot für die Schweiz. "
                "Sammle vom Nutzer Start, Ziel, Datum und Uhrzeit. "
                "Sobald du alle vier Infos hast, antworte **nur noch** mit einem JSON-Objekt im Format:\n"
                "{\"start\":\"<ORT>\",\"ziel\":\"<ORT>\",\"datum\":\"YYYY-MM-DD\",\"uhrzeit\":\"HH:MM:SS\"}"
            )
        },
        {
            "role": "assistant",
            "content": "Wohin möchtest du reisen und wann?"
        }
    ]
    st.session_state.reiseinfos = None          # Wird gesetzt, wenn Bot das JSON zurückliefert
    st.session_state.trip_displayed = False      # Wird True, sobald OJP-Antwort angezeigt wurde
    st.session_state.final_phase = False         # Wird True, sobald die Abschlussfrage gestellt wurde

# ----------------------------------------
# 6) UI: Seitentitel & Kurzerklärung
# ----------------------------------------
st.set_page_config(page_title="🚆 ÖV-Chatbot Schweiz", layout="wide")
st.title("🚆 ÖV-Chatbot Schweiz")
st.write("Stelle z. B. eine Frage wie „Ich möchte von Zürich nach Bern morgen um 15 Uhr fahren.“")
st.write("---")

# ========================================
# >>> LOGIK: ZUERST EINGABEN UND UPDATES <<<
# ========================================

# --- Block A: Chat‐Eingabe, solange noch keine OJP-Daten abgerufen wurden ---
if not st.session_state.trip_displayed:
    with st.form(key="chat_form", clear_on_submit=True):
        user_text = st.text_input("Deine Nachricht:", placeholder="Tippe hier…")
        send_button = st.form_submit_button("Senden")

    if send_button and user_text:
        # 1) Datumsausdrücke ersetzen
        cleaned = replace_date_keywords(user_text)
        if cleaned != user_text:
            st.info(f"ℹ️ „{user_text}“ → „{cleaned}“")

        # 2) User-Nachricht speichern
        st.session_state.messages.append({"role": "user", "content": cleaned})

        # 3) Anfrage an OpenAI (neue API-Schnittstelle)
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=st.session_state.messages
        )
        reply = response.choices[0].message.content.strip()

        # 4) Bot-Antwort speichern
        st.session_state.messages.append({"role": "assistant", "content": reply})

        # 5) Prüfen, ob Bot bereits ein JSON mit Reiseinfos geliefert hat
        match = re.search(r'\{.*\}', reply, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                st.session_state.reiseinfos = parsed
                # (Optional) Zum Debuggen: st.write("✅ Reiseinfos erkannt:", parsed)
            except json.JSONDecodeError:
                st.warning("⚠️ Bot hat JSON-Struktur geliefert, konnte sie aber nicht parsen.")

# --- Block B: OJP-Trip abrufen, sobald JSON vorliegt und noch nicht angezeigt wurde ---
if st.session_state.reiseinfos and not st.session_state.trip_displayed:
    reiseinfos = st.session_state.reiseinfos

    # 6) Datum normalisieren (falls ohne Jahr eingegeben wurde)
    heute = datetime.now()
    # Merke: user_text ist in diesem Scope verfügbar, weil Block A zwingend vorher durchlaufen sein muss, um reiseinfos zu setzen.
    user_hat_jahr = bool(re.search(r'\b\d{4}\b', user_text))
    try:
        dt = datetime.strptime(reiseinfos["datum"], "%Y-%m-%d")
        if dt.year != heute.year and not user_hat_jahr:
            dt = dt.replace(year=heute.year)
        datum_iso = dt.strftime("%Y-%m-%d")
    except Exception:
        datum_iso = heute.strftime("%Y-%m-%d")

    # 7) Uhrzeit normalisieren
    uhr_raw = reiseinfos.get("uhrzeit", "08:00:00")
    m = re.match(r"^(\d{1,2}):?(\d{2})?:?(\d{2})?$", uhr_raw)
    if m:
        std  = m.group(1).zfill(2)
        minu = m.group(2) or "00"
        sek  = m.group(3) or "00"
        uhrzeit_iso = f"{std}:{minu}:{sek}"
    else:
        uhrzeit_iso = "08:00:00"

    # 8) Stop-Lookup für Start und Ziel
    start_id, start_name = stop_place_lookup(reiseinfos["start"])
    ziel_id,  ziel_name  = stop_place_lookup(reiseinfos["ziel"])
    if not start_id or not ziel_id:
        st.error("❌ Haltestelle(n) konnten nicht gefunden werden. Bitte Chat neu starten und Eingabe prüfen.")
        st.stop()

    # 9) OJP-TripRequest-XML bauen
    dep_time = f"{datum_iso}T{uhrzeit_iso}Z"
    now_utc  = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    xml_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<OJP xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xmlns:xsd="http://www.w3.org/2001/XMLSchema"
     xmlns="http://www.siri.org.uk/siri"
     xmlns:ojp="http://www.vdv.de/ojp"
     version="1.0"
     xsi:schemaLocation="http://www.siri.org.uk/siri ../ojp-xsd-v1.0/OJP.xsd">
  <OJPRequest>
    <ServiceRequest>
      <RequestTimestamp>{now_utc}</RequestTimestamp>
      <RequestorRef>StreamlitApp</RequestorRef>
      <ojp:OJPTripRequest>
        <RequestTimestamp>{now_utc}</RequestTimestamp>
        <ojp:Origin>
          <ojp:PlaceRef>
            <ojp:StopPlaceRef>{start_id}</ojp:StopPlaceRef>
            <ojp:LocationName>
              <ojp:Text>{start_name}</ojp:Text>
            </ojp:LocationName>
          </ojp:PlaceRef>
          <ojp:DepArrTime>{dep_time}</ojp:DepArrTime>
        </ojp:Origin>
        <ojp:Destination>
          <ojp:PlaceRef>
            <ojp:StopPlaceRef>{ziel_id}</ojp:StopPlaceRef>
            <ojp:LocationName>
              <ojp:Text>{ziel_name}</ojp:Text>
            </ojp:LocationName>
          </ojp:PlaceRef>
          <ojp:DepArrTime>{dep_time}</ojp:DepArrTime>
        </ojp:Destination>
        <ojp:Params>
          <ojp:NumberOfResults>5</ojp:NumberOfResults>
          <ojp:OptimisationMethod>fastest</ojp:OptimisationMethod>
        </ojp:Params>
      </ojp:OJPTripRequest>
    </ServiceRequest>
  </OJPRequest>
</OJP>"""

    headers = {
        "Content-Type": "application/xml",
        "Authorization": f"Bearer {OJP_API_KEY}"
    }
    resp = requests.post("https://api.opentransportdata.swiss/ojp2020",
                         data=xml_body.encode("utf-8"), headers=headers)
    if resp.status_code != 200:
        st.error(f"❌ OJP-Anfrage fehlgeschlagen (Status {resp.status_code}).")
        st.stop()

    # 10) Antwort parsen und vorbereiten für Anzeige
    best, alts = parse_trips(resp.text)

    # 11) Setze Flag, damit wir nicht nochmal in Block B landen
    st.session_state.trip_displayed = True

    # 12) Füge die Abschlussfrage ANSCHLIESSEND an die Chat-Historie
    st.session_state.messages.append({
        "role": "assistant",
        "content": "Alles klar? Führst du die Reise wirklich durch und welche Verbindung wirst du wählen?"
    })
    st.session_state.final_phase = True

    # 13) Speichere die Trip-Daten in session_state, damit wir sie beim Rendern unten anzeigen können
    st.session_state.best_trip = best
    st.session_state.alt_trips = alts

# ========================================
# >>> NACH ALLEN UPDATES: CHAT-HISTORIE & ERGEBNISSE ANZEIGEN <<<
# ========================================

# ─────────────────────────────────────────────────────────
# 14) Chat-Historie ausgeben (mit neuen Farb-Styles)
# ─────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    if msg["role"] == "assistant":
        # Bot-Bubble: dunkler Anthrazit-Hintergrund, weißer Text
        st.markdown(
            f"""
            <div style="
                background-color: #2F4F4F;
                color: #FFFFFF;
                padding: 12px 16px;
                border-radius: 12px;
                margin: 8px 0px;
                max-width: 80%;
                line-height: 1.4;
            ">
                <strong>🤖 Bot:</strong> {msg['content']}
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        # User-Bubble: Petrol-Grau-Hintergrund, weißer Text, rechtsbündig
        st.markdown(
            f"""
            <div style="
                background-color: #3E606F;
                color: #FFFFFF;
                padding: 12px 16px;
                border-radius: 12px;
                margin: 8px 0px;
                max-width: 80%;
                margin-left: auto;
                line-height: 1.4;
            ">
                <strong>🧳 Du:</strong> {msg['content']}
            </div>
            """,
            unsafe_allow_html=True
        )

st.write("---")

# ─────────────────────────────────────────────────────────
# 15) Verbindungen anzeigen (farblich neutral lassen)
# ─────────────────────────────────────────────────────────
if st.session_state.get("best_trip"):
    st.header("🚀 Schnellste Verbindung")
    for i, s in enumerate(st.session_state.best_trip, start=1):
        if s["type"] == "ride":
            st.write(
                f"{i}. 🚆 Linie {s['line']}: "
                f"{s['dep_sta']} ({s['dep_time']} Uhr) → {s['arr_sta']} ({s['arr_time']} Uhr)"
            )
        else:
            st.write(
                f"{i}. 🚶 {s['mode'].capitalize()} von "
                f"{s['from']} nach {s['to']} (Dauer {s['duration']})"
            )

    if st.session_state.alt_trips:
        st.subheader("🔄 Alternative Verbindungen")
        for idx, alt in enumerate(st.session_state.alt_trips, start=1):
            st.markdown(f"**Alternative {idx}:**")
            for j, s in enumerate(alt, start=1):
                if s["type"] == "ride":
                    st.write(
                        f"{j}. 🚆 Linie {s['line']}: "
                        f"{s['dep_sta']} ({s['dep_time']} Uhr) → {s['arr_sta']} ({s['arr_time']} Uhr)"
                    )
                else:
                    st.write(
                        f"{j}. 🚶 {s['mode'].capitalize()} von "
                        f"{s['from']} nach {s['to']} (Dauer {s['duration']})"
                    )
    else:
        st.info("Keine Alternativen verfügbar.")

# ─────────────────────────────────────────────────────────
# 16) Block C: Antwort auf Abschlussfrage (farblich gleich wie User-Bubble)
# ─────────────────────────────────────────────────────────
if st.session_state.trip_displayed and st.session_state.final_phase:
    last_msg = st.session_state.messages[-1]
    if last_msg["role"] == "assistant":
        with st.form(key="final_form", clear_on_submit=True):
            user_final = st.text_input("🧳 Deine Antwort auf die Abschlussfrage:")
            final_send = st.form_submit_button("Senden")
        if final_send and user_final:
            st.session_state.messages.append({"role": "user", "content": user_final})
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Danke für deine Rückmeldung! Ich wünsche dir eine gute Reise und bis zum nächsten Mal!"
            })
            # Kein weiteres Flag nötig – der Dialog ist damit beendet.
