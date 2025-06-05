# streamlit_karte.py

import math
import xml.etree.ElementTree as ET
import pydeck as pdk
import streamlit as st

# Pfad zur XML-Datei
XML_FILE = "response.xml"

# Namespaces definieren
namespaces = {
    "siri": "http://www.siri.org.uk/siri",
    "ojp": "http://www.vdv.de/ojp"
}

@st.cache_data
def parse_xml_and_extract_path(xml_path):
    """
    Liest die XML-Datei ein, parst sie und extrahiert die Sequenz von StopPoint-Referenzen
    sowie deren Koordinaten. Gibt eine Liste von [lon, lat] zurück, die den Routenverlauf bilden.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    stoppoint_to_coords = {}
    for loc in root.findall(".//ojp:Location", namespaces):
        sp = loc.find("ojp:StopPoint", namespaces)
        if sp is not None:
            ref_elem = sp.find("siri:StopPointRef", namespaces)
            if ref_elem is not None:
                sp_ref = ref_elem.text.strip()
                geo = loc.find("ojp:GeoPosition", namespaces)
                if geo is not None:
                    lon_elem = geo.find("siri:Longitude", namespaces)
                    lat_elem = geo.find("siri:Latitude", namespaces)
                    if lon_elem is not None and lat_elem is not None:
                        lon = float(lon_elem.text)
                        lat = float(lat_elem.text)
                        stoppoint_to_coords[sp_ref] = (lon, lat)

    first_trip = root.find(".//ojp:TripResult", namespaces)
    if first_trip is None:
        return []

    trip = first_trip.find("ojp:Trip", namespaces)
    if trip is None:
        return []

    sequence_of_refs = []
    for leg in trip.findall("ojp:TripLeg", namespaces):
        timed = leg.find("ojp:TimedLeg", namespaces)
        if timed is not None:
            board_ref_elem = timed.find("ojp:LegBoard/siri:StopPointRef", namespaces)
            if board_ref_elem is not None:
                sequence_of_refs.append(board_ref_elem.text.strip())
            alight_ref_elem = timed.find("ojp:LegAlight/siri:StopPointRef", namespaces)
            if alight_ref_elem is not None:
                sequence_of_refs.append(alight_ref_elem.text.strip())

        transfer = leg.find("ojp:TransferLeg", namespaces)
        if transfer is not None:
            start_ref_elem = transfer.find("ojp:LegStart/siri:StopPointRef", namespaces)
            if start_ref_elem is not None:
                sequence_of_refs.append(start_ref_elem.text.strip())
            end_ref_elem = transfer.find("ojp:LegEnd/siri:StopPointRef", namespaces)
            if end_ref_elem is not None:
                sequence_of_refs.append(end_ref_elem.text.strip())

    path_coords = []
    for ref in sequence_of_refs:
        coords = stoppoint_to_coords.get(ref)
        if coords:
            path_coords.append([coords[0], coords[1]])

    deduped = []
    prev = None
    for pt in path_coords:
        if pt != prev:
            deduped.append(pt)
        prev = pt

    return deduped


def show_reiseweg():
    """
    Zeigt in Streamlit die pydeck-Karte mit dem Reiseweg an.
    """
    path = parse_xml_and_extract_path(XML_FILE)

    if not path:
        st.error("Keine Route/Koordinaten gefunden. Bitte überprüfen Sie die XML-Datei.")
        return

    # Min/Max für Bounding-Box
    lons = [pt[0] for pt in path]
    lats = [pt[1] for pt in path]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)

    # Mittelpunkt berechnen
    center_lon = (lon_min + lon_max) / 2
    center_lat = (lat_min + lat_max) / 2

    # Zoom-Level approximativ berechnen
    lon_span = lon_max - lon_min
    lat_span = lat_max - lat_min

    if lon_span == 0 or lat_span == 0:
        zoom_level = 14
    else:
        zoom_lon = math.log2(360.0 / lon_span)
        zoom_lat = math.log2(180.0 / lat_span)
        zoom_level = min(zoom_lon, zoom_lat) - 1
        zoom_level = max(0, min(zoom_level, 20))

    # PathLayer: dicke, rote Linie
    path_layer = pdk.Layer(
        "PathLayer",
        data=[{"path": path}],
        get_path="path",
        get_width=16,
        get_color=[220, 20, 60],  # Carmine-Red
        opacity=1.0,
    )

    # ScatterplotLayer: Start-/Endpunkt
    start_point = {"position": path[0], "color": [0, 128, 0], "radius": 100}
    end_point = {"position": path[-1], "color": [0, 0, 255], "radius": 100}

    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=[start_point, end_point],
        get_position="position",
        get_fill_color="color",
        get_radius="radius",
        pickable=True,
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=zoom_level,
        pitch=0,
    )

    deck = pdk.Deck(
        layers=[path_layer, scatter_layer],
        initial_view_state=view_state,
        map_style="mapbox://styles/mapbox/light-v10",
    )

    st.pydeck_chart(deck)


if __name__ == "__main__":
    # Wenn man streamlit_karte.py direkt ausführt, zeigt er die Karte auch alleine an
    st.title("Reiseweg")
    show_reiseweg()
