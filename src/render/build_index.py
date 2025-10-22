import pathlib, re

root = pathlib.Path(__file__).resolve().parents[2]
bronze = root / "data" / "bronze"
site = root / "site"

def list_dates():
    pat = re.compile(r"orders_pt_(\d{4}-\d{2}-\d{2})\.csv$")
    dates = []
    for p in bronze.glob("orders_pt_*.csv"):
        m = pat.search(p.name)
        if m: dates.append(m.group(1))
    return sorted(set(dates))

def build_index():
    dates = list_dates()
    site.mkdir(parents=True, exist_ok=True)
    out = site / "index.html"

    # html minimalista com datepicker e lista
    min_date = dates[0] if dates else ""
    max_date = dates[-1] if dates else ""
    items = "\n".join(f'<li><a href="{d}/index.html">{d}</a></li>' for d in reversed(dates))
    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>geologistic – daily routes</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:900px;margin:1rem auto;padding:0 1rem}}
 .muted{{color:#666}}
</style>
</head><body>
<h1>geologistic – daily routes</h1>
<p class="muted">pick a date or click one of the recent pages.</p>
<label for="pick">date:</label>
<input id="pick" type="date" min="{min_date}" max="{max_date}">
<ul>
{items}
</ul>
<script>
 const i=document.getElementById('pick');
 i.addEventListener('change',()=>{{ if(i.value) location.href=`${{i.value}}/index.html`; }});
</script>
</body></html>"""
    out.write_text(html, encoding="utf-8")
    print("index written:", out)

if __name__ == "__main__":
    build_index()
