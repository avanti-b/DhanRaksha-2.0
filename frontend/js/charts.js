/**
 * Chart rendering. Every dataset passed in here comes from /api/v1/analytics —
 * there are no baked-in series anywhere in this file.
 */
const PALETTE = {
  bark: "#2C2016",
  gold: "#C8922A",
  sage: "#4A6741",
  rust: "#B84A2C",
  grid: "rgba(44,32,22,0.07)",
  tick: "#8A9E85",
};

const chartRegistry = {};

function baseOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { color: PALETTE.grid }, ticks: { font: { size: 10 }, color: PALETTE.tick } },
      y: {
        beginAtZero: true,
        grid: { color: PALETTE.grid },
        ticks: { font: { size: 10 }, color: PALETTE.tick, precision: 0 },
      },
    },
    ...extra,
  };
}

function upsertChart(key, canvasId, config) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  if (chartRegistry[key]) {
    chartRegistry[key].data = config.data;
    chartRegistry[key].update();
    return;
  }
  chartRegistry[key] = new Chart(canvas.getContext("2d"), config);
}

function renderHourChart(byHour) {
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const lookup = Object.fromEntries((byHour || []).map((row) => [row.hour, row]));
  upsertChart("hour", "hourChart", {
    type: "line",
    data: {
      labels: hours.map((h) => `${String(h).padStart(2, "0")}h`),
      datasets: [
        {
          label: "Scored",
          data: hours.map((h) => lookup[h]?.count || 0),
          borderColor: PALETTE.bark,
          backgroundColor: "rgba(44,32,22,0.06)",
          fill: true,
          tension: 0.35,
          pointRadius: 2,
        },
        {
          label: "Flagged fraud",
          data: hours.map((h) => lookup[h]?.fraud || 0),
          borderColor: PALETTE.rust,
          backgroundColor: "rgba(184,74,44,0.10)",
          fill: true,
          tension: 0.35,
          pointRadius: 2,
        },
      ],
    },
    options: baseOptions({ plugins: { legend: { display: true, labels: { font: { size: 10 } } } } }),
  });
}

function renderBandChart(bands) {
  const order = ["<10", "10-100", "100-500", "500-2000", "2000+"];
  const lookup = Object.fromEntries((bands || []).map((row) => [row.band, row]));
  upsertChart("band", "bandChart", {
    type: "bar",
    data: {
      labels: order,
      datasets: [
        {
          label: "Scored",
          data: order.map((band) => lookup[band]?.count || 0),
          backgroundColor: PALETTE.gold,
          borderRadius: 5,
        },
        {
          label: "Flagged fraud",
          data: order.map((band) => lookup[band]?.fraud || 0),
          backgroundColor: PALETTE.rust,
          borderRadius: 5,
        },
      ],
    },
    options: baseOptions({
      indexAxis: "y",
      plugins: { legend: { display: true, labels: { font: { size: 10 } } } },
    }),
  });
}

function renderRiskBars(distribution, total) {
  const colours = { HIGH: PALETTE.rust, MEDIUM: PALETTE.gold, LOW: PALETTE.sage };
  const container = document.getElementById("d-risk-bars");
  if (!container) return;

  if (!total) {
    container.innerHTML =
      '<div class="empty-state"><h4>Nothing scored yet</h4>' +
      "<p>Run a prediction and the distribution appears here.</p></div>";
    return;
  }

  container.innerHTML = ["HIGH", "MEDIUM", "LOW"]
    .map((level) => {
      const count = distribution[level] || 0;
      const percent = total ? (count / total) * 100 : 0;
      return `
        <div class="prog-wrap">
          <div class="prog-label"><span>${level}</span><span>${count} · ${percent.toFixed(1)}%</span></div>
          <div class="prog-bg"><div class="prog-fill" style="width:${percent}%;background:${colours[level]}"></div></div>
        </div>`;
    })
    .join("");
}
