# streamlit_chatbot_streamlit_ui_v2.py

import os
import re
import json
import requests
import xml.etree.ElementTree as ET
import dateparser
from datetime import datetime, timedelta, timezone

import streamlit as st
import openai

# ------------------------- 1) API-Keys aus secrets laden -------------------------
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
OJP_API_KEY    = st.secrets.get("OJP_API_KEY")

if not OPENAI_API_KEY or not OJP_API_KEY:
    st.error("❌ Bitte lege in .streamlit/secrets.toml OPENAI_API_KEY und OJP_API_KEY an.")
    st.stop()

openai.api_key = OPENAI_API_KEY

# ------------------------- 2) Datumerkennung/Funktionen -------------------------
tage = {
    'montag': 0, 'dienstag': 1, 'mittwoch': 2,
    'donnerstag': 3, 'freitag': 4, 'samstag': 5, 'sonntag': 6
}

def replace_date_keywords(text: str) -> str:
    """
    Ersetzt deutsche relative Datumsausdrücke (heute, gestern, morgen, übermorgen, nächsten <Wochentag>) 
    durch ein ISO-Datum (YYYY-MM-DD).  
    """
    pattern = re.compile(r'\b(heute|gestern|morgen|übermorgen|nächsten?\s+\w+)\b', re.IGNORECASE)

    def repl(match):
        frag = match.group(0)
        frag_norm = re.sub(r'(?i)\bnächsten\b', 'nächster', frag)

        # 1) Manuelle "nächster <Tag>"-Berechnung
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

        # 2) Sonst dateparser ("heute", "morgen", "übermorgen")
        dt = dateparser.parse(
            frag_norm,
            settings={'PREFER_DATES_FROM': 'future'},
            languages=['de']
        )
        if dt:
            return dt.strftime('%Y-%m-%d')

        # 3) Fallback
        return frag

    return pattern.sub(repl, text)

def get_text(elem, path, ns):
    """
    Sucht ein Element mit Pfad `path` im Element `elem` unter Verwendung der Namensräume `ns`.
    Gibt den Textinhalt zurück oder einen leeren String, wenn nichts gefunden wird.
    """
    sub = elem.find(path, ns)
    return sub.text if sub is not None and sub.text is not None else ''

def stop_place_lookup(ort_name: str):
    """
    Sucht eine Haltestelle via OJP. Gibt Liste von (stop_id, stop_name) oder None zurück.
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
</OJP>"""

    url = "https://api.opentransportdata.swiss/ojp2020"
    headers = {
        "Content-Type": "application/xml",
        "Authorization": f"Bearer {OJP_API_KEY}"
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
    """
    Parst die OJP-TripResponse, sortiert alle Trips nach Dauer 
    und gibt (besteVerbindung_steps, [ali1_steps, ali2_steps, ...]) zurück.
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

# ------------------------- 6) Session-State initialisieren -------------------------
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "system",
            "content": (
                "Du bist ein freundlicher und hilfsbereiter Mobilitäts-Chatbot. "
                "Du planst für den Nutzer eine Reise mit dem öffentlichen Verkehr in der Schweiz. "
                "Dein Ziel ist es, die Informationen zur Reiseplanung vom Nutzer zu sammeln: Startort, Zielort, Datum, Uhrzeit "
                "und ob es sich um eine Abfahrts- oder Ankunftszeit handelt. "
                "Führe einen natürlichen und lockeren Dialog per Du. Stelle gezielte Rückfragen, wenn etwas fehlt. "
                "Sobald du alle Infos hast, gib **ausschließlich** ein JSON-Objekt aus:\n"
                "{\"start\":\"…\", \"ziel\":\"…\", \"datum\":\"YYYY-MM-DD\", \"uhrzeit\":\"HH:MM:SS\", \"typ\":\"abfahrt\"}\n"
               "Direkt nachdem die Verbindungen angezeigt wurden, frage den Nutzer, ob alles klar ist, ob er die Reise durchführt "
                "und welche Verbindung er wählen wird. "
                "Beende das Gespräch und wünsche ihm eine gute Reise. Sei kreativ und überraschend."
            )
        },
        {
            "role": "assistant",
            "content": "Wohin möchtest du reisen und wann?"
        }
    ]
    st.session_state.reiseinfos = None        # Wird gesetzt, sobald JSON erkannt wurde
    st.session_state.steps_best = None         # Schritte der besten Verbindung
    st.session_state.steps_alts = []           # Liste mit Schritte-Listen aller Alternativen
    st.session_state.stage = "chat"            # "chat" bis JSON erkannt, dann "stop_lookup", dann "trip", dann "done"
    st.session_state.user_input = ""           # Letzte Benutzereingabe

# ------------------------- 7) UI oben: Titel & Erklärung -------------------------
st.set_page_config(page_title="🚆 ÖV-Chatbot Schweiz", layout="wide")
st.title("🚆 ÖV-Chatbot Schweiz")
st.write("Stelle z. B. eine Frage wie „Ich möchte von Zürich nach Bern morgen um 15 Uhr ankommen.“")
st.write("---")

# ===============================================================
#  >>> CHAT-HISTORIE ANZEIGEN <<<
# ===============================================================
for msg in st.session_state.messages:
    if msg["role"] == "system":
        continue  # Systemnachricht nicht anzeigen
    if msg["role"] == "assistant":
        st.chat_message("assistant").write(msg["content"])
    else:
        st.chat_message("user").write(msg["content"])

# ===============================================================
#  >>> EINGABE BEARBEITEN: NUR IN STAGES "chat" ODER "done" <<<
# ===============================================================
if st.session_state.stage in ["chat", "done"]:
    user_input = st.chat_input("🧳 Deine Nachricht:")
    if user_input:
        st.session_state.user_input = user_input
        # 1) Datumsausdrücke ersetzen
        cleaned = replace_date_keywords(user_input)
        if cleaned != user_input:
            st.info(f"ℹ️ Datums­auss­druck ersetzt:\n  {user_input!r}\n→ {cleaned!r}")

        # 2) Nachricht in History speichern
        st.session_state.messages.append({"role": "user", "content": cleaned})

        # 3) GPT-4 aufrufen (nur in Stage "chat"; in Stage "done" antwortet Bot direkt)
        if st.session_state.stage == "chat":
            response = openai.chat.completions.create(
                model="gpt-4o",
                messages=st.session_state.messages
            )
            reply = response.choices[0].message.content.strip()

            # 4) Prüfen, ob Bot ein JSON zurückgegeben hat
            match = re.search(r'\{.*\}', reply, re.DOTALL)
            if match:
                # Wenn JSON gefunden wird, parsen wir es und speichern in session_state,
                # aber KEINEN JSON-String an den User ausgeben:
                try:
                    parsed = json.loads(match.group(0))
                    st.session_state.reiseinfos = parsed
                    st.session_state.stage = "stop_lookup"
                    # Statt den rohen JSON-Text anzuzeigen, bestätigen wir kurz:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "Super, ich habe alle notwendigen Informationen erhalten. Ich suche nun deine Verbindungen."
                    })
                    st.rerun()
                except json.JSONDecodeError:
                    # Falls das gefundene Fragment kein gültiges JSON ist, ignorieren wir es
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    st.rerun()
            else:
                # Kein JSON gefunden: normale Chat-Antwort anzeigen
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.rerun()

        else:
            # Stage "done": Bot antwortet abschließend
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Danke für deine Rückmeldung! Ich wünsche dir eine gute Reise und bis zum nächsten Mal!"
            })
            st.rerun()

# ===============================================================
#  >>> STAGE: stop_lookup <<<
# ===============================================================
if st.session_state.stage == "stop_lookup":
    reiseinfos = st.session_state.reiseinfos

    # Datum normalisieren (falls ohne Jahr eingegeben)
    heute = datetime.now()
    user_hat_jahr = bool(re.search(r'\b\d{4}\b', st.session_state.user_input))
    try:
        dt = datetime.strptime(reiseinfos["datum"], "%Y-%m-%d")
        if dt.year != heute.year and not user_hat_jahr:
            dt = dt.replace(year=heute.year)
        reiseinfos["datum"] = dt.strftime("%Y-%m-%d")
    except ValueError:
        reiseinfos["datum"] = heute.strftime("%Y-%m-%d")

    # Uhrzeit normalisieren
    uhr_raw = reiseinfos.get("uhrzeit", "08:00:00")
    m = re.match(r"^(\d{1,2}):?(\d{2})?:?(\d{2})?$", uhr_raw)
    if m:
        std  = m.group(1).zfill(2)
        minu = m.group(2) or "00"
        sek  = m.group(3) or "00"
        reiseinfos["uhrzeit"] = f"{std}:{minu}:{sek}"
    else:
        reiseinfos["uhrzeit"] = "08:00:00"

    # Stop-Place-Lookup für Start und Ziel
    start_candidates = stop_place_lookup(reiseinfos["start"])
    ziel_candidates  = stop_place_lookup(reiseinfos["ziel"])

    if not start_candidates or not ziel_candidates:
        st.error("❌ Haltestelle(n) konnten nicht gefunden werden. Bitte neu starten und Eingabe prüfen.")
        st.stop()

    st.markdown("**Wähle die exakte Haltestelle aus den Ergebnissen unten aus.**")
    col1, col2 = st.columns(2)
    with col1:
        st.write("🔎 Start-Haltestelle:")
        start_map = {name: ref for ref, name in start_candidates}
        chosen_start_name = st.selectbox("Start-Haltestelle auswählen", options=list(start_map.keys()))
    with col2:
        st.write("🔎 Ziel-Haltestelle:")
        ziel_map = {name: ref for ref, name in ziel_candidates}
        chosen_ziel_name = st.selectbox("Ziel-Haltestelle auswählen", options=list(ziel_map.keys()))

    if st.button("Weiter zu Verbindungen"):
        st.session_state.reiseinfos["start_id"]   = start_map[chosen_start_name]
        st.session_state.reiseinfos["start_name"] = chosen_start_name
        st.session_state.reiseinfos["ziel_id"]    = ziel_map[chosen_ziel_name]
        st.session_state.reiseinfos["ziel_name"]  = chosen_ziel_name
        st.session_state.stage = "trip"
        st.rerun()

# … dein Code bis einschließlich „trip“-Block unverändert …


# ===============================================================
#  >>> STAGE: trip <<<
# ===============================================================
if st.session_state.stage == "trip":
    info = st.session_state.reiseinfos

    datum      = info["datum"]
    uhrzeit    = info["uhrzeit"]
    start_id   = info["start_id"]
    start_name = info["start_name"]
    ziel_id    = info["ziel_id"]
    ziel_name  = info["ziel_name"]

    typ = info.get("typ", "abfahrt")
    if typ not in ("abfahrt", "ankunft"):
        typ = "abfahrt"

    now_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    if typ == "abfahrt":
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
          <ojp:DepArrTime>{datum}T{uhrzeit}Z</ojp:DepArrTime>
        </ojp:Origin>
        <ojp:Destination>
          <ojp:PlaceRef>
            <ojp:StopPlaceRef>{ziel_id}</ojp:StopPlaceRef>
            <ojp:LocationName>
              <ojp:Text>{ziel_name}</ojp:Text>
            </ojp:LocationName>
          </ojp:PlaceRef>
          <!-- kein DepArrTime beim Reiseziel -->
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
    else:
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
          <!-- kein DepArrTime beim Origin -->
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

    headers = {
        "Content-Type": "application/xml",
        "Authorization": f"Bearer {OJP_API_KEY}"
    }
    response = requests.post(
        "https://api.opentransportdata.swiss/ojp2020",
        data=xml_body.encode("utf-8"),
        headers=headers
    )

    if response.status_code != 200:
        st.error(f"❌ Fehler bei der Trip-Anfrage: {response.status_code}")
        st.stop()

    best, alts = parse_trips(response.text)
    st.session_state.steps_best = best
    st.session_state.steps_alts = alts

    # ——————————————————————————————————————————————————————————————
    # Ausgabe der Verbindungen + Frage (einmalig):
    # ——————————————————————————————————————————————————————————————

    st.session_state.messages.append({"role": "assistant", "content": "Hier sind die Verbindungen:"})
    st.chat_message("assistant").write("Hier sind die Verbindungen:")

    st.markdown("### 🚀 Schnellste Verbindung")
    for i, s in enumerate(best, start=1):
        if s['type'] == 'ride':
            st.write(
                f"{i}. 🚆 **{s['line']}**: {s['dep_sta']} ({s['dep_time']} Uhr, Gleis {s['dep_quay']}) → "
                f"{s['arr_sta']} ({s['arr_time']} Uhr, Gleis {s['arr_quay']})"
            )
        else:
            st.write(
                f"{i}. 🚶 **{s['mode'].capitalize()}** von {s['from']} nach {s['to']} "
                f"(Dauer {s['duration']})"
            )

    if alts:
        st.markdown("### 🔄 Alternative Verbindungen")
        for idx, alt in enumerate(alts, start=1):
            st.markdown(f"**Alternative {idx}:**")
            for j, s in enumerate(alt, start=1):
                if s['type'] == 'ride':
                    st.write(
                        f"{j}. 🚆 **{s['line']}**: {s['dep_sta']} ({s['dep_time']} Uhr, Gleis {s['dep_quay']}) → "
                        f"{s['arr_sta']} ({s['arr_time']} Uhr, Gleis {s['arr_quay']})"
                    )
                else:
                    st.write(
                        f"{j}. 🚶 **{s['mode'].capitalize()}** von {s['from']} nach {s['to']} "
                        f"(Dauer {s['duration']})"
                    )
    else:
        st.info("Keine Alternativen verfügbar.")

    st.session_state.messages.append({
        "role": "assistant",
        "content": "Alles klar? Führst du die Reise wirklich durch und welche Verbindung wirst du wählen?"
    })
    st.chat_message("assistant").write("Alles klar? Führst du die Reise wirklich durch und welche Verbindung wirst du wählen?")

    user_choice = st.chat_input("🧳 Deine Antwort:")
    if user_choice:
        st.session_state.messages.append({"role": "user", "content": user_choice})
        # Wenn der Nutzer hier antwortet, merken wir uns die Wahl und schalten erst danach auf "done"
        st.session_state.stage = "done"
        # Die Abschlussnachricht hängt der Bot direkt an:
        st.session_state.messages.append({
            "role": "assistant",
            "content": "Alles klar, danke für deine Rückmeldung! Ich wünsche dir eine gute Reise 🚆🙂"
        })
        # Jetzt rerunen, damit wir ins "done"-Branch springen:
        st.rerun()


# ===============================================================
#  >>> STAGE: done <<<
# ===============================================================
if st.session_state.stage == "done":
    # 1) Zuerst zeigen wir hier die Verbindungen erneut, damit sie auch nach dem Rerun sichtbar bleiben:
    best = st.session_state.steps_best or []
    alts = st.session_state.steps_alts or []

    st.markdown("### 🚀 Schnellste Verbindung")
    for i, s in enumerate(best, start=1):
        if s['type'] == 'ride':
            st.write(
                f"{i}. 🚆 **{s['line']}**: {s['dep_sta']} ({s['dep_time']} Uhr, Gleis {s['dep_quay']}) → "
                f"{s['arr_sta']} ({s['arr_time']} Uhr, Gleis {s['arr_quay']})"
            )
        else:
            st.write(
                f"{i}. 🚶 **{s['mode'].capitalize()}** von {s['from']} nach {s['to']} "
                f"(Dauer {s['duration']})"
            )

    if alts:
        st.markdown("### 🔄 Alternative Verbindungen")
        for idx, alt in enumerate(alts, start=1):
            st.markdown(f"**Alternative {idx}:**")
            for j, s in enumerate(alt, start=1):
                if s['type'] == 'ride':
                    st.write(
                        f"{j}. 🚆 **{s['line']}**: {s['dep_sta']} ({s['dep_time']} Uhr, Gleis {s['dep_quay']}) → "
                        f"{s['arr_sta']} ({s['arr_time']} Uhr, Gleis {s['arr_quay']})"
                    )
                else:
                    st.write(
                        f"{j}. 🚶 **{s['mode'].capitalize()}** von {s['from']} nach {s['to']} "
                        f"(Dauer {s['duration']})"
                    )
    else:
        st.info("Keine Alternativen verfügbar.")



