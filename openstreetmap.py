import streamlit as st
from geopy.geocoders import Nominatim
import requests
import ssl
import certifi
import pandas as pd
import folium
from folium.features import DivIcon
import streamlit.components.v1 as components

# --- Seite konfigurieren ---
st.set_page_config(page_title="Einkaufsmöglichkeiten finden", layout="wide")

# SSL-Kontext für Geopy
ssl_ctx = ssl.create_default_context(cafile=certifi.where())

@st.cache_data
def get_coordinates(address: str):
    """Gibt (lat, lon) zurück oder (None, None)."""
    geolocator = Nominatim(user_agent="streamlit_shop_app", ssl_context=ssl_ctx)
    try:
        loc = geolocator.geocode(address, timeout=10)
    except Exception:
        return None, None
    return (loc.latitude, loc.longitude) if loc else (None, None)

@st.cache_data
def get_shops(lat: float, lon: float, radius: int = 1000) -> pd.DataFrame:
    """Fragt Overpass API ab und liefert DataFrame mit Name, Typ, lat, lon, Nr."""
    overpass_url = "http://overpass-api.de/api/interpreter"
    query = f"""
    [out:json];
    (
      node["shop"](around:{radius},{lat},{lon});
      way["shop"](around:{radius},{lat},{lon});
      relation["shop"](around:{radius},{lat},{lon});
    );
    out center;
    """
    resp = requests.get(overpass_url, params={"data": query})
    data = resp.json()
    shops = []
    for el in data.get("elements", []):
        lat_e = el.get("lat") or el.get("center", {}).get("lat")
        lon_e = el.get("lon") or el.get("center", {}).get("lon")
        tags = el.get("tags", {})
        shops.append({
            "Name": tags.get("name", "Unbenannter Shop"),
            "Typ":  tags.get("shop", "unbekannt"),
            "lat":  lat_e,
            "lon":  lon_e
        })
    df = pd.DataFrame(shops)
    df["Nr"] = df.index + 1
    return df

# --- Eingaben ---
st.title("🔍 Einkaufsmöglichkeiten finden")
address = st.text_input("Adresse oder Ort eingeben")
radius  = st.slider("Radius um Adresse (in Metern)", 100, 2000, 500, step=50)

# 1) Suche ausführen und Ergebnis cachen
if st.button("Suchen"):
    if not address.strip():
        st.warning("Bitte gib eine Adresse oder einen Ort ein.")
        st.session_state.pop("shops_df", None)
    else:
        lat, lon = get_coordinates(address)
        if lat is None:
            st.error("Die angegebene Adresse konnte nicht gefunden werden.")
            st.session_state.pop("shops_df", None)
        else:
            df = get_shops(lat, lon, radius)
            st.session_state["shops_df"] = {"df": df, "lat": lat, "lon": lon}

# 2) Wenn wir ein Ergebnis haben, zeigen wir Filter + Karte + Tabelle
if "shops_df" in st.session_state:
    data = st.session_state["shops_df"]
    df   = data["df"]
    lat  = data["lat"]
    lon  = data["lon"]

    # Filter nach Shop-Typ (immer sichtbar)
    shop_types    = sorted(df["Typ"].unique())
    selected_types = st.multiselect(
        "Shop-Typen filtern",
        shop_types,
        default=shop_types,
        key="shop_type_filter"
    )
    df_filtered = df[df["Typ"].isin(selected_types)]

    if df_filtered.empty:
        st.warning("Keine Einkaufsmöglichkeiten gefunden (nach Filter).")
    else:
        st.subheader(f"Shops um '{address}' (Radius {radius} m)")

        # --- Folium-Karte erzeugen ---
        m = folium.Map(
            location=[lat, lon],
            zoom_start=15,
            tiles="CartoDB dark_matter"
        )

        # Benutzer-Standort markieren
        folium.Marker(
            [lat, lon],
            icon=folium.Icon(color="blue", icon="home", prefix='fa'),
            popup="Eingegebener Ort",
            tooltip="Eingegebener Ort"
        ).add_to(m)

        # Kreise und nummerierte Marker
        for _, row in df_filtered.iterrows():
            folium.Circle(
                radius=20,
                location=(row.lat, row.lon),
                color="white",
                weight=1,
                fill=True,
                fill_color="red",
                fill_opacity=0.7
            ).add_to(m)

            folium.map.Marker(
                [row.lat, row.lon],
                icon=DivIcon(
                    icon_size=(30, 30),
                    icon_anchor=(15, 15),
                    html=(
                        f"<div style='font-size:12px;"
                        f"color:white;text-align:center;"
                        f"width:30px;line-height:30px;'>"
                        f"{row.Nr}</div>"
                    ),
                )
            ).add_to(m)

        # Karte in Streamlit einbetten
        map_html = m._repr_html_()
        components.html(map_html, height=500, width=700)

        # Tabelle mit Details
        st.dataframe(df_filtered[["Nr", "Name", "Typ"]])

# --- Installationshinweis ---
st.markdown("---")
st.info(
    "Diese App nutzt die OpenStreetMap-Datenbank und die Overpass API. "
    "Die Daten können unvollständig oder veraltet sein. "
    "Bitte beachte die [Nutzungsbedingungen](https://www.openstreetmap.org/copyright)."
)
