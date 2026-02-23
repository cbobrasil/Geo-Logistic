import os
import json
import argparse
from pathlib import Path
import pandas as pd
import requests


def read_orders_any(path: str) -> pd.DataFrame:
    p = path.lower()
    if p.endswith(".csv"):
        return pd.read_csv(path)
    if p.endswith(".parquet"):
        return pd.read_parquet(path)
    raise ValueError("orders file must be .csv or .parquet")


def ensure_order_date(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "order_date" in df.columns:
        dt = pd.to_datetime(df["order_date"], errors="coerce")
    elif "scheduled_date" in df.columns:
        dt = pd.to_datetime(df["scheduled_date"], errors="coerce")
    elif "order_datetime" in df.columns:
        dt = pd.to_datetime(df["order_datetime"], errors="coerce")
    elif "created_at" in df.columns:
        dt = pd.to_datetime(df["created_at"], errors="coerce")
    elif "datetime" in df.columns:
        dt = pd.to_datetime(df["datetime"], errors="coerce")
    else:
        raise ValueError(
            "could not find a date column. expected one of: "
            "order_date, scheduled_date, order_datetime, created_at, datetime"
        )

    df["order_date"] = dt.dt.date.astype("string")
    df = df[df["order_date"].notna()].copy()
    return df


def pick_address_cols(df: pd.DataFrame) -> tuple[str, str]:
    # tries to find usable "address like" and "order id like" columns
    address_candidates = [
        "address",
        "delivery_address",
        "destination_address",
        "shipping_address",
        "full_address",
    ]
    id_candidates = ["order_id", "id", "order_number", "order_ref"]

    address_col = next((c for c in address_candidates if c in df.columns), None)
    id_col = next((c for c in id_candidates if c in df.columns), None)

    if not address_col:
        # fallback: city is better than nothing
        address_col = "city" if "city" in df.columns else None
    if not id_col:
        id_col = "order_id" if "order_id" in df.columns else None

    if not address_col:
        raise ValueError("could not find an address column, and city not present")
    if not id_col:
        # allow empty id, but warn via print
        print("warning: could not find an order id column, list will show blank ids")
        id_col = "__no_id__"
        df[id_col] = ""

    return id_col, address_col


def osrm_trip(points_lonlat: list[tuple[float, float]]) -> dict:
    coords_str = ";".join([f"{lon:.6f},{lat:.6f}" for lon, lat in points_lonlat])

    base_url = "https://router.project-osrm.org"
    trip_url = f"{base_url}/trip/v1/driving/{coords_str}"
    params = {
        "source": "first",
        "roundtrip": "true",
        "overview": "full",
        "geometries": "geojson",
    }

    resp = requests.get(trip_url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"osrm call failed: http {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    if data.get("code") != "Ok" or not data.get("trips"):
        raise RuntimeError(f"invalid osrm response: {json.dumps(data, ensure_ascii=False)[:500]}")

    return data


def build_routes_payload(
    orders_df: pd.DataFrame,
    warehouse_csv: str,
    max_orders: int,
    limit_days: int | None,
) -> dict:
    orders_df = ensure_order_date(orders_df)

    required = {"lon", "lat", "city"}
    if not required.issubset(set(orders_df.columns)):
        raise ValueError("orders_all needs columns: lon, lat, city")

    orders_df["lon"] = pd.to_numeric(orders_df["lon"], errors="coerce")
    orders_df["lat"] = pd.to_numeric(orders_df["lat"], errors="coerce")
    orders_df = orders_df[orders_df["lon"].notna() & orders_df["lat"].notna()].copy()

    wh_df = pd.read_csv(warehouse_csv)
    if not {"lon", "lat", "city"}.issubset(set(wh_df.columns)):
        raise ValueError("warehouse.csv needs columns: lon, lat, city")

    wh = wh_df.iloc[0].to_dict()
    wh_lon = float(wh["lon"])
    wh_lat = float(wh["lat"])

    id_col, address_col = pick_address_cols(orders_df)

    all_days = sorted(orders_df["order_date"].unique().tolist())
    if limit_days is not None:
        all_days = all_days[:limit_days]

    routes_by_day = {}
    meta_by_day = {}

    for day in all_days:
        day_df = orders_df[orders_df["order_date"] == day].copy()

        # keep stable ordering before sending to osrm
        # you can change this to whatever is meaningful for you
        day_df = day_df.sort_values([ "city", id_col ]).head(max_orders).copy()

        points = [(wh_lon, wh_lat)] + list(zip(day_df["lon"].astype(float), day_df["lat"].astype(float)))

        data = osrm_trip(points)

        trip = data["trips"][0]
        waypoints = data["waypoints"]

        # sorted by waypoint_index gives the visit order
        ordered_wp = sorted(waypoints, key=lambda w: w["waypoint_index"])

        def idx_to_stop(idx: int) -> dict:
            if idx == 0:
                return {
                    "type": "warehouse",
                    "order_id": "",
                    "city": str(wh.get("city", "warehouse")),
                    "address": str(wh.get("city", "warehouse")),
                    "lon": wh_lon,
                    "lat": wh_lat,
                }
            row = day_df.iloc[idx - 1]
            return {
                "type": "order",
                "order_id": str(row.get(id_col, "")),
                "city": str(row.get("city", "")),
                "address": str(row.get(address_col, "")),
                "lon": float(row["lon"]),
                "lat": float(row["lat"]),
            }

        stops = [idx_to_stop(wp["waypoint_index"]) for wp in ordered_wp]

        routes_by_day[day] = {
            "route_geojson": trip["geometry"],
            "stops": stops,
        }

        meta_by_day[day] = {
            "total_distance_km": float(trip["distance"]) / 1000.0,
            "total_duration_min": float(trip["duration"]) / 60.0,
            "orders_used": int(day_df.shape[0]),
        }

        print(
            f"day {day} done. orders_used={meta_by_day[day]['orders_used']} "
            f"dist_km={meta_by_day[day]['total_distance_km']:.1f} "
            f"dur_min={meta_by_day[day]['total_duration_min']:.1f}"
        )

    payload = {
        "warehouse": {"lon": wh_lon, "lat": wh_lat, "city": str(wh.get("city", "warehouse"))},
        "days": all_days,
        "meta_by_day": meta_by_day,
        "routes_by_day": routes_by_day,
    }
    return payload


def write_html(payload: dict, out_html: str) -> None:
    out_html_path = Path(out_html)
    out_dir = out_html_path.parent
    os.makedirs(out_dir, exist_ok=True)

    data_path = out_dir / "report_routes_data.json"
    data_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>geo logistic routes report</title>

  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>

  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, segoe ui, roboto, ubuntu, cantarell, noto sans, sans-serif; }}
    .wrap {{ display: grid; grid-template-columns: 380px 1fr; height: 100vh; }}
    .side {{ padding: 14px; border-right: 1px solid #e6e6e6; overflow: auto; }}
    .map {{ height: 100vh; }}
    .title {{ font-size: 18px; font-weight: 700; margin: 0 0 8px 0; }}
    .sub {{ font-size: 13px; color: #444; margin: 0 0 10px 0; }}
    label {{ font-size: 12px; color: #333; }}
    select {{ width: 100%; padding: 8px; font-size: 14px; }}
    .meta {{ font-size: 12px; color: #333; background: #f7f7f7; padding: 10px; border-radius: 8px; margin-top: 10px; }}
    ol {{ padding-left: 20px; }}
    li {{ margin-bottom: 10px; }}
    .stop-type {{ font-size: 11px; color: #666; text-transform: uppercase; }}
    .stop-main {{ font-size: 13px; font-weight: 600; }}
    .stop-sub {{ font-size: 12px; color: #444; }}
    .hint {{ font-size: 12px; color: #666; margin-top: 10px; }}
    .err {{ color: #b00020; font-size: 12px; white-space: pre-wrap; }}
  </style>
</head>

<body>
<div class="wrap">
  <div class="side">
    <div class="title">routes report</div>
    <div class="sub">select a date to view the optimized route and ordered stop list</div>

    <label for="day_select">date</label>
    <select id="day_select"></select>

    <div class="meta" id="meta_box">loading...</div>

    <div style="font-size: 13px; font-weight: 700; margin: 12px 0 6px 0;">stops in order</div>
    <ol id="stops_list"></ol>
    <div class="hint">note: this route uses osrm trip with a roundtrip starting at the warehouse</div>

    <div class="err" id="err_box"></div>
  </div>

  <div id="map" class="map"></div>
</div>

<script>
  let data = null;

  function setError(msg) {{
    document.getElementById("err_box").textContent = msg || "";
  }}

  async function loadData() {{
    const resp = await fetch("./report_routes_data.json");
    if (!resp.ok) {{
      throw new Error("could not load report_routes_data.json, http " + resp.status);
    }}
    return await resp.json();
  }}

  function initUi() {{
    const wh = data.warehouse;
    const map = L.map("map").setView([wh.lat, wh.lon], 7);

    L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
      maxZoom: 19,
      attribution: "© OpenStreetMap contributors"
    }}).addTo(map);

    let routeLayer = null;
    let markerLayer = L.layerGroup().addTo(map);

    function clearLayers() {{
      if (routeLayer) {{
        map.removeLayer(routeLayer);
        routeLayer = null;
      }}
      markerLayer.clearLayers();
    }}

    function setMeta(day) {{
      const m = data.meta_by_day[day];
      const el = document.getElementById("meta_box");
      el.innerHTML = `
        <div><b>date:</b> ${{day}}</div>
        <div><b>orders used:</b> ${{m.orders_used}}</div>
        <div><b>distance:</b> ${{m.total_distance_km.toFixed(1)}} km</div>
        <div><b>duration:</b> ${{m.total_duration_min.toFixed(1)}} min</div>
      `;
    }}

    function setStopsList(day) {{
      const stops = data.routes_by_day[day].stops;
      const ol = document.getElementById("stops_list");
      ol.innerHTML = "";

      stops.forEach((s, i) => {{
        const li = document.createElement("li");
        const type = s.type === "warehouse" ? "warehouse" : "delivery";
        const title = s.type === "warehouse"
          ? "warehouse: " + (s.city || "warehouse")
          : "order " + (s.order_id || "");
        const sub = s.address || s.city || "";

        li.innerHTML = `
          <div class="stop-type">${{type}}</div>
          <div class="stop-main">${{i + 1}}. ${{title}}</div>
          <div class="stop-sub">${{sub}}</div>
        `;
        ol.appendChild(li);
      }});
    }}

    function addMarkers(day) {{
      const stops = data.routes_by_day[day].stops;
      stops.forEach((s, i) => {{
        const popup = (i + 1) + ". " + (s.type === "warehouse" ? "warehouse" : "order") + " - " + (s.city || "");
        L.marker([s.lat, s.lon], {{ title: popup }}).bindPopup(popup).addTo(markerLayer);
      }});
    }}

    function setRoute(day) {{
      clearLayers();

      const route = data.routes_by_day[day].route_geojson;
      routeLayer = L.geoJSON(route).addTo(map);

      addMarkers(day);
      setStopsList(day);
      setMeta(day);

      try {{
        map.fitBounds(routeLayer.getBounds(), {{ padding: [20, 20] }});
      }} catch (e) {{
        map.setView([wh.lat, wh.lon], 7);
      }}
    }}

    const sel = document.getElementById("day_select");
    sel.innerHTML = "";

    if (!data.days || data.days.length === 0) {{
      document.getElementById("meta_box").textContent = "no days found in dataset";
      return;
    }}

    data.days.forEach((d) => {{
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      sel.appendChild(opt);
    }});

    sel.addEventListener("change", (e) => setRoute(e.target.value));

    sel.value = data.days[data.days.length - 1];
    setRoute(sel.value);
  }}

  (async () => {{
    try {{
      data = await loadData();
      initUi();
    }} catch (e) {{
      setError(String(e));
      document.getElementById("meta_box").textContent = "failed to load report data";
    }}
  }})();
</script>

</body>
</html>
"""
    out_html_path.write_text(html, encoding="utf-8")

    print(f"data saved at: {os.path.abspath(str(data_path))}")
    print(f"html saved at: {os.path.abspath(str(out_html_path))}")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders-path", required=True, help="data/silver/orders_all.csv or .parquet")
    ap.add_argument("--warehouse-csv", required=True, help="data/warehouse.csv")
    ap.add_argument("--out-html", required=True, help="output html path")
    ap.add_argument("--max-orders", type=int, default=25)
    ap.add_argument("--limit-days", type=int, default=None)

    args = ap.parse_args()

    orders_df = read_orders_any(args.orders_path)

    payload = build_routes_payload(
        orders_df=orders_df,
        warehouse_csv=args.warehouse_csv,
        max_orders=args.max_orders,
        limit_days=args.limit_days,
    )

    write_html(payload, args.out_html)


if __name__ == "__main__":
    main()