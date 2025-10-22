import os, json, argparse
from datetime import datetime, timezone
import requests
import pandas as pd
import folium

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders-csv", required=True, help="caminho para o csv de orders do dia")
    ap.add_argument("--warehouse-csv", required=True, help="caminho para o csv de warehouse")
    ap.add_argument("--max-orders", type=int, default=25, help="limite de pontos (além da warehouse)")
    ap.add_argument("--out-html", required=True, help="arquivo html de saída")
    ap.add_argument("--out-csv", required=True, help="arquivo csv com sequência otimizada")
    ap.add_argument("--scheduled-date", required=False, help="yyyy-mm-dd (usado só para logs)")
    args = ap.parse_args()

    # -------- carregar dados --------
    orders_df = pd.read_csv(args.orders_csv)
    warehouse_df = pd.read_csv(args.warehouse_csv)

    assert {"lon", "lat", "city"}.issubset(orders_df.columns), "orders.csv deve ter colunas lon, lat, city"
    assert {"lon", "lat", "city"}.issubset(warehouse_df.columns), "warehouse.csv deve ter colunas lon, lat, city"

    # limita quantidade de orders (para não exagerar no demo server)
    orders_df = orders_df.head(args.max_orders).copy()
    if orders_df.empty:
        raise ValueError("nenhuma order encontrada.")

    # pega a warehouse (primeira linha)
    wh = warehouse_df.iloc[0].to_dict()
    wh_lonlat = (float(wh["lon"]), float(wh["lat"]))

    # constrói lista de pontos: warehouse primeiro, depois orders
    points = [wh_lonlat] + list(zip(orders_df["lon"].astype(float), orders_df["lat"].astype(float)))

    # monta string de coordenadas no formato osrm: "lon,lat;lon,lat;..."
    coords_str = ";".join([f"{lon:.6f},{lat:.6f}" for lon, lat in points])

    # -------- chamada ao osrm /trip --------
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
        raise RuntimeError(f"falha na chamada osrm: http {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    if data.get("code") != "Ok" or not data.get("trips"):
        raise RuntimeError(f"resposta inválida do osrm: {json.dumps(data, ensure_ascii=False)[:500]}")

    trip = data["trips"][0]
    waypoints = data["waypoints"]

    # -------- extrair ordem otimizada --------
    ordered_wp = sorted(waypoints, key=lambda w: w["waypoint_index"])

    def idx_to_record(i):
        if i == 0:
            return {"type": "warehouse", "city": wh["city"], "lon": wh_lonlat[0], "lat": wh_lonlat[1]}
        else:
            row = orders_df.iloc[i-1]
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

    print(f"pontos enviados (incl. warehouse): {len(points)}")
    print(f"distância total: {total_distance_km:.1f} km | duração total: {total_duration_min:.1f} min")
    if args.scheduled_date:
        print(f"data: {args.scheduled_date}")

    # -------- gerar mapa folium --------
    m = folium.Map(location=[wh_lonlat[1], wh_lonlat[0]], zoom_start=7, control_scale=True)

    route_geom = trip["geometry"]  # geojson
    if route_geom and route_geom["type"].lower() == "linestring":
        folium.GeoJson(route_geom, name="rota").add_to(m)

    for i, rec in enumerate(ordered_records, start=1):
        label = "warehouse" if rec["type"] == "warehouse" else f"order {rec.get('order_id','')}"
        popup = f"{i}. {label} — {rec['city']}"
        folium.Marker(
            location=[rec["lat"], rec["lon"]],
            tooltip=popup,
            popup=popup,
            icon=folium.DivIcon(html=f"""<div style="font-weight:bold; font-size:12px;">{i}</div>"""),
        ).add_to(m)

    # salvar saídas (na pasta já escolhida por quem chamou)
    os.makedirs(os.path.dirname(args.out_html), exist_ok=True)
    m.save(args.out_html)
    pd.DataFrame(ordered_records).to_csv(args.out_csv, index=False)

    print(f"html salvo em: {os.path.abspath(args.out_html)}")
    print(f"sequência salva em: {os.path.abspath(args.out_csv)}")

if __name__ == "__main__":
    main()
