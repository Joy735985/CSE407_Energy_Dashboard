# main.py — Tuya plug dashboard with graphs (hosting-friendly)

from flask import Flask, render_template_string, jsonify
from tuya_connector import TuyaOpenAPI
import json
import threading
import time
import datetime
import csv
import os

# ---------- Tuya Cloud config (use ENV VARS in deployment!) ----------
ACCESS_ID = os.environ.get("TUYA_ACCESS_ID", "YOUR_LOCAL_TEST_ACCESS_ID")
ACCESS_KEY = os.environ.get("TUYA_ACCESS_KEY", "YOUR_LOCAL_TEST_ACCESS_KEY")
API_ENDPOINT = os.environ.get("TUYA_API_ENDPOINT", "https://openapi.tuyaeu.com")
DEVICE_ID = os.environ.get("TUYA_DEVICE_ID", "YOUR_LOCAL_TEST_DEVICE_ID")

POLL_INTERVAL_SECONDS = 30  # Poll every 30 seconds

# ---------- Flask Setup ----------
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Tuya Plug Dashboard</title>
  <style>
    body { font-family: Arial, sans-serif; padding: 20px; background: #f3f3f3; }
    .card {
      padding: 20px;
      background: #fff;
      border-radius: 8px;
      max-width: 900px;
      margin: 20px auto;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    pre { background:#eee; padding:10px; border-radius:6px; overflow-x:auto; }
    canvas { width: 100%; max-height: 300px; }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>

  <div class="card">
    <h2>Tuya Plug Status</h2>

    {% if error %}
      <p style="color:red;">Error: {{ error }}</p>
    {% else %}
      <p><b>Switch:</b> {{ switch }}</p>
      <p><b>Power:</b> {{ power }} W</p>
    {% endif %}
  </div>

  <div class="card">
    <h3>Power (W)</h3>
    <canvas id="powerChart"></canvas>
  </div>

  <div class="card">
    <h3>Voltage (V)</h3>
    <canvas id="voltageChart"></canvas>
  </div>

  <div class="card">
    <h3>Current (mA)</h3>
    <canvas id="currentChart"></canvas>
  </div>

  <div class="card">
    <h3>Raw Values (Latest)</h3>
    <pre>{{ latest_values }}</pre>
  </div>

<script>
  const initialHistory = {{ history|tojson | safe }};

  function splitHistory(data) {
    return {
      labels: data.map(d => d.time),
      power: data.map(d => d.power),
      voltage: data.map(d => d.voltage),
      current: data.map(d => d.current)
    };
  }

  const ctxPower = document.getElementById('powerChart').getContext('2d');
  const ctxVoltage = document.getElementById('voltageChart').getContext('2d');
  const ctxCurrent = document.getElementById('currentChart').getContext('2d');

  const s = splitHistory(initialHistory);

  const powerChart = new Chart(ctxPower, {
    type: 'line',
    data: { labels: s.labels, datasets: [{ label: 'Power (W)', data: s.power, borderWidth: 2 }] }
  });

  const voltageChart = new Chart(ctxVoltage, {
    type: 'line',
    data: { labels: s.labels, datasets: [{ label: 'Voltage (V)', data: s.voltage, borderWidth: 2 }] }
  });

  const currentChart = new Chart(ctxCurrent, {
    type: 'line',
    data: { labels: s.labels, datasets: [{ label: 'Current (mA)', data: s.current, borderWidth: 2 }] }
  });

  async function refreshData() {
    const res = await fetch("/data");
    const json = await res.json();
    const d = splitHistory(json);

    powerChart.data.labels = d.labels;
    powerChart.data.datasets[0].data = d.power;
    powerChart.update();

    voltageChart.data.labels = d.labels;
    voltageChart.data.datasets[0].data = d.voltage;
    voltageChart.update();

    currentChart.data.labels = d.labels;
    currentChart.data.datasets[0].data = d.current;
    currentChart.update();
  }

  setInterval(refreshData, 30000); // refresh every 30 sec
</script>

</body>
</html>
"""

# ---------- Tuya API ----------
openapi = TuyaOpenAPI(API_ENDPOINT, ACCESS_ID, ACCESS_KEY)
openapi.connect()

history = []
HISTORY_LIMIT = 200
CSV_FILE = "tuya_data.csv"

# guard variable so we don't start multiple threads
_poll_thread_started = False
_poll_lock = threading.Lock()


def append_to_csv(point):
    write_header = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "power", "voltage", "current"])
        if write_header:
            writer.writeheader()
        writer.writerow(point)


def read_status():
    resp = openapi.get(f"/v1.0/devices/{DEVICE_ID}/status")
    if not resp.get("success"):
        raise RuntimeError(resp.get("msg", "API failed"))

    switch = "Unknown"
    power = 0.0
    voltage = 0.0
    current = 0.0

    for item in resp["result"]:
        code = item["code"]
        value = item["value"]

        if code in ("switch", "switch_1"):
            switch = "ON" if value else "OFF"
        elif code in ("cur_power", "power"):
            power = float(value)
            if power > 10000:
                power /= 10
        elif code == "cur_voltage":
            voltage = value / 10.0
        elif code == "cur_current":
            current = float(value)

    return resp, switch, round(power, 2), voltage, current


def poll_loop():
    while True:
        try:
            resp, switch, power, voltage, current = read_status()
            t = datetime.datetime.now().strftime("%H:%M:%S")

            point = {"time": t, "power": power, "voltage": voltage, "current": current}

            history.append(point)
            if len(history) > HISTORY_LIMIT:
                history.pop(0)

            append_to_csv(point)
            print("Logged:", point)

        except Exception as e:
            print("Error:", e)

        time.sleep(POLL_INTERVAL_SECONDS)


def ensure_poll_thread():
    global _poll_thread_started
    with _poll_lock:
        if not _poll_thread_started:
            t = threading.Thread(target=poll_loop, daemon=True)
            t.start()
            _poll_thread_started = True
            print("Background poll thread started.")


@app.route("/")
def home():
    # start background polling on first request (works with gunicorn)
    ensure_poll_thread()

    error = None
    latest_values = "{}"
    switch = "-"
    power = "-"

    try:
        resp, switch, power, voltage, current = read_status()
        latest_values = json.dumps(
            {"switch": switch, "power": power, "voltage": voltage, "current": current},
            indent=2
        )
    except Exception as e:
        error = str(e)

    if not history:
        now = datetime.datetime.now().strftime("%H:%M:%S")
        history.append({"time": now, "power": 0, "voltage": 0, "current": 0})

    return render_template_string(
        HTML,
        error=error,
        switch=switch,
        power=power,
        history=history,
        latest_values=latest_values
    )


@app.route("/data")
@app.route("/data")
def data():
    return jsonify(history)


# ---------- Background polling (runs on both local & Render) ----------
polling_started = False

def start_polling():
    global polling_started
    if not polling_started:
        threading.Thread(target=poll_loop, daemon=True).start()
        polling_started = True
        print("Background Tuya polling started")


# start polling thread as soon as module is imported
start_polling()

if __name__ == "__main__":
    print("Server running → http://127.0.0.1:5000")
    app.run(debug=True)

