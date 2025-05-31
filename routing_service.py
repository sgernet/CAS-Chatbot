# routing_service.py

def erstelle_route_mit_zwischenstopp(start, zwischenstopp, ziel, zeit):
    """
    Erstellt eine Route mit einem Zwischenstopp.
    Rückgabe: Liste von Etappen (start → zwischenstopp → ziel)
    """

    print("🔍 Etappe 1: Von", start, "nach", zwischenstopp)
    # Hier würdest du die API für die 1. Etappe aufrufen

    print("🔍 Etappe 2: Von", zwischenstopp, "nach", ziel)
    # Hier würdest du die API für die 2. Etappe aufrufen

    return [
        {"von": start, "nach": zwischenstopp, "zeit": zeit},
        {"von": zwischenstopp, "nach": ziel, "zeit": "nach Zwischenhalt"}
    ]
if __name__ == "__main__":
    route = erstelle_route_mit_zwischenstopp("Bern", "Post Zürich", "Luzern", "14:00")
    
    print("\n📍 Geplante Etappen:")
    for etappe in route:
        print(f"- {etappe['von']} → {etappe['nach']} ({etappe['zeit']})")
