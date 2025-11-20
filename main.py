# main.py — CSE407 Tuya IoT Energy Monitoring Dashboard (stylish wide charts)

from flask import Flask, render_template_string, jsonify
from tuya_connector import TuyaOpenAPI
import json
import time
import datetime
import csv
import os

# ---------- Tuya Cloud config ----------
# Use environment variables on Render, fall back to local values if needed
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
  <title>CSE407 IoT Energy Monitoring Dashboard</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      padding: 20px;
      margin: 0;
      background: #eef2f7;
    }
    .container {
      max-width: 1200px;
      margin: 0 auto 40px auto;
    }
    .card {
      padding: 20px;
      background: #ffffff;
      border-radius: 14px;
      margin: 15px 0;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
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
      background: #f9fafb;
      border-radius: 12px;
      padding: 12px 14px;
      border: 1px solid #e5e7eb;
      box-shadow: 0 3px 8px rgba(148, 163, 184, 0.25);
    }
    .status-label {
      font-size: 11px;
      color: #6b7280;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .status-value {
      font-size: 19px;
      font-weight: 600;
      margin-top: 5px;
      color: #111827;
    }
    .switch-on { color: #059669; }
    .switch-off { color: #dc2626; }

    /* Wide stacked charts */
    .chart-card-wrapper {
      display: flex;
      flex-direction: column;
      gap: 18px;
      margin-top: 10px;
    }
    .chart-card {
      width: 80%;
      margin: 0 auto;
      padding: 18px 20px 20px 20px;
      border-radius: 16px;
      background: linear-gradient(135deg, #e0f2fe 0%, #eef2ff 50%, #fefce8 100%);
      border: 1px solid rgba(148, 163, 184, 0.6);
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.25);
    }
    .chart-card h3 {
      margin-bottom: 10px;
      font-size: 16px;
      color: #0f172a;
    }
    .chart-inner {
      background: #ffffff;
      border-radius: 12px;
      padding: 14px 14px 12px 14px;
      box-shadow: inset 0 0 0 1px #e5e7eb;
    }
    canvas {
      width: 100%;
      max-height: 340px;
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

  <div class="chart-card-wrapper">
    <div class="chart-card">
      <h3>Power (W)</h3>
      <div class="chart-inner">
        <canvas id="powerChart"></canvas>
      </div>
    </div>

    <div class="chart-card">
      <h3>Voltage (V)</h3>
      <div class="chart-inner">
        <canvas id="voltageChart"></canvas>
      </div>
    </div>

    <div class="chart-card">
      <h3>Current (mA)</h3>
      <div class="chart-inner">
        <canvas id="currentChart"></canvas>
      </div>
    </div>

    <div class="chart-card">
      <h3>Energy Today (kWh)</h3>
      <div class="chart-inner">
        <canvas id="energyChart"></canvas>
      </div>
    </div>

    <div class="chart-card">
      <h3>Cost Today (BDT)</h3>
      <div class="chart-inner">
        <canvas id="costChart"></canvas>
      </div>
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

  function makeLineChart(ctx, label, dataArr, color) {
    return new Chart(ctx, {
      type: 'line',
      data: {
        labels: s.labels,
        datasets: [{
          label: label,
          data: dataArr,
          borderWidth: 2.5,
          fill: true,
          tension: 0.28,
          borderColor: color,
          backgroundColor: color + '33', // transparent fill
          pointRadius: 3,
          pointHoverRadius: 5,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: true
          }
        },
        scales: {
          x: {
            ticks: { maxTicksLimit: 8 }
          },
          y: {
            beginAtZero: false
          }
        }
      }
    });
  }

  const powerChart   = makeLineChart(ctxPower,  'Power (W)',          s.power,  '#3b82f6'); // blue
  const voltageChart = makeLineChart(ctxVolt,   'Voltage (V)',        s.voltage,'#f97316'); // orange
  const currentChart = makeLineChart(ctxCurr,   'Current (mA)',       s.current,'#22c55e'); // green
  const energyChart  = makeLineChart(ctxEnergy, 'Energy Today (kWh)', s.energy, '#a855f7'); // purple
  const costChart    = makeLineChart(ctxCost,   'Cost Today (BDT)',   s.cost,   '#ec4899'); // pink

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
last_sample_time = None
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
            # some plugs report power *10
            if power > 10000:
                power /= 10
        elif code == "cur_voltage":
            voltage = value / 10.0
        elif code == "cur_current":
            current = float(value)

    return resp, switch, round(power, 2), round(voltage, 1), round(current, 1)


def sample_from_tuya():
    """
    Poll Tuya once, update energy & cost, append to history & CSV.
    Called from both home() and /data, so no background thread is needed.
    """
    global energy_kwh_today, cost_today, last_sample_time, current_day

    now = datetime.datetime.now()

    # Reset counters at midnight
    if now.date() != current_day:
        current_day = now.date()
        energy_kwh_today = 0.0
        cost_today = 0.0
        last_sample_time = None

    resp, switch, power, voltage, current = read_status()

    # Time delta since last sample
    if last_sample_time is None:
        dt_seconds = POLL_INTERVAL_SECONDS
    else:
        dt_seconds = (now - last_sample_time).total_seconds()
        if dt_seconds <= 0:
            dt_seconds = POLL_INTERVAL_SECONDS

    last_sample_time = now

    # Energy increment (kWh) = P(W) * t(h) / 1000
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

    return switch, power, voltage, current


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
        # Take one fresh sample when page loads
        switch, power, voltage, current = sample_from_tuya()
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
    """
    Called every 30 seconds from the browser.
    Each call takes one new sample from Tuya and returns full history.
    """
    try:
        sample_from_tuya()
    except Exception as e:
        print("Error in /data polling:", e)
    return jsonify(history)


if __name__ == "__main__":
    print("Server running → http://127.0.0.1:5000")
    app.run(debug=True)
