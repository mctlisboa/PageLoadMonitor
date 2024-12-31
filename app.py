import os
import time
import threading
from datetime import datetime, timedelta
import schedule
import pycurl
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # For servers without a GUI
import matplotlib.pyplot as plt

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    Response
)
from io import BytesIO

# -------------------------------------------------------------------------
# 1) GLOBAL CONFIG
# -------------------------------------------------------------------------
app = Flask(__name__)

# Default list of sites
MONITORED_SITES = [
    "https://lex.ao"
]

# Global measurement interval (in minutes)
MEASURE_INTERVAL_MINUTES = int(os.getenv("MEASURE_INTERVAL_MINUTES", "10"))
TIMEZONE = os.getenv("TZ", "UTC")

CSV_FILE = "load_time_log.csv"

# Set system timezone (if supported)
os.environ['TZ'] = TIMEZONE
time.tzset()

# -------------------------------------------------------------------------
# 2) ENSURE CSV EXISTS
# -------------------------------------------------------------------------
def ensure_csv_exists(filename):
    """Create CSV with a header if it doesn't already exist."""
    if not os.path.isfile(filename):
        with open(filename, "w") as f:
            header = "timestamp,site,connection_ms,latency_ms,response_ms,page_load_ms\n"
            f.write(header)

ensure_csv_exists(CSV_FILE)

# -------------------------------------------------------------------------
# 3) PYCURL MEASUREMENT
# -------------------------------------------------------------------------
def measure_site_metrics(url):
    """
    Use pycurl to measure:
      - connection_ms (TCP connect)
      - latency_ms    (TTFB)
      - response_ms   (time from TTFB to finish)
      - page_load_ms  (total request time)
    Return a dict with times in ms, or -1 if error.
    """
    c = pycurl.Curl()
    c.setopt(c.URL, url.encode("utf-8"))
    c.setopt(c.CONNECTTIMEOUT, 30)
    c.setopt(c.TIMEOUT, 60)
    c.setopt(c.NOPROGRESS, 1)

    buf = BytesIO()
    c.setopt(c.WRITEDATA, buf)

    try:
        c.perform()
        total_time = c.getinfo(pycurl.TOTAL_TIME)         # total time
        connect_time = c.getinfo(pycurl.CONNECT_TIME)     # TCP handshake done
        starttransfer_time = c.getinfo(pycurl.STARTTRANSFER_TIME)  # TTFB

        # Convert all to ms
        connection_ms = connect_time * 1000
        latency_ms = starttransfer_time * 1000
        page_load_ms = total_time * 1000
        response_ms = (total_time - starttransfer_time) * 1000

        c.close()
        return {
            "connection_ms": connection_ms,
            "latency_ms": latency_ms,
            "response_ms": response_ms,
            "page_load_ms": page_load_ms
        }
    except pycurl.error:
        c.close()
        return {
            "connection_ms": -1,
            "latency_ms": -1,
            "response_ms": -1,
            "page_load_ms": -1
        }

def measure_load_time(site):
    """Measure the site metrics and append to CSV with timestamp."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metrics = measure_site_metrics(site)

    if metrics["page_load_ms"] >= 0:
        print(f"[{now_str}] {site} => PageLoad: {metrics['page_load_ms']:.2f} ms")
    else:
        print(f"[{now_str}] {site} => Error measuring metrics.")

    with open(CSV_FILE, "a") as f:
        row = (
            f"{now_str},{site},"
            f"{metrics['connection_ms']:.2f},"
            f"{metrics['latency_ms']:.2f},"
            f"{metrics['response_ms']:.2f},"
            f"{metrics['page_load_ms']:.2f}\n"
        )
        f.write(row)

def measure_all_sites():
    """Measure for all monitored sites."""
    for site in MONITORED_SITES:
        measure_load_time(site)

# -------------------------------------------------------------------------
# 4) SCHEDULING
# -------------------------------------------------------------------------
def apply_schedule():
    """Clear existing tasks, schedule measure_all_sites with the current interval."""
    schedule.clear()
    schedule.every(MEASURE_INTERVAL_MINUTES).minutes.do(measure_all_sites)

def schedule_loop():
    """Run scheduled tasks in a background thread."""
    apply_schedule()
    while True:
        schedule.run_pending()
        time.sleep(1)

def start_background_thread():
    """Start background thread: measure once + scheduling loop."""
    measure_all_sites()  # immediate measurement on startup
    t = threading.Thread(target=schedule_loop, daemon=True)
    t.start()

# -------------------------------------------------------------------------
# 5) DATA ACCESS & BLOCK ANALYSIS
# -------------------------------------------------------------------------
def read_data(last_n_days=3):
    """Read CSV into a DataFrame, only the last N days."""
    if not os.path.isfile(CSV_FILE):
        cols = ["timestamp","site","connection_ms","latency_ms","response_ms","page_load_ms"]
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(CSV_FILE)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df.dropna(subset=["timestamp"], inplace=True)
    cutoff = datetime.now() - timedelta(days=last_n_days)
    df = df[df["timestamp"] >= cutoff]
    return df

def get_min_max_15min_blocks_past_24h(df):
    """
    For each site, find the 15-min block with the lowest average page_load_ms
    and the block with the highest average page_load_ms, over the last 24 hours.
    Returns a dict: { site: (lowest_block_dt, highest_block_dt) }
    """
    results = {}
    if df.empty:
        return results

    # Filter to last 24 hours
    cutoff = datetime.now() - timedelta(hours=24)
    df_24 = df[df["timestamp"] >= cutoff].copy()

    # Exclude errors
    df_24 = df_24[df_24["page_load_ms"] >= 0]
    if df_24.empty:
        return results

    # Floor timestamps to 15-minute intervals
    df_24["block15"] = df_24["timestamp"].dt.floor("15T")

    # Group by (site, block15), compute average page_load_ms
    grouped = df_24.groupby(["site", "block15"])["page_load_ms"].mean().reset_index()

    # For each site, find the block with min average and max average
    for site in grouped["site"].unique():
        sub = grouped[grouped["site"] == site]
        if sub.empty:
            results[site] = (None, None)
            continue

        row_min = sub.loc[sub["page_load_ms"].idxmin()]
        row_max = sub.loc[sub["page_load_ms"].idxmax()]
        results[site] = (row_min["block15"], row_max["block15"])

    return results

# -------------------------------------------------------------------------
# 6) FLASK ROUTES
# -------------------------------------------------------------------------
@app.route("/")
def index():
    """
    Main dashboard:
      - form to set measurement interval
      - form to add site
      - cards for each site, including 15-min block stats
    """
    df = read_data()
    block_results = get_min_max_15min_blocks_past_24h(df)

    def format_block(dtblock):
        return dtblock.strftime("%Y-%m-%d %H:%M") if dtblock else "N/A"

    # Build a dictionary: { site: { 'low_str': ..., 'high_str': ... } }
    block_stats = {}
    for site in MONITORED_SITES:
        if site in block_results:
            low_dt, high_dt = block_results[site]
            block_stats[site] = {
                "lowest": format_block(low_dt),
                "highest": format_block(high_dt)
            }
        else:
            block_stats[site] = {
                "lowest": "N/A",
                "highest": "N/A"
            }

    return render_template(
        "index.html",
        sites=MONITORED_SITES,
        measure_interval=MEASURE_INTERVAL_MINUTES,
        timezone=TIMEZONE,
        block_stats=block_stats
    )

@app.route("/chart_data/<path:site>")
def chart_data(site):
    """
    Return JSON with multiple arrays for Chart.js:
      {
        labels: [...],
        connection: [...],
        latency: [...],
        response: [...],
        page_load: [...]
      }
    """
    df = read_data()
    df = df[df["site"] == site].sort_values("timestamp")

    labels = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
    connection_vals = df["connection_ms"].tolist()
    latency_vals = df["latency_ms"].tolist()
    response_vals = df["response_ms"].tolist()
    page_load_vals = df["page_load_ms"].tolist()

    return jsonify({
        "labels": labels,
        "connection": connection_vals,
        "latency": latency_vals,
        "response": response_vals,
        "page_load": page_load_vals
    })

@app.route("/download_csv")
def download_csv():
    """Download the entire CSV."""
    if not os.path.isfile(CSV_FILE):
        return Response(
            "timestamp,site,connection_ms,latency_ms,response_ms,page_load_ms\n",
            mimetype="text/csv"
        )
    with open(CSV_FILE, "r") as f:
        csv_data = f.read()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=load_time_log.csv"}
    )

@app.route("/add_site", methods=["POST"])
def add_site():
    """Add a new site, measure it immediately."""
    new_site = request.form.get("site_url", "").strip()
    if new_site and new_site not in MONITORED_SITES:
        MONITORED_SITES.append(new_site)
        measure_load_time(new_site)
    return redirect(url_for("index"))

@app.route("/remove_site/<path:site>")
def remove_site(site):
    """Remove site from the list."""
    if site in MONITORED_SITES:
        MONITORED_SITES.remove(site)
    return redirect(url_for("index"))

@app.route("/set_interval", methods=["POST"])
def set_interval():
    """
    Change the global measurement interval (in minutes).
    Re-apply the schedule with the new interval.
    """
    global MEASURE_INTERVAL_MINUTES
    try:
        new_val = int(request.form.get("interval", "10"))
        MEASURE_INTERVAL_MINUTES = max(1, new_val)
    except ValueError:
        MEASURE_INTERVAL_MINUTES = 10

    apply_schedule()
    return redirect(url_for("index"))

# -------------------------------------------------------------------------
# 7) MAIN
# -------------------------------------------------------------------------
if __name__ == "__main__":
    start_background_thread()
    print("Starting Flask on port 5000.")
    app.run(host="0.0.0.0", port=5000)
