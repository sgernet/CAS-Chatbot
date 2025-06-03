import requests
from google.transit import gtfs_realtime_pb2
import datetime
from dotenv import load_dotenv
import os

# Deinen API-Key hier einfügen

load_dotenv()
try:
    GTFS_RT_API_KEY = os.environ["GTFS_RT_API_KEY"]
    OJP_API_KEY   = os.environ["OJP_API_KEY"]
except KeyError as e:
    raise RuntimeError(f"Umgebungsvariable {e.args[0]} fehlt!") from None


url = "https://api.opentransportdata.swiss/la/gtfs-rt"
# HTTP-Header inkl. Authorization & User-Agent
headers = {
    "Authorization": f"Bearer {GTFS_RT_API_KEY}",
    "User-Agent": "gtfs-test-client/1.0",
    "Accept": "application/octet-stream"
}

response = requests.get(url, headers=headers)

if response.status_code != 200:
    print(f"❌ Fehler beim Abrufen: {response.status_code}")
    print(response.text)
    exit()

# Protobuf-Nachricht verarbeiten
feed = gtfs_realtime_pb2.FeedMessage()
feed.ParseFromString(response.content)

print(f"✅ Feed enthält {len(feed.entity)} Trip-Updates")
for entity in feed.entity[:5]:  # nur die ersten 5 anzeigen
    if entity.HasField("trip_update"):
        trip = entity.trip_update.trip
        print(f"🔹 Trip ID: {trip.trip_id} | Route: {trip.route_id}")