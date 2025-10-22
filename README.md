# **Geo-Logistic**

**geologistic** is a simple project for generating and consolidating synthetic logistics delivery data in portugal.  
it simulates daily orders for a logistics company and organizes them into structured data layers.

---


## ⚙️ installation and setup

1. **install python 3.12 or later**

- windows: download from [python.org/downloads](https://www.python.org/downloads/)
- check version:
    ```bash
    python --version
    ```

2. **create and activate a virtual environment**

   ```bash
   python -m venv .venv
   # windows
   .\.venv\Scripts\activate
   # mac/linux
   source .venv/bin/activate

3. **install dependencies**
    ```bash
    pip install -r requirements.txt
    ```


## 🏃 how to run 


1. **generate orders for a date range**

- creates one .csv file per day within the defined start and end dates in the script.

     ```bash
     python src/create_orders_per_period.py
     ```

2. **generate orders only for the current day**


- creates a single .csv file containing today’s orders.

     ```bash
     python src/create_orders_today.py
     ```

3. **consolidate all daily files - Optional**

- merges all generated .csv files into one .parquet and .csv file inside the silver layer.

     ```bash
     python src/consolidate_duckdb.py
     ```

4. **the output**

- The output of the generate orders (per period and per today) will be save in data/bronze/

     ```
     orders_pt_YYYY-MM-DD.csv
     warehouse_pt.csv
     ```

- The optional output of the consolidate orders will be saved in data/silver/ :

     ```
     orders_all.parquet
     orders_all.csv
     ```

4. **generate and publish optimized routes**

- Each day can be transformed into an interactive html map using osrm + folium.
- Run the script that calculates the best route for a given date (used internally by the render process):

    ```bash
    python src/calculate_best_route.py 
    ```

- This script uses the files:
   - data/bronze/orders_pt_2025-10-12.csv 
   - data/bronze/warehouse_pt.csv
  
- Contacts the free osrm api
- Computes an optimal traveling salesman route 
- Produces a folium html map and saves both the html and the optimized sequence for that day and 
- Generate the files: 
    - site/2025-10-12/index.html
    - site/2025-10-12/optimized_sequence.csv


5. **render daily pages automatically**

- To automate rendering, use the helpers under src/render/:

    - build_day.py → generates the html and csv for one date
    - build_index.py → builds a homepage with a date picker and list of available dates

    ```bash
    python src/render/build_day.py --date 2025-10-12
    python src/render/build_index.py
    ```

6. **preview locally**

 - serve the generated site locally to view the pages:

    ```bash
    python -m http.server --directory site 8010
    ```

- in your browser open http://localhost:8010/  to check the route 