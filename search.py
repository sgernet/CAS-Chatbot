import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="SearchChMap in Streamlit", layout="wide")

html_code = """
<!-- Load the search.ch Map API -->
<script src="https://search.ch/map/api/map.js?lang=de"></script>

<!-- Karte und Button -->
<div style="margin-bottom:10px">
  <button onclick="showService()">Services anzeigen</button>
</div>
<div id="mapwidget" style="width:100%; height:600px;"></div>

<script>
  // Karte initialisieren – hier wird 'service' als POI-Gruppe geladen
  var map = new SearchChMap({
    container: "mapwidget",
    center: "Zürich,Niederdorfstr.10",
    poigroups: "service"
  });

  function showService() {
    map.showPOIGroup("service");
  }
</script>
"""

components.html(html_code, height=650, scrolling=True)

