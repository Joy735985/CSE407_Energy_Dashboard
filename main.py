# main.py — CSE407 Tuya IoT Energy Monitoring Dashboard

from flask import Flask, render_template_string, jsonify
from tuya_connector import TuyaOpenAPI
import json
import threading
import time
import datetime
import csv
import os

# ---------- Tuya Cloud config ----------
# Prefer environment variables (Render), fall back to hardcoded values for local testing
ACCESS_ID = os.getenv("TUYA_ACCESS_ID", "jypequ8ckprw8gdfc3nh")
ACCESS_KEY = os.getenv("TUYA_ACCESS_KEY", "f3abd2b176674a60a18d58b0c0f1d95e")
API_ENDPOINT = os.getenv("TUYA_API_ENDPOINT", "https://openapi.tuyaeu.com")
DEVICE_ID = os.getenv("TUYA_DEVICE_ID", "bf7cb729c67a2b6c6e7jgd")

POLL_INTERVAL_SECONDS = 30       # Poll every 30 seconds
COST_PER_KWH = 8.84              # BDT per kWh

# ---------- Flask Setup ----------
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>CSE407 IoT Energy Dashboard</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      padding: 20px;
      margin: 0;
      background: #f3f4f8;
    }
    .container {
      max-width: 1150px;
      margin: 0 auto 40px auto;
    }
    .card {
      padding: 20px;
      background: #fff;
      border-radius: 12px;
      margin: 15px 0;
      box-shadow: 0 2px 14px rgba(0,0,0,0.06);
    }
    .card h2, .card h3 {
      margin: 0 0 12px 0;
      font-weight: 600;
      color: #111827;
    }
    .subheading {
      margin: 0;
      color: #6b7280;
      font-size: 13px;
    }
    .status-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }
    .status-item {
      background: #f7f9fc;
      border-radius: 10px;
      padding: 10px 12px;
      border: 1px solid #e5e7eb;
    }
    .status-label {
      font-size: 11px;
      color: #6b7280;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .status-value {
      font-size: 18px;
      font-weight: 600;
      margin-top: 4px;
      color: #111827;
    }
    .switch-on { color: #059669; }
    .switch-off { color: #dc2626; }

    .charts-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 15px;
    }
    .chart-card {
      padding: 16px 18px 18px 18px;
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.04);
    }
    .chart-card h3 {
      margin-bottom: 8px;
      font-size: 15px;
    }
    canvas {
      width: 100%;
      max-height: 260px;
    }
    pre {
      background:#111827;
      color:#e5e7eb;
      padding:10px 12px;
      border-radius:8px;
      overflow-x:auto;
      font-size: 12px;
    }
    .footer-note {
      font-size: 11px;
      color: #9ca3af;
      margin-top: 4px;
    }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
<div class="container">

  <div class="card">
    <h2>CSE407 IoT Energy Monitoring Dashboard</h2>
    <p class="subheading">
      Live data from Tuya Cloud (updated every {{ poll_interval }} seconds)
    </p>
    {% if error %}
      <p style="color:#b91c1c; margin-top:8px;">Error: {{ error }}</p>
    {% endif %}

    <div class="status-grid">
      <div class="status-item">
        <div class="status-label">Switch</div>
        <div class="status-value {{ 'switch-on' if switch == 'ON' else 'switch-off' }}">{{ switch }}</div>
      </div>
      <div class="status-item">
        <div class="status-label">Power</div>
        <div class="status-value">{{ power }} W</div>
      </div>
      <div class="status-item">
        <div class="status-label">Voltage</div>
        <div class="status-value">{{ voltage }} V</div>
      </div>
      <div class="status-item">
        <div class="status-label">Current</div>
        <div class="status-value">{{ current }} mA</div>
      </div>
      <div class="status-item">
        <div class="status-label">Energy Today</div>
        <div class="status-value">{{ energy_kwh_today }} kWh</div>
      </div>
      <div class="status-item">
        <div class="status-label">Cost Today</div>
        <div class="status-value">{{ cost_today }} BDT</div>
      </div>
    </div>
  </div>

  <div class="charts-grid">
    <div class="chart-card">
      <h3>Power (W)</h3>
      <canvas id="powerChart"></canvas>
    </div>
    <div class="chart-card">
      <h3>Voltage (V)</h3>
      <canvas id="voltageChart"></canvas>
    </div>
    <div class="chart-card">
      <h3>Current (mA)</h3>
      <canvas id="currentChart"></canvas>
    </div>
    <div class="chart-card">
      <h3>Energy Today (kWh)</h3>
      <canvas id="energyChart"></canvas>
    </div>
    <div class="chart-card">
      <h3>Cost Today (BDT)</h3>
      <canvas id="costChart"></canvas>
    </div>
  </div>

  <div class="card">
    <h3>Raw Values (Latest)</h3>
    <pre>{{ latest_values }}</pre>
    <div class="footer-note">
      Data source: Tuya Cloud API • Logged to tuya_data.csv (time, power, voltage, current, energy_kwh_today, cost_today)
    </div>
  </div>

</div>

<script>
  const initialHistory = {{ history|tojson | safe }};

  function splitHistory(data) {
    return {
      labels: data.map(d => d.time),
      power: data.map(d => d.power),
      voltage: data.map(d => d.voltage),
      current: data.map(d => d.current),
      energy: data.map(d => d.energy_kwh_today),
      cost: data.map(d => d.cost_today)
    };
  }

  const ctxPower  = document.getElementById('powerChart').getContext('2d');
  const ctxVolt   = document.getElementById('voltageChart').getContext('2d');
  const ctxCurr   = document.getElementById('currentChart').getContext('2d');
  const ctxEnergy = document.getElementById('energyChart').getContext('2d');
  const ctxCost   = document.getElementById('costChart').getContext('2d');

  const s = splitHistory(initialHistory);

  function makeLineChart(ctx, label, dataArr) {
    return new Chart(ctx, {
      type: 'line',
      data: {
        labels: s.labels,
        datasets: [{
          label: label,
          data: dataArr,
          borderWidth: 2,
          fill: false,
          tension: 0.2,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true }
        },
        scales: {
          x: {
            ticks: { maxTicksLimit: 6 }
          }
        }
      }
    });
  }

  const powerChart  = makeLineChart(ctxPower,  'Power (W)',          s.power);
  const voltageChart= makeLineChart(ctxVolt,   'Voltage (V)',        s.voltage);
  const currentChart= makeLineChart(ctxCurr,   'Current (mA)',       s.current);
  const energyChart = makeLineChart(ctxEnergy, 'Energy Today (kWh)', s.energy);
  const costChart   = makeLineChart(ctxCost,   'Cost Today (BDT)',   s.cost);

  async function refreshData() {
    try {
      const res = await fetch("/data");
      const json = await res.json();
      const d = splitHistory(json);

      powerChart.data.labels   = d.labels;
      voltageChart.data.labels = d.labels;
      currentChart.data.labels = d.labels;
      energyChart.data.labels  = d.labels;
      costChart.data.labels    = d.labels;

      powerChart.data.datasets[0].data   = d.power;
      voltageChart.data.datasets[0].data = d.voltage;
      currentChart.data.datasets[0].data = d.current;
      energyChart.data.datasets[0].data  = d.energy;
      costChart.data.datasets[0].data    = d.cost;

      powerChart.update();
      voltageChart.update();
      currentChart.update();
      energyChart.update();
      costChart.update();
    } catch (e) {
      console.error("Failed to refresh charts:", e);
    }
  }

  // refresh every poll interval
  setInterval(refreshData, {{ poll_interval }} * 1000);
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

# Energy & cost tracking
energy_kwh_today = 0.0
cost_today = 0.0
last_poll_time = None
current_day = datetime.date.today()


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
    """Read current status from Tuya Cloud."""
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
            # Some Tuya plugs report power *10
            if power > 10000:
                power /= 10
        elif code == "cur_voltage":
            voltage = value / 10.0
        elif code == "cur_current":
            current = float(value)

    return resp, switch, round(power, 2), round(voltage, 1), round(current, 1)


def poll_loop():
    """Background loop: poll Tuya, update history, compute energy & cost."""
    global energy_kwh_today, cost_today, last_poll_time, current_day

    while True:
        try:
            now = datetime.datetime.now()

            # Reset counters at midnight
            if now.date() != current_day:
                current_day = now.date()
                energy_kwh_today = 0.0
                cost_today = 0.0
                last_poll_time = None

            resp, switch, power, voltage, current = read_status()

            # Time delta since last poll
            if last_poll_time is None:
                dt_seconds = POLL_INTERVAL_SECONDS
            else:
                dt_seconds = (now - last_poll_time).total_seconds()
                if dt_seconds <= 0:
                    dt_seconds = POLL_INTERVAL_SECONDS

            last_poll_time = now

            # Energy increment:
            #   energy (kWh) = P(W) * t(hours) / 1000
            dt_hours = dt_seconds / 3600.0
            energy_kwh_today += (power * dt_hours) / 1000.0
            cost_today = energy_kwh_today * COST_PER_KWH

            t_label = now.strftime("%H:%M:%S")

            point = {
                "time": t_label,
                "power": power,
                "voltage": voltage,
                "current": current,
                "energy_kwh_today": round(energy_kwh_today, 4),
                "cost_today": round(cost_today, 2),
            }

            history.append(point)
            if len(history) > HISTORY_LIMIT:
                history.pop(0)

            append_to_csv(point)
            print("Logged:", point)

        except Exception as e:
            print("Error in poll_loop:", e)

        time.sleep(POLL_INTERVAL_SECONDS)


@app.route("/")
def home():
    global energy_kwh_today, cost_today

    error = None
    latest_values = "{}"
    switch = "-"
    power = "-"
    voltage = "-"
    current = "-"

    try:
        resp, switch, power, voltage, current = read_status()
        latest_values = json.dumps(
            {
                "switch": switch,
                "power": power,
                "voltage": voltage,
                "current": current,
                "energy_kwh_today": round(energy_kwh_today, 4),
                "cost_today": round(cost_today, 2),
            },
            indent=2,
        )
    except Exception as e:
        error = str(e)

    if not history:
        now = datetime.datetime.now().strftime("%H:%M:%S")
        history.append(
            {
                "time": now,
                "power": 0,
                "voltage": 0,
                "current": 0,
                "energy_kwh_today": 0,
                "cost_today": 0,
            }
        )

    return render_template_string(
        HTML,
        error=error,
        switch=switch,
        power=power,
        voltage=voltage,
        current=current,
        energy_kwh_today=round(energy_kwh_today, 4),
        cost_today=round(cost_today, 2),
        history=history,
        latest_values=latest_values,
        poll_interval=POLL_INTERVAL_SECONDS,
    )


@app.route("/data")
def data():
    return jsonify(history)


# ---------- Background polling (works on Render & local) ----------
polling_started = False


def start_polling():
    global polling_started
    if not polling_started:
        threading.Thread(target=poll_loop, daemon=True).start()
        polling_started = True
        print("Background Tuya polling started")


# Start polling thread as soon as module is imported (gunicorn & local)
start_polling()

if __name__ == "__main__":
    print("Server running → http://127.0.0.1:5000")
    app.run(debug=True)
