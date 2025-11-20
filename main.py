# main.py — Tuya plug dashboard with graphs + kWh + cost

from flask import Flask, render_template_string, jsonify
from tuya_connector import TuyaOpenAPI
import json
import threading
import time
import datetime
import csv
import os

# ---------- Tuya Cloud config ----------
ACCESS_ID = "uvmnkvagfjg73yjtuamc"
ACCESS_KEY = "ed83ebe9b00a4e31a7bed9a5307cafdd"
API_ENDPOINT = "https://openapi.tuyaeu.com"
DEVICE_ID = "bf7cb729c67a2b6c6e7jgd"

POLL_INTERVAL_SECONDS = 30  # Poll every 30 seconds
COST_PER_KWH = 8.84         # BDT per kWh (you can change this for your context)


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
      max-width: 1100px;
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
    <h2>CSE407 IoT Energy Monitoring Dashboard</h2>

    {% if error %}
      <p style="color:red;">Error: {{ error }}</p>
    {% else %}
      <p><b>Time:</b> {{ now }}</p>
      <p><b>Switch:</b> {{ switch }}</p>
      <p><b>Power:</b> {{ power }} W</p>
      <p><b>Voltage:</b> {{ voltage }} V</p>
      <p><b>Current:</b> {{ current }} mA</p>
      <p><b>Energy Today:</b> {{ energy_today }} kWh</p>
      <p><b>Cost Today:</b> {{ cost_today }} BDT</p>
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
    <h3>Energy Today (kWh) — Cumulative</h3>
    <canvas id="energyChart"></canvas>
  </div>

  <div class="card">
    <h3>Cost Today (BDT) — Cumulative</h3>
    <canvas id="costChart"></canvas>
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
      current: data.map(d => d.current),
      energy: data.map(d => d.energy_kwh_today || 0),
      cost: data.map(d => d.cost_today || 0)
    };
  }

  const ctxPower   = document.getElementById('powerChart').getContext('2d');
  const ctxVoltage = document.getElementById('voltageChart').getContext('2d');
  const ctxCurrent = document.getElementById('currentChart').getContext('2d');
  const ctxEnergy  = document.getElementById('energyChart').getContext('2d');
  const ctxCost    = document.getElementById('costChart').getContext('2d');

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

  const energyChart = new Chart(ctxEnergy, {
    type: 'line',
    data: { labels: s.labels, datasets: [{ label: 'Energy Today (kWh)', data: s.energy, borderWidth: 2 }] }
  });

  const costChart = new Chart(ctxCost, {
    type: 'line',
    data: { labels: s.labels, datasets: [{ label: 'Cost Today (BDT)', data: s.cost, borderWidth: 2 }] }
  });

  async function refreshData() {
    const res = await fetch("/data");
    const json = await res.json();
    const d = splitHistory(json);

    powerChart.data.labels   = d.labels;
    powerChart.data.datasets[0].data = d.power;
    powerChart.update();

    voltageChart.data.labels = d.labels;
    voltageChart.data.datasets[0].data = d.voltage;
    voltageChart.update();

    currentChart.data.labels = d.labels;
    currentChart.data.datasets[0].data = d.current;
    currentChart.update();

    energyChart.data.labels  = d.labels;
    energyChart.data.datasets[0].data = d.energy;
    energyChart.update();

    costChart.data.labels    = d.labels;
    costChart.data.datasets[0].data = d.cost;
    costChart.update();
  }

  // refresh every 30 sec (same as backend polling)
  setInterval(refreshData, 30000);
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

# daily cumulative energy & cost
daily_kwh = 0.0
daily_cost = 0.0
last_energy_date = datetime.date.today()


def append_to_csv(point):
    write_header = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "time",
                "power",
                "voltage",
                "current",
                "energy_kwh_today",
                "cost_today",
            ],
        )
        if write_header:
            writer.writeheader()
        writer.writerow(point)


def read_status():
    """Read raw status from Tuya and parse switch, power, voltage, current."""
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
                power /= 10.0
        elif code == "cur_voltage":
            voltage = value / 10.0
        elif code == "cur_current":
            current = float(value)

    return resp, switch, round(power, 2), voltage, current


def poll_loop():
    """Background loop: poll Tuya, update history, accumulate kWh & cost."""
    global daily_kwh, daily_cost, last_energy_date

    while True:
        try:
            # reset daily counters when date changes
            today = datetime.date.today()
            if today != last_energy_date:
                daily_kwh = 0.0
                daily_cost = 0.0
                last_energy_date = today

            resp, switch, power, voltage, current = read_status()
            t = datetime.datetime.now().strftime("%H:%M:%S")

            # power is in Watts → convert to kWh over POLL_INTERVAL_SECONDS
            energy_interval_kwh = (power / 1000.0) * (POLL_INTERVAL_SECONDS / 3600.0)
            daily_kwh += energy_interval_kwh
            daily_cost = daily_kwh * COST_PER_KWH

            point = {
                "time": t,
                "power": power,
                "voltage": voltage,
                "current": current,
                "energy_kwh_today": round(daily_kwh, 6),
                "cost_today": round(daily_cost, 4),
            }

            history.append(point)
            if len(history) > HISTORY_LIMIT:
                history.pop(0)

            append_to_csv(point)
            print("Logged:", point)

        except Exception as e:
            print("Error:", e)

        time.sleep(POLL_INTERVAL_SECONDS)


@app.route("/")
def home():
    global daily_kwh, daily_cost

    error = None
    latest_values = "{}"
    switch = "-"
    power = 0.0
    voltage = 0.0
    current = 0.0
    now_str = datetime.datetime.now().strftime("%H:%M:%S")

    try:
        resp, switch, power, voltage, current = read_status()
        latest_values = json.dumps(
            {
                "switch": switch,
                "power": power,
                "voltage": voltage,
                "current": current,
                "energy_today_kwh": round(daily_kwh, 6),
                "cost_today_bdt": round(daily_cost, 4),
            },
            indent=2,
        )
    except Exception as e:
        error = str(e)

    # if no history yet, seed a zero point so charts render
    if not history:
        history.append(
            {
                "time": now_str,
                "power": 0.0,
                "voltage": 0.0,
                "current": 0.0,
                "energy_kwh_today": 0.0,
                "cost_today": 0.0,
            }
        )

    return render_template_string(
        HTML,
        error=error,
        now=now_str,
        switch=switch,
        power=power,
        voltage=voltage,
        current=current,
        energy_today=round(daily_kwh, 4),
        cost_today=round(daily_cost, 3),
        history=history,
        latest_values=latest_values,
    )


@app.route("/data")
def data():
    return jsonify(history)


if __name__ == "__main__":
    threading.Thread(target=poll_loop, daemon=True).start()
    print("Server running → http://127.0.0.1:5000")
    app.run(debug=True)
