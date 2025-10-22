# consolidate all the csv from data/bronze in a  parquet file 
import pathlib, duckdb

root = pathlib.Path(__file__).resolve().parent.parent
src_glob = str(root / "data" / "bronze" / "orders_pt_*.csv")
silver = root / "data" / "silver"
silver.mkdir(parents=True, exist_ok=True)

con = duckdb.connect(database=":memory:")



df = con.execute(f"""
    select *
    from read_csv_auto('{src_glob}', header=true, filename=true)  
    order by scheduled_date, order_id
""").df()

(df
 .to_parquet(silver / "orders_all.parquet", index=False))
df.to_csv(silver / "orders_all.csv", index=False)

print("ok:", len(df), "rows →", silver / "orders_all.parquet")
