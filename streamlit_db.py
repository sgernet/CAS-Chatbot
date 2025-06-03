import streamlit as st

# Inhalt von streamlit_db.py
def zeige_streamlit_db():
    print("Nutzerprofil anlegen")

st.title("📝 Nutzerprofil anlegen")

with st.form("profil_formular"):
    # 1–3: Basisdaten
    vorname = st.text_input("Vorname*", max_chars=50)
    nachname = st.text_input("Nachname*", max_chars=50)
    email = st.text_input("E-Mail*", max_chars=100)

    # 4: Passwort
    passwort = st.text_input("Passwort*", type="password")
    passwort2 = st.text_input("Passwort wiederholen*", type="password")
    st.caption("🔒 Mindestens 6 Zeichen")

    # 5–7: Adresse
    strasse = st.text_input("Straße und Hausnummer")
    plz = st.number_input("Postleitzahl", min_value=0, step=1)
    ort = st.text_input("Ort", max_chars=50)

    # 8–15: Checkboxen
    barrierefrei = st.checkbox("Benötige barrierefreie Mobilität")
    wenig_umsteigen = st.checkbox("Route mit möglichst wenigen Umstiegen")
    schnell_umsteigen = st.checkbox("Schnelles Umsteigen ist möglich")
    eigenes_velo = st.checkbox("Ich nutze mein eigenes Velo")
    leihvelo = st.checkbox("Ich bin an Leihvelos interessiert")
    escooter = st.checkbox("Ich nutze E-Scooter")
    eigenes_auto = st.checkbox("Ich nutze mein eigenes Auto")
    carsharing = st.checkbox("Ich bin an Carsharing interessiert")

    # 16: Dialogform
    dialogform = st.text_area("Dialogform / Gesprächsmodus*", placeholder="z. B. 'Kurz und knapp', 'Locker erklärt'")

    # 17: Wetter
    wetter = st.checkbox("Ja, ich möchte wetterabhängige Routenvorschläge")

    # 18: Reisetyp
    reisetyp = st.text_area("Reisetyp*", placeholder="z. B. 'Pendler', 'Freizeit', 'Einkauf'")

    submitted = st.form_submit_button("💾 Profil speichern")

if submitted:
    # Validierung
    if passwort != passwort2:
        st.error("❌ Die Passwörter stimmen nicht überein.")
    elif not vorname or not nachname or not email or not dialogform or not reisetyp:
        st.error("❌ Bitte fülle alle Pflichtfelder (*) aus.")
    elif len(passwort) < 6:
        st.error("❌ Passwort muss mindestens 6 Zeichen lang sein.")
    else:
        st.success("✅ Profil erfolgreich erfasst (noch ohne Datenbankanbindung).")
        # Hier kannst du optional die Daten in eine Datenbank speichern
