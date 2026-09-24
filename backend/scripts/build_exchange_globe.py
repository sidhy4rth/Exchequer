"""Build the exchange points for the sign-in globe.

Pulls every exchange CoinGecko lists (free endpoint, no key), keeps the ones
that name a country of registration, and places each at that country's
capital or main financial city. Exchanges in the same country are spread in
a small golden-angle spiral round the city so they read as a cluster rather
than one dot. Decentralised venues have no country and are counted but not
placed.

    backend/.venv/bin/python -m scripts.build_exchange_globe

Writes frontend/src/data/exchange_globe.json.
"""

import json
import math
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "exchange_globe.json"
API = "https://api.coingecko.com/api/v3/exchanges?per_page=250&page={}"

# Where a country's exchanges sit on the globe: its capital or the city its
# exchanges actually cluster in. (lat, lon)
PLACES = {
    "United States": (40.71, -74.01),          # New York
    "British Virgin Islands": (18.43, -64.62),  # Road Town
    "Seychelles": (-4.62, 55.45),               # Victoria
    "Singapore": (1.29, 103.85),
    "Panama": (8.98, -79.52),
    "Panama Canal Zone": (8.98, -79.52),
    "Cayman Islands": (19.29, -81.37),          # George Town
    "United Arab Emirates": (25.20, 55.27),     # Dubai
    "Japan": (35.68, 139.69),                   # Tokyo
    "Switzerland": (47.17, 8.52),               # Zug
    "Australia": (-33.87, 151.21),              # Sydney
    "Turkey": (41.01, 28.98),                   # Istanbul
    "Lithuania": (54.69, 25.28),                # Vilnius
    "South Korea": (37.57, 126.98),             # Seoul
    "India": (19.08, 72.88),                    # Mumbai
    "Saint Vincent and the Grenadines": (13.16, -61.22),
    "Hong Kong": (22.32, 114.17),
    "Indonesia": (-6.21, 106.85),               # Jakarta
    "Estonia": (59.44, 24.75),                  # Tallinn
    "Canada": (43.65, -79.38),                  # Toronto
    "Marshall Islands": (7.09, 171.38),         # Majuro
    "United Kingdom": (51.51, -0.13),           # London
    "Thailand": (13.76, 100.50),                # Bangkok
    "Spain": (40.42, -3.70),
    "Samoa": (-13.83, -171.76),
    "Taiwan": (25.03, 121.57),
    "Costa Rica": (9.93, -84.08),
    "China": (31.23, 121.47),                   # Shanghai
    "Netherlands": (52.37, 4.90),
    "Gibraltar": (36.14, -5.35),
    "South Africa": (-26.20, 28.05),            # Johannesburg
    "Italy": (45.46, 9.19),                     # Milan
    "Brazil": (-23.55, -46.63),                 # São Paulo
    "Bahamas": (25.05, -77.35),                 # Nassau
    "Germany": (50.11, 8.68),                   # Frankfurt
    "El Salvador": (13.69, -89.22),
    "France": (48.86, 2.35),
    "Israel": (32.09, 34.78),                   # Tel Aviv
    "Poland": (52.23, 21.01),
    "Georgia": (41.72, 44.79),                  # Tbilisi
    "Andorra": (42.51, 1.52),
    "Romania": (44.43, 26.10),
    "Luxembourg": (49.61, 6.13),
    "Malta": (35.90, 14.51),
    "Austria": (48.21, 16.37),
    "Bermuda": (32.29, -64.78),
    "Philippines": (14.60, 120.98),
    "Vanuatu": (-17.73, 168.32),
    "Malaysia": (3.14, 101.69),
    "Isle of Man": (54.15, -4.48),
    "Jamaica": (18.02, -76.80),
    "Chile": (-33.45, -70.67),
    "Vietnam": (10.82, 106.63),                 # Ho Chi Minh City
    "Norway": (59.91, 10.75),
    "Ukraine": (50.45, 30.52),
    "Chad": (12.13, 15.06),
    "Cyprus": (34.68, 33.04),                   # Limassol
    "Anguilla": (18.22, -63.06),
    "Russia": (55.76, 37.62),
    "Sweden": (59.33, 18.07),
    "Canton and Enderbury Islands": (-2.84, -171.68),
}


def fetch_all():
    rows, page = [], 1
    while True:
        for attempt in range(5):
            with urllib.request.urlopen(API.format(page), timeout=30) as resp:
                data = json.load(resp)
            if isinstance(data, list):
                break
            time.sleep(20 * (attempt + 1))  # rate limited: back off
        else:
            raise RuntimeError(f"CoinGecko kept refusing page {page}")
        if not data:
            return rows
        rows += data
        page += 1
        time.sleep(4)


def main():
    rows = fetch_all()
    by_country, unplaced = {}, 0
    for row in rows:
        country = row.get("country")
        if country not in PLACES:
            unplaced += 1
            continue
        by_country.setdefault(country, []).append(row)

    points = []
    for country, members in by_country.items():
        lat0, lon0 = PLACES[country]
        members.sort(key=lambda r: r.get("trust_score_rank") or 10_000)
        for i, row in enumerate(members):
            # Golden-angle spiral: first (best-ranked) exchange on the city.
            r = 0.9 * math.sqrt(i)
            a = i * 2.399963
            lat = lat0 + r * math.sin(a)
            lon = lon0 + r * math.cos(a) / max(0.2, math.cos(math.radians(lat0)))
            points.append({
                "name": row["name"],
                "country": country,
                "year": row.get("year_established"),
                "rank": row.get("trust_score_rank"),
                "lat": round(lat, 3),
                "lon": round(lon, 3),
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "CoinGecko /exchanges",
        "fetched": time.strftime("%Y-%m-%d"),
        "total": len(rows),
        "unplaced": unplaced,
        "points": points,
    }, separators=(",", ":")))
    print(f"{len(rows)} exchanges, {len(points)} placed, {unplaced} without a country")


if __name__ == "__main__":
    main()
