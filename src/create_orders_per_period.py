# Generate fake delivery data in portugal + warehouse at Porto

import random
import uuid
from datetime import date, timedelta, timezone, datetime
import pandas as pd
from pathlib import Path

# -------- configurations --------
seed = 42
random.seed(seed)

start_date = date(2025, 10, 1)
end_date   = date(2025, 10, 20)


current_ts = datetime.now(timezone.utc)

# Quantity per day  
min_orders_per_day = 5
max_orders_per_day = 15


# output directory for per-day files
out_dir = Path(__file__).resolve().parent.parent / "data" / "bronze"
out_dir.mkdir(parents=True, exist_ok=True)

# Cities
cities = [
    {"city": "porto", "lon": -8.6291, "lat": 41.1579},
    {"city": "lisboa", "lon": -9.1393, "lat": 38.7223},
    {"city": "braga", "lon": -8.4292, "lat": 41.5454},
    {"city": "coimbra", "lon": -8.4292, "lat": 40.2033},
    {"city": "aveiro", "lon": -8.6455, "lat": 40.6405},
    {"city": "faro", "lon": -7.9351, "lat": 37.0194},
    {"city": "viseu", "lon": -7.9137, "lat": 40.6610},
    {"city": "évora", "lon": -7.9097, "lat": 38.5667},
    {"city": "setúbal", "lon": -8.8932, "lat": 38.5244},
    {"city": "leiria", "lon": -8.8050, "lat": 39.7436},
    {"city": "viana do castelo", "lon": -8.8333, "lat": 41.6932},
    {"city": "vilareal", "lon": -7.7461, "lat": 41.3006},
    {"city": "bragança", "lon": -6.7567, "lat": 41.8067},
    {"city": "guarda", "lon": -7.2620, "lat": 40.5373},
    {"city": "santarém", "lon": -8.6820, "lat": 39.2362},
    {"city": "castelo branco", "lon": -7.4909, "lat": 39.8222},
    {"city": "portalegre", "lon": -7.4322, "lat": 39.2967},
    {"city": "beja", "lon": -7.8632, "lat": 38.0151},
]

# warehouse 
warehouse_city = next(c for c in cities if c["city"] == "porto")
warehouse = {
    "warehouse_id": "wh-porto-001",
    "name": "warehouse porto",
    "city": warehouse_city["city"],
    "lon": warehouse_city["lon"],
    "lat": warehouse_city["lat"],
}

# -------- functions --------

def daterange_inclusive(start: date, end: date):
    for i in range((end - start).days + 1):
        yield start + timedelta(days=i)

def jitter_coords(lon, lat, max_delta_deg_lon=0.03, max_delta_deg_lat=0.02):
    dlon = random.uniform(-max_delta_deg_lon, max_delta_deg_lon)
    dlat = random.uniform(-max_delta_deg_lat, max_delta_deg_lat)
    return lon + dlon, lat + dlat


# -------- generate orders  --------
written_dates = []
total_rows = 0

for d in daterange_inclusive(start_date, end_date):
    n = random.randint(min_orders_per_day, max_orders_per_day)
    rows = []
    for _ in range(n):
        base = random.choice(cities)
        lon, lat = jitter_coords(base["lon"], base["lat"])
        rows.append(
            {
                "order_id": f"ord-{uuid.uuid4().hex[:8]}",
                "scheduled_date": d.isoformat(),
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "city": base["city"],
                "service_time_min": random.choice([5, 10, 15, 20]),
                "priority": random.choice(["low", "normal", "high"]),
                "datetime_ingestion": current_ts,
            }
        )

    day_df = pd.DataFrame(rows)
    fname = out_dir / f"orders_pt_{d.isoformat()}.csv"
    day_df.to_csv(fname, index=False)
    print(f"ok: {fname}  ({len(day_df)} linhas)")
    written_dates.append(d.isoformat())
    total_rows += len(day_df)

warehouse_path = out_dir / "warehouse_pt.csv"
pd.DataFrame([warehouse]).to_csv(warehouse_path, index=False)


# --- validação: todos os dias existem? ---
expected = [(start_date + timedelta(days=i)).isoformat()
            for i in range((end_date - start_date).days + 1)]
missing = [d for d in expected if d not in written_dates]
extra   = [d for d in written_dates if d not in expected]

print("\nresume:")
print(f"files gerated: {len(written_dates)}  (expected: {len(expected)})")
print(f"total rows: {total_rows}")
if missing:
    print("missing:", missing)
if extra:
    print("extras:", extra)