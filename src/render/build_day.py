# publica um dia: lê data/bronze/orders_pt_yyyy-mm-dd.csv e warehouse_pt.csv,
# roda o calculate_best_route e salva em site/yyyy-mm-dd/{index.html, optimized_sequence.csv}

import pathlib, subprocess, sys

root = pathlib.Path(__file__).resolve().parents[2]
bronze = root / "data" / "bronze"
site = root / "site"

def build_day(date_iso: str, max_orders: int = 25):
    orders_csv = bronze / f"orders_pt_{date_iso}.csv"
    warehouse_csv = bronze / "warehouse_pt.csv"
    out_dir = site / date_iso
    out_html = out_dir / "index.html"                 # folium vira a página do dia
    out_csv  = out_dir / "optimized_sequence.csv"

    if not orders_csv.exists():
        raise FileNotFoundError(f"não existe: {orders_csv}")
    if not warehouse_csv.exists():
        raise FileNotFoundError(f"não existe: {warehouse_csv}")

    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(root / "src" / "calculate_best_route.py"),
        "--orders-csv", str(orders_csv),
        "--warehouse-csv", str(warehouse_csv),
        "--max-orders", str(max_orders),
        "--out-html", str(out_html),
        "--out-csv", str(out_csv),
        "--scheduled-date", date_iso,
    ]
    subprocess.check_call(cmd)
    print("ok:", date_iso, "→", out_dir)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="yyyy-mm-dd")
    ap.add_argument("--max-orders", type=int, default=25)
    args = ap.parse_args()
    build_day(args.date, args.max_orders)
