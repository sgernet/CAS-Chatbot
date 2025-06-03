import streamlit as st

st.set_page_config(page_title="🚆 ÖV-Chatbot Schweiz", layout="wide")

from streamlit_db import zeige_streamlit_db
from streamlit_chatbot_mit_db import zeige_streamlit_chatbot

def main():
    tab1, tab2 = st.tabs(["Profil", "Chatbot"])
    with tab1:
        zeige_streamlit_db()
    with tab2:
        zeige_streamlit_chatbot()

if __name__ == "__main__":
    main()
