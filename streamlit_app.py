import streamlit as st
from streamlit_db import zeige_streamlit_db
from streamlit_chatbot_V2 import zeige_streamlit_chatbot_V2

def main():
    tab1, tab2 = st.tabs(["Profil", "Chatbot"])
    with tab1:
        zeige_streamlit_db()
    with tab2:
        zeige_streamlit_chatbot_V2()

if __name__ == "__main__":
    main()
