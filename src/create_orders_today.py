# create one-day fake orders file (for today's date)
import random, uuid, pathlib
from datetime import datetime, timezone, date
import pandas as pd

# --- configs ---
seed = 42
random.seed(seed)

# define a data do dia atual (em UTC)
today = datetime.now(timezone.utc).date()
current_ts = datetime.now(timezone.utc)

min_orders_per_day = 5
max_orders_per_day = 15

# --- output path ---
out_dir = pathlib.Path(__file__).resolve().parent.parent / "data" / "bronze"
out_dir.mkdir(parents=True, exist_ok=True)

# --- cities ---
cities = [
    {"city": "porto", "lon": -8.6291, "lat": 41.1579},
    {"city": "lisboa", "lon": -9.1393, "lat": 38.7223},
    {"city": "braga", "lon": -8.4292, "lat": 41.5454},
    {"city": "coimbra", "lon": -8.4292, "lat": 40.2033},
]

# ---  function ---
def jitter_coords(lon, lat, dlon=0.03, dlat=0.02):
    return lon + random.uniform(-dlon, dlon), lat + random.uniform(-dlat, dlat)

# --- generate orders for today  ---
orders_today = random.randint(min_orders_per_day, max_orders_per_day)
rows = []
for _ in range(orders_today):
    base = random.choice(cities)
    lon, lat = jitter_coords(base["lon"], base["lat"])
    rows.append({
        "order_id": f"ord-{uuid.uuid4().hex[:8]}",
        "scheduled_date": today.isoformat(),
        "lon": round(lon, 6),
        "lat": round(lat, 6),
        "city": base["city"],
        "service_time_min": random.choice([5, 10, 15, 20]),
        "priority": random.choice(["low", "normal", "high"]),
        "datetime_ingestion": current_ts,
    })

# --- saving ---
day_df = pd.DataFrame(rows)
fname = out_dir / f"orders_pt_{today.isoformat()}.csv"
day_df.to_csv(fname, index=False)

print(f"ok: {fname}  ({len(day_df)} linhas geradas)")
