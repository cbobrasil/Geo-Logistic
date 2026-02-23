import os
import json
import argparse
from datetime import datetime
import pandas as pd
import requests
import folium


def read_orders_any(path: str) -> pd.DataFrame:
    # Read orders from csv or parquet
    p = path.lower()
    if p.endswith(".csv"):
        df = pd.read_csv(path)
    elif p.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        raise ValueError("orders file must be .csv or .parquet")
    return df


def ensure_order_date(df: pd.DataFrame) -> pd.DataFrame:
    # Create order_date (yyyy-mm-dd) from the best available column
    # Supported inputs: order_date, scheduled_date, purchase_datetime, datetime, created_at, order_datetime
    df = df.copy()

    if "order_date" in df.columns:
        dt = pd.to_datetime(df["order_date"], errors="coerce")
    elif "scheduled_date" in df.columns:
        dt = pd.to_datetime(df["scheduled_date"], errors="coerce")
    elif "purchase_datetime" in df.columns:
        dt = pd.to_datetime(df["purchase_datetime"], errors="coerce")
    elif "order_datetime" in df.columns:
        dt = pd.to_datetime(df["order_datetime"], errors="coerce")
    elif "created_at" in df.columns:
        dt = pd.to_datetime(df["created_at"], errors="coerce")
    elif "datetime" in df.columns:
        dt = pd.to_datetime(df["datetime"], errors="coerce")
    else:
        raise ValueError(
            "could not find a date column. expected one of: "
            "order_date, scheduled_date, purchase_datetime, datetime, created_at, order_datetime"
        )

    df["order_date"] = dt.dt.date.astype("string")
    df = df[df["order_date"].notna()].copy()
    return df


def build_daily_destinations_table(orders_df: pd.DataFrame) -> pd.DataFrame:
    # Expected columns at minimum: lon, lat, city
    required = {"lon", "lat", "city"}
    if not required.issubset(set(orders_df.columns)):
        raise ValueError("orders_all needs columns: lon, lat, city")

    orders_df = ensure_order_date(orders_df)

    # Normalize types
    orders_df["city"] = orders_df["city"].astype(str).str.strip()
    orders_df["lon"] = pd.to_numeric(orders_df["lon"], errors="coerce")
    orders_df["lat"] = pd.to_numeric(orders_df["lat"], errors="coerce")
    orders_df = orders_df[orders_df["lon"].notna() & orders_df["lat"].notna()].copy()

    # Destination counts per day per city
    g = (
        orders_df.groupby(["order_date", "city"], as_index=False)
        .agg(
            orders_count=("city", "size"),
            lon=("lon", "median"),
            lat=("lat", "median"),
        )
        .sort_values(["order_date", "orders_count", "city"], ascending=[True, False, True])
    )

    # Pack destinations into json per day
    def pack_day(day_df: pd.DataFrame) -> str:
        recs = day_df[["city", "lat", "lon", "orders_count"]].to_dict("records")
        return json.dumps(recs, ensure_ascii=False)

    daily = (
        g.groupby("order_date", as_index=False)
        .apply(lambda x: pd.Series(
            {
                "total_orders": int(x["orders_count"].sum()),
                "unique_destinations": int(x.shape[0]),
                "destinations_json": pack_day(x),
            }
        ))
        .reset_index(drop=True)
        .sort_values("order_date")
    )

    return daily


def run_osrm_route_for_day(
    orders_df: pd.DataFrame,
    warehouse_csv: str,
    scheduled_date: str,
    max_orders: int,
    out_html: str,
    out_csv: str,
) -> None:
    # Filter orders to a specific day, then run the original route flow
    orders_df = ensure_order_date(orders_df)
    day_df = orders_df[orders_df["order_date"] == scheduled_date].copy()

    if day_df.empty:
        raise ValueError(f"no orders found for scheduled_date: {scheduled_date}")

    # Required columns
    if not {"lon", "lat", "city"}.issubset(day_df.columns):
        raise ValueError("orders need to have lon, lat, city columns")

    # Limit points
    day_df = day_df.head(max_orders).copy()

    warehouse_df = pd.read_csv(warehouse_csv)
    if not {"lon", "lat", "city"}.issubset(warehouse_df.columns):
        raise ValueError("warehouse.csv needs lon, lat, city columns")

    wh = warehouse_df.iloc[0].to_dict()
    wh_lonlat = (float(wh["lon"]), float(wh["lat"]))

    points = [wh_lonlat] + list(zip(day_df["lon"].astype(float), day_df["lat"].astype(float)))
    coords_str = ";".join([f"{lon:.6f},{lat:.6f}" for lon, lat in points])

    base_url = "https://router.project-osrm.org"
    trip_url = f"{base_url}/trip/v1/driving/{coords_str}"

    params = {
        "source": "first",
        "roundtrip": "true",
        "overview": "full",
        "geometries": "geojson",
        "annotations": "distance,duration",
    }

    resp = requests.get(trip_url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"osrm call failed: http {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    if data.get("code") != "Ok" or not data.get("trips"):
        raise RuntimeError(f"invalid osrm response: {json.dumps(data, ensure_ascii=False)[:500]}")

    trip = data["trips"][0]
    waypoints = data["waypoints"]

    ordered_wp = sorted(waypoints, key=lambda w: w["waypoint_index"])

    def idx_to_record(i: int) -> dict:
        if i == 0:
            return {"type": "warehouse", "city": wh["city"], "lon": wh_lonlat[0], "lat": wh_lonlat[1]}
        row = day_df.iloc[i - 1]
        return {
            "type": "order",
            "order_id": row.get("order_id", ""),
            "city": row["city"],
            "lon": float(row["lon"]),
            "lat": float(row["lat"]),
        }

    ordered_records = [idx_to_record(wp["waypoint_index"]) for wp in ordered_wp]

    total_distance_km = trip["distance"] / 1000.0
    total_duration_min = trip["duration"] / 60.0

    print(f"points sent (incl. warehouse): {len(points)}")
    print(f"total distance: {total_distance_km:.1f} km | total duration: {total_duration_min:.1f} min")
    print(f"date: {scheduled_date}")

    m = folium.Map(location=[wh_lonlat[1], wh_lonlat[0]], zoom_start=7, control_scale=True)

    route_geom = trip["geometry"]
    if route_geom and route_geom["type"].lower() == "linestring":
        folium.GeoJson(route_geom, name="route").add_to(m)

    for i, rec in enumerate(ordered_records, start=1):
        label = "warehouse" if rec["type"] == "warehouse" else f"order {rec.get('order_id', '')}"
        popup = f"{i}. {label} - {rec['city']}"
        folium.Marker(
            location=[rec["lat"], rec["lon"]],
            tooltip=popup,
            popup=popup,
            icon=folium.DivIcon(html=f"<div style='font-weight:bold; font-size:12px;'>{i}</div>"),
        ).add_to(m)

    os.makedirs(os.path.dirname(out_html), exist_ok=True)
    m.save(out_html)
    pd.DataFrame(ordered_records).to_csv(out_csv, index=False)

    print(f"html saved at: {os.path.abspath(out_html)}")
    print(f"sequence saved at: {os.path.abspath(out_csv)}")


def main() -> None:
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--mode",
        required=True,
        choices=["build_daily_silver", "route_day"],
        help="build_daily_silver creates the daily destinations silver table. route_day generates a route html for one day",
    )

    ap.add_argument(
        "--orders-path",
        required=True,
        help="path to orders_all.csv or orders_all.parquet",
    )

    # build_daily_silver outputs
    ap.add_argument("--out-silver-parquet", required=False, help="output parquet path for daily table")
    ap.add_argument("--out-silver-csv", required=False, help="output csv path for daily table")

    # route_day inputs and outputs
    ap.add_argument("--warehouse-csv", required=False, help="path to the warehouse CSV file")
    ap.add_argument("--scheduled-date", required=False, help="yyyy-mm-dd")
    ap.add_argument("--max-orders", type=int, default=25, help="limit of delivery points (besides the warehouse)")
    ap.add_argument("--out-html", required=False, help="output HTML file path")
    ap.add_argument("--out-csv", required=False, help="output CSV file with optimized sequence")

    args = ap.parse_args()

    orders_df = read_orders_any(args.orders_path)

    if args.mode == "build_daily_silver":
        if not args.out_silver_parquet and not args.out_silver_csv:
            raise ValueError("provide at least one: --out-silver-parquet or --out-silver-csv")

        daily_df = build_daily_destinations_table(orders_df)

        if args.out_silver_parquet:
            os.makedirs(os.path.dirname(args.out_silver_parquet), exist_ok=True)
            daily_df.to_parquet(args.out_silver_parquet, index=False)
            print(f"daily destinations parquet saved at: {os.path.abspath(args.out_silver_parquet)}")

        if args.out_silver_csv:
            os.makedirs(os.path.dirname(args.out_silver_csv), exist_ok=True)
            daily_df.to_csv(args.out_silver_csv, index=False)
            print(f"daily destinations csv saved at: {os.path.abspath(args.out_silver_csv)}")

        print(f"days: {daily_df.shape[0]}")
        if daily_df.shape[0] > 0:
            print(f"min day: {daily_df['order_date'].min()} | max day: {daily_df['order_date'].max()}")

    elif args.mode == "route_day":
        missing = []
        if not args.warehouse_csv:
            missing.append("--warehouse-csv")
        if not args.scheduled_date:
            missing.append("--scheduled-date")
        if not args.out_html:
            missing.append("--out-html")
        if not args.out_csv:
            missing.append("--out-csv")
        if missing:
            raise ValueError(f"missing arguments for route_day: {', '.join(missing)}")

        run_osrm_route_for_day(
            orders_df=orders_df,
            warehouse_csv=args.warehouse_csv,
            scheduled_date=args.scheduled_date,
            max_orders=args.max_orders,
            out_html=args.out_html,
            out_csv=args.out_csv,
        )


if __name__ == "__main__":
    main()