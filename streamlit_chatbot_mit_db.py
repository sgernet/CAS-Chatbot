# Datei: streamlit_chatbot.py
import streamlit as st
import openai
import re
import json
from chatbot_util_mit_db import replace_date_keywords, stop_place_lookup, parse_trips
from datetime import datetime

# Setze API-Key (wird in app.py bereits aus secrets geladen)
openai.api_key = st.secrets.get("OPENAI_API_KEY")

def zeige_streamlit_chatbot():
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "system", "content": (
                "Du bist ein freundlicher und hilfsbereiter Mobilitäts-Chatbot. "
                "Du planst für den Nutzer eine Reise mit dem öffentlichen Verkehr in der Schweiz. "
                "Dein Ziel ist es, die Informationen zur Reiseplanung vom Nutzer zu sammeln: Startort, Zielort, Datum, Uhrzeit "
                "und ob es sich um eine Abfahrts- oder Ankunftszeit handelt. "
                "Führe einen natürlichen und lockeren Dialog per Du. Stelle gezielte Rückfragen, wenn etwas fehlt. "
                "Sobald du alle Infos hast, gib **ausschließlich** ein JSON-Objekt aus:\n"
                "{\"start\":\"…\", \"ziel\":\"…\", \"datum\":\"YYYY-MM-DD\", \"uhrzeit\":\"HH:MM:SS\", \"typ\":\"abfahrt\"}\n"
                "Direkt nachdem die Verbindungen angezeigt wurden, frage den Nutzer, ob alles klar ist, ob er die Reise durchführt "
                "und welche Verbindung er wählen wird. Führe den Dialog so lange fort, bis "
                "der Nutzer keine Fragen mehr hat, und dir die Reise bestätigt hat. "
                "Beende das Gespräch und wünsche ihm eine gute Reise. Sei kreativ und überraschend."
            )},
            {"role": "assistant", "content": "Wohin möchtest du reisen und wann?"}
        ]
        st.session_state.reiseinfos = None
        st.session_state.steps_best = None
        st.session_state.steps_alts = []
        st.session_state.stage = "chat"
        st.session_state.user_input = ""

    for msg in st.session_state.messages:
        if msg["role"] == "system":
            continue
        st.chat_message(msg["role"]).write(msg["content"])

    if st.session_state.stage in ["chat", "done"]:
        user_input = st.chat_input("🧳 Deine Nachricht:")
        if user_input:
            st.session_state.user_input = user_input
            cleaned = replace_date_keywords(user_input)
            if cleaned != user_input:
                st.info(f"ℹ️ Datumsausdruck ersetzt:\n  {user_input!r}\n→ {cleaned!r}")
            st.session_state.messages.append({"role": "user", "content": cleaned})

            if st.session_state.stage == "chat":
                response = openai.chat.completions.create(
                    model="gpt-4",
                    messages=st.session_state.messages
                )
                reply = response.choices[0].message.content.strip()
                st.session_state.messages.append({"role": "assistant", "content": reply})

                match = re.search(r'\{.*\}', reply, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                        st.session_state.reiseinfos = parsed
                        st.session_state.stage = "stop_lookup"
                    except json.JSONDecodeError:
                        pass
            else:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "Danke für deine Rückmeldung! Ich wünsche dir eine gute Reise und bis zum nächsten Mal!"
                })

    if st.session_state.stage == "stop_lookup":
        reiseinfos = st.session_state.reiseinfos
        heute = datetime.now()
        user_hat_jahr = bool(re.search(r'\b\d{4}\b', st.session_state.user_input))
        try:
            dt = datetime.strptime(reiseinfos["datum"], "%Y-%m-%d")
            if dt.year != heute.year and not user_hat_jahr:
                dt = dt.replace(year=heute.year)
            reiseinfos["datum"] = dt.strftime("%Y-%m-%d")
        except ValueError:
            reiseinfos["datum"] = heute.strftime("%Y-%m-%d")

        uhr_raw = reiseinfos.get("uhrzeit", "08:00:00")
        m = re.match(r"^(\d{1,2}):?(\d{2})?:?(\d{2})?$", uhr_raw)
        if m:
            std  = m.group(1).zfill(2)
            minu = m.group(2) or "00"
            sek  = m.group(3) or "00"
            reiseinfos["uhrzeit"] = f"{std}:{minu}:{sek}"
        else:
            reiseinfos["uhrzeit"] = "08:00:00"

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

    if st.session_state.stage == "trip":
        info = st.session_state.reiseinfos
        datum      = info["datum"]
        uhrzeit    = info["uhrzeit"]
        start_id   = info["start_id"]
        start_name = info["start_name"]
        ziel_id    = info["ziel_id"]
        ziel_name  = info["ziel_name"]
        typ        = info.get("typ", "abfahrt")
        if typ not in ("abfahrt", "ankunft"):
            typ = "abfahrt"

        now_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # hier kannst du den XML-Request je nach typ generieren (z. B. über Hilfsfunktion)
        st.success("✅ Verbindungssuche erfolgt – hier kannst du deine trip-Logik einfügen.")
        st.session_state.stage = "done"
