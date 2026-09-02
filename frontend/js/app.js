/**
 * DhanRaksha 2.0 frontend controller.
 *
 * Every figure rendered here is fetched from the backend. Where the backend has
 * no data yet, the UI says so rather than showing a placeholder number.
 */

const state = {
  view: "dashboard",
  txFilters: { limit: 50, offset: 0 },
  txTotal: 0,
  caseStatus: "",
  modelInfo: null,
};

const VIEW_TITLES = {
  dashboard: ["Monitor", "Dashboard"],
  transactions: ["Monitor", "Transaction history"],
  cases: ["Monitor", "Fraud cases"],
  predict: ["Analyse", "Score a transaction"],
  model: ["Analyse", "Model & thresholds"],
  about: ["Analyse", "About the system"],
};

/* ───────────────────────── helpers ───────────────────────── */
const $ = (id) => document.getElementById(id);
const money = (value) =>
  Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (value) => `${(Number(value || 0) * 100).toFixed(2)}%`;
const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

function riskPill(level) {
  const cls = { HIGH: "pill-high", MEDIUM: "pill-medium", LOW: "pill-low" }[level] || "pill-neutral";
  return `<span class="pill ${cls}">${escapeHtml(level)}</span>`;
}
function decisionBadge(prediction) {
  return prediction === "fraud"
    ? '<span class="fraud-badge">Fraud</span>'
    : '<span class="legit-badge">Legitimate</span>';
}
function shortTime(iso) {
  if (!iso) return "—";
  return String(iso).replace("T", " ").replace("+00:00", "").replace("Z", "");
}
function showBanner(message, kind = "banner-error") {
  const banner = $("global-banner");
  banner.className = `banner ${kind} show`;
  banner.textContent = message;
}
function clearBanner() {
  $("global-banner").className = "banner";
}

/* ───────────────────────── navigation ───────────────────────── */
function navigate(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((el) =>
    el.classList.toggle("active", el.dataset.view === view)
  );
  document.querySelectorAll(".section").forEach((el) =>
    el.classList.toggle("active", el.id === `view-${view}`)
  );
  const [crumb, title] = VIEW_TITLES[view] || ["", view];
  $("breadcrumb").textContent = crumb;
  $("page-title").textContent = title;
  refreshView();
}

function refreshView() {
  clearBanner();
  if (state.view === "dashboard") loadDashboard();
  else if (state.view === "transactions") loadTransactions();
  else if (state.view === "cases") loadCases();
  else if (state.view === "model") loadModel();
}

/* ───────────────────────── health ───────────────────────── */
async function checkHealth() {
  const badge = $("api-badge");
  const text = $("api-text");
  try {
    const health = await api.health();
    badge.className = "api-badge live";
    text.textContent = `API live · ${health.components.model.version}`;
  } catch (error) {
    if (error.status === 503 && error.code === "MODEL_UNAVAILABLE") {
      badge.className = "api-badge error";
      text.textContent = "Model not loaded";
      return;
    }
    badge.className = "api-badge error";
    text.textContent = "Backend offline";
    showBanner(
      "Cannot reach the backend. Start it with: python -m backend.app (or docker compose up)."
    );
  }
}

/* ───────────────────────── dashboard ───────────────────────── */
async function loadDashboard() {
  try {
    const data = await api.analytics();
    const totals = data.totals;

    $("d-total").textContent = totals.total_transactions.toLocaleString();
    $("d-fraud").textContent = totals.fraud_detected.toLocaleString();
    $("d-fraud-sub").textContent = `${totals.fraud_rate_percent}% of scored volume`;
    $("d-high").textContent = (data.risk_distribution.HIGH || 0).toLocaleString();
    $("d-high-sub").textContent = `${data.risk_distribution.MEDIUM || 0} medium · ${
      data.risk_distribution.LOW || 0
    } low`;
    $("d-cases").textContent = data.cases.open_or_review.toLocaleString();
    $("d-cases-sub").textContent = `${data.cases.total} total cases`;
    $("d-total-sub").textContent =
      totals.total_transactions === 0
        ? "no predictions recorded yet"
        : `avg amount ${money(data.amounts.average_amount)}`;

    renderRiskBars(data.risk_distribution, totals.total_transactions);
    renderHourChart(data.by_hour);
    renderBandChart(data.by_amount_band);

    $("d-model-grid").innerHTML = [
      ["Model version", data.model.model_version],
      ["Loaded", data.model.loaded ? "yes" : "no"],
      ["Fraud threshold", data.model.fraud_threshold],
      ["Avg probability", Number(data.average_fraud_probability).toFixed(4)],
    ]
      .map(([label, value]) => `<div class="kv"><label>${label}</label><span>${escapeHtml(value)}</span></div>`)
      .join("");
    $("d-model-note").textContent = `Analytics source: ${data.data_source}.`;

    const rows = data.recent_transactions || [];
    $("d-recent").innerHTML = rows.length
      ? rows
          .map(
            (tx) => `
      <tr class="clickable-row" data-tx="${escapeHtml(tx.transaction_id)}">
        <td class="mono">${escapeHtml(tx.transaction_id)}</td>
        <td>${shortTime(tx.timestamp)}</td>
        <td style="font-weight:500">${money(tx.amount)}</td>
        <td>${pct(tx.fraud_probability)}</td>
        <td>${riskPill(tx.risk_level)}</td>
        <td>${decisionBadge(tx.prediction)}</td>
      </tr>`
          )
          .join("")
      : '<tr><td colspan="6"><div class="empty-state"><h4>No transactions yet</h4><p>Score one from the “Score a transaction” page.</p></div></td></tr>';
  } catch (error) {
    showBanner(`Could not load analytics: ${error.message}`);
  }
}

/* ───────────────────────── transactions ───────────────────────── */
async function loadTransactions() {
  try {
    const data = await api.transactions(state.txFilters);
    state.txTotal = data.pagination.total;
    const rows = data.items;

    $("t-body").innerHTML = rows.length
      ? rows
          .map(
            (tx) => `
      <tr class="clickable-row" data-tx="${escapeHtml(tx.transaction_id)}">
        <td class="mono">${escapeHtml(tx.transaction_id)}</td>
        <td>${shortTime(tx.timestamp)}</td>
        <td style="font-weight:500">${money(tx.amount)}</td>
        <td>${String(tx.hour).padStart(2, "0")}:00</td>
        <td>${pct(tx.fraud_probability)}</td>
        <td>${riskPill(tx.risk_level)}</td>
        <td>${decisionBadge(tx.prediction)}</td>
      </tr>`
          )
          .join("")
      : '<tr><td colspan="7"><div class="empty-state"><h4>No matching transactions</h4><p>Adjust the filters, or score a transaction first.</p></div></td></tr>';

    const from = data.pagination.total ? data.pagination.offset + 1 : 0;
    $("t-pagination").textContent = `Showing ${from}–${
      data.pagination.offset + data.pagination.returned
    } of ${data.pagination.total}`;
  } catch (error) {
    showBanner(`Could not load transactions: ${error.message}`);
  }
}

/* ───────────────────────── cases ───────────────────────── */
async function loadCases() {
  try {
    const data = await api.cases({ status: state.caseStatus, limit: 100 });

    $("c-summary").innerHTML = [
      ["Open", data.status_counts.OPEN, "gold"],
      ["Under review", data.status_counts.UNDER_REVIEW, ""],
      ["Confirmed fraud", data.status_counts.CONFIRMED_FRAUD, "rust"],
      ["Marked legitimate", data.status_counts.MARKED_LEGITIMATE, "sage"],
    ]
      .map(
        ([label, value, tone]) => `
      <div class="metric-card ${tone}">
        <div class="metric-label">${label}</div>
        <div class="metric-val">${value}</div>
      </div>`
      )
      .join("");

    $("c-body").innerHTML = data.items.length
      ? data.items
          .map(
            (item) => `
      <tr class="clickable-row" data-tx="${escapeHtml(item.transaction_id)}">
        <td class="mono">${escapeHtml(item.case_id)}</td>
        <td class="mono">${escapeHtml(item.transaction_id)}</td>
        <td>${shortTime(item.created_at)}</td>
        <td>${riskPill(item.risk_level)}</td>
        <td>${item.risk_score.toFixed(3)}</td>
        <td><span class="pill pill-neutral">${escapeHtml(item.status)}</span></td>
        <td>${escapeHtml(item.reviewer || "—")}</td>
      </tr>`
          )
          .join("")
      : '<tr><td colspan="7"><div class="empty-state"><h4>No cases</h4><p>Cases open automatically when a transaction is scored HIGH risk.</p></div></td></tr>';
  } catch (error) {
    showBanner(`Could not load cases: ${error.message}`);
  }
}

/* ───────────────────────── model ───────────────────────── */
async function loadModel() {
  try {
    const info = await api.modelInfo();
    state.modelInfo = info;

    $("m-version").textContent = info.model_version;
    const dataset = info.dataset || {};
    $("m-summary").innerHTML = [
      ["Algorithm", info.algorithm],
      ["Trained at (UTC)", shortTime(info.trained_at)],
      ["Features", info.feature_count],
      ["Rows after cleaning", (dataset.total_rows || 0).toLocaleString()],
      ["Fraud rows", dataset.fraud_rows ?? "—"],
      ["Fraud share", dataset.fraud_percentage ? `${dataset.fraud_percentage}%` : "—"],
      ["Resampling", info.resampling?.method || "—"],
      ["Applied to", info.resampling?.applied_to || "—"],
      ["Active threshold", info.active_fraud_threshold],
    ]
      .map(([label, value]) => `<div class="kv"><label>${label}</label><span>${escapeHtml(value)}</span></div>`)
      .join("");

    const metrics = info.test_set_metrics || {};
    $("m-metrics").innerHTML = [
      ["Precision", metrics.precision],
      ["Recall", metrics.recall],
      ["F1 score", metrics.f1_score],
      ["ROC-AUC", metrics.roc_auc],
      ["PR-AUC", metrics.pr_auc],
      ["Threshold", metrics.threshold],
    ]
      .map(
        ([label, value]) =>
          `<div class="mm"><label>${label}</label><span>${
            value === undefined ? "—" : Number(value).toFixed(4)
          }</span></div>`
      )
      .join("");

    const matrix = metrics.confusion_matrix || [
      [0, 0],
      [0, 0],
    ];
    $("m-confusion").innerHTML = `
      <div class="conf-cell conf-tn"><div class="conf-val">${matrix[0][0].toLocaleString()}</div><div class="conf-lbl">True negatives</div></div>
      <div class="conf-cell conf-fp"><div class="conf-val">${matrix[0][1].toLocaleString()}</div><div class="conf-lbl">False positives</div></div>
      <div class="conf-cell conf-fn"><div class="conf-val">${matrix[1][0].toLocaleString()}</div><div class="conf-lbl">False negatives</div></div>
      <div class="conf-cell conf-tp"><div class="conf-val">${matrix[1][1].toLocaleString()}</div><div class="conf-lbl">True positives</div></div>`;
    $("m-confusion-note").textContent = metrics.support
      ? `Test split: ${metrics.support.legitimate.toLocaleString()} legitimate, ${metrics.support.fraud} fraud.`
      : "";

    $("m-thresholds").innerHTML = (info.threshold_analysis || [])
      .map(
        (row) => `
      <tr>
        <td style="font-weight:600">${row.threshold.toFixed(2)}</td>
        <td>${row.precision.toFixed(4)}</td>
        <td>${row.recall.toFixed(4)}</td>
        <td>${row.f1_score.toFixed(4)}</td>
        <td class="risk-m">${row.false_positives}</td>
        <td class="risk-h">${row.false_negatives}</td>
      </tr>`
      )
      .join("");

    const risk = info.risk_engine || {};
    $("m-risk").innerHTML = [
      ["HIGH at or above", risk.risk_high_threshold],
      ["MEDIUM at or above", risk.risk_medium_threshold],
      ["Amount p99", risk.amount_percentiles?.p99?.toFixed?.(2) ?? "—"],
      ["Amount p99.9", risk.amount_percentiles?.p999?.toFixed?.(2) ?? "—"],
      ["Elevated hours", (risk.elevated_risk_hours || []).join(", ") || "none"],
      ["PCA monitored", (risk.pca_components_monitored || []).join(", ") || "none"],
      ["Behavioural signals", risk.behavioural_signals || "—"],
    ]
      .map(([label, value]) => `<div class="kv"><label>${label}</label><span>${escapeHtml(value)}</span></div>`)
      .join("");

    const importances = info.feature_importances_top15 || [];
    const top = importances[0]?.importance || 1;
    $("m-importance").innerHTML = importances
      .slice(0, 8)
      .map(
        (item) => `
      <div class="prog-wrap">
        <div class="prog-label"><span>${escapeHtml(item.feature)}</span><span>${item.importance.toFixed(4)}</span></div>
        <div class="prog-bg"><div class="prog-fill" style="width:${(item.importance / top) * 100}%;background:var(--gold)"></div></div>
      </div>`
      )
      .join("");
  } catch (error) {
    showBanner(`Could not load model information: ${error.message}`);
  }
}

/* ───────────────────────── prediction ───────────────────────── */
function buildVInputs() {
  $("v-grid").innerHTML = Array.from({ length: 28 }, (_, i) => i + 1)
    .map(
      (index) => `
    <div class="form-group">
      <label>V${index}</label>
      <input type="number" id="p-v${index}" value="0" step="0.000001">
    </div>`
    )
    .join("");
}

function resetForm() {
  $("p-amount").value = 0;
  $("p-hour").value = 0;
  for (let i = 1; i <= 28; i += 1) $(`p-v${i}`).value = 0;
  $("p-result").style.display = "none";
  $("s-note").textContent = "";
}

let samples = [];
let sampleIndex = 0;
async function loadSample() {
  try {
    if (!samples.length) samples = (await api.samples()).samples || [];
    if (!samples.length) return;
    const sample = samples[sampleIndex % samples.length];
    sampleIndex += 1;
    $("p-amount").value = sample.amount;
    $("p-hour").value = sample.hour;
    for (let i = 1; i <= 28; i += 1) $(`p-v${i}`).value = sample[`v${i}`] ?? 0;
    $("s-note").textContent = `Loaded a real dataset row labelled ${sample.label.replace("_", " ")}.`;
    $("p-result").style.display = "none";
  } catch (error) {
    $("s-note").textContent = `Samples unavailable: ${error.message}`;
  }
}

async function submitPrediction() {
  const button = $("p-submit");
  const box = $("p-result");
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>Scoring…';
  box.style.display = "none";

  const payload = {
    amount: parseFloat($("p-amount").value),
    hour: parseInt($("p-hour").value, 10),
  };
  for (let i = 1; i <= 28; i += 1) {
    payload[`v${i}`] = parseFloat($(`p-v${i}`).value) || 0;
  }

  try {
    const result = await api.predict(payload);
    box.style.display = "block";
    box.className = `result-box ${result.prediction === "fraud" ? "result-fraud" : "result-legit"}`;
    $("p-result-label").textContent =
      result.prediction === "fraud" ? "Flagged as fraud" : "Legitimate";
    $("p-result-detail").textContent =
      `${result.transaction_id} · probability ${result.fraud_probability_percent}% · ` +
      `risk ${result.risk_level} (score ${result.risk_score}) · threshold ${result.threshold_used} · ` +
      `model ${result.model_version} · ${shortTime(result.timestamp)}` +
      (result.case_id ? ` · case ${result.case_id} opened` : "");
    $("p-result-signals").innerHTML = (result.risk_signals || [])
      .map((signal) => `<span class="signal-chip">${escapeHtml(signal)}</span>`)
      .join("");
    $("p-result-explain").textContent = result.explanation || "";
  } catch (error) {
    box.style.display = "block";
    box.className = "result-box result-fraud";
    $("p-result-label").textContent = "Request rejected";
    $("p-result-detail").textContent = `${error.code}: ${error.message}`;
    $("p-result-signals").innerHTML = "";
    $("p-result-explain").textContent = "";
  } finally {
    button.disabled = false;
    button.textContent = "Run prediction";
  }
}

/* ───────────────────────── detail drawer ───────────────────────── */
async function openTransaction(transactionId) {
  const backdrop = $("drawer-backdrop");
  const drawer = $("drawer");
  backdrop.classList.add("open");
  drawer.classList.add("open");
  $("dr-title").textContent = transactionId;
  $("dr-body").innerHTML = '<p class="threshold-note">Loading…</p>';

  try {
    const { transaction, case: fraudCase } = await api.transaction(transactionId);
    const features = transaction.features || {};

    const caseBlock = fraudCase
      ? `
      <div class="card">
        <div class="card-title">Case ${escapeHtml(fraudCase.case_id)}</div>
        <div class="kv-grid">
          <div class="kv"><label>Status</label><span>${escapeHtml(fraudCase.status)}</span></div>
          <div class="kv"><label>Opened</label><span>${shortTime(fraudCase.created_at)}</span></div>
          <div class="kv"><label>Reviewer</label><span>${escapeHtml(fraudCase.reviewer || "unassigned")}</span></div>
          <div class="kv"><label>Resolution</label><span>${escapeHtml(fraudCase.resolution || "—")}</span></div>
        </div>
        <div class="toolbar" style="margin-top:14px">
          <div class="form-group">
            <label>Update status</label>
            <select id="dr-status">
              ${["OPEN", "UNDER_REVIEW", "CONFIRMED_FRAUD", "MARKED_LEGITIMATE", "CLOSED"]
                .map((s) => `<option ${s === fraudCase.status ? "selected" : ""}>${s}</option>`)
                .join("")}
            </select>
          </div>
          <div class="form-group"><label>Reviewer</label><input id="dr-reviewer" value="${escapeHtml(
            fraudCase.reviewer || ""
          )}"></div>
          <div class="form-group" style="flex:1"><label>Notes</label><input id="dr-notes" value="${escapeHtml(
            fraudCase.notes || ""
          )}"></div>
          <button class="ghost-btn" id="dr-save" data-case="${escapeHtml(fraudCase.case_id)}">Save</button>
        </div>
        <p class="threshold-note" id="dr-case-msg"></p>
      </div>`
      : `
      <div class="card">
        <div class="card-title">No case</div>
        <p class="threshold-note">This transaction has no fraud case attached.</p>
        <button class="ghost-btn" id="dr-open-case" data-tx="${escapeHtml(transaction.transaction_id)}"
                style="margin-top:10px">Open a case</button>
        <p class="threshold-note" id="dr-case-msg"></p>
      </div>`;

    $("dr-body").innerHTML = `
      <div class="card">
        <div class="card-title">Decision</div>
        <div class="kv-grid">
          <div class="kv"><label>Decision</label><span>${transaction.prediction}</span></div>
          <div class="kv"><label>Fraud probability</label><span>${pct(transaction.fraud_probability)}</span></div>
          <div class="kv"><label>Risk level</label><span>${transaction.risk_level}</span></div>
          <div class="kv"><label>Risk score</label><span>${transaction.risk_score}</span></div>
          <div class="kv"><label>Amount</label><span>${money(transaction.amount)}</span></div>
          <div class="kv"><label>Hour</label><span>${String(transaction.hour).padStart(2, "0")}:00</span></div>
          <div class="kv"><label>Model version</label><span>${escapeHtml(transaction.model_version)}</span></div>
          <div class="kv"><label>Threshold used</label><span>${transaction.threshold_used}</span></div>
          <div class="kv"><label>Timestamp (UTC)</label><span>${shortTime(transaction.timestamp)}</span></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Risk signals</div>
        ${
          (transaction.triggered_rules || []).length
            ? transaction.triggered_rules
                .map(
                  (rule) => `
          <div class="prog-wrap">
            <div class="prog-label"><span>${escapeHtml(rule.rule)}</span><span>+${rule.weight}</span></div>
            <p class="threshold-note" style="margin-top:2px">${escapeHtml(rule.description)}${
                    rule.detail ? ` — ${escapeHtml(rule.detail)}` : ""
                  }</p>
          </div>`
                )
                .join("")
            : '<p class="threshold-note">No rules fired for this transaction.</p>'
        }
      </div>

      ${caseBlock}

      <div class="card">
        <div class="card-title">Model input (scaled)</div>
        <table class="feature-table">
          ${Object.entries(features)
            .map(
              ([name, value]) =>
                `<tr><td>${escapeHtml(name)}</td><td>${Number(value).toFixed(6)}</td></tr>`
            )
            .join("")}
        </table>
      </div>`;
  } catch (error) {
    $("dr-body").innerHTML = `<p class="threshold-note">Could not load: ${escapeHtml(error.message)}</p>`;
  }
}

function closeDrawer() {
  $("drawer-backdrop").classList.remove("open");
  $("drawer").classList.remove("open");
}

/* ───────────────────────── wiring ───────────────────────── */
document.addEventListener("click", async (event) => {
  const navItem = event.target.closest(".nav-item");
  if (navItem) return navigate(navItem.dataset.view);

  const row = event.target.closest(".clickable-row");
  if (row) return openTransaction(row.dataset.tx);

  const save = event.target.closest("#dr-save");
  if (save) {
    try {
      await api.updateCase(save.dataset.case, {
        status: $("dr-status").value,
        reviewer: $("dr-reviewer").value || null,
        notes: $("dr-notes").value || null,
      });
      $("dr-case-msg").textContent = "Case updated.";
      if (state.view === "cases") loadCases();
    } catch (error) {
      $("dr-case-msg").textContent = `Update failed: ${error.message}`;
    }
  }

  const openCase = event.target.closest("#dr-open-case");
  if (openCase) {
    try {
      await api.createCase({ transaction_id: openCase.dataset.tx });
      openTransaction(openCase.dataset.tx);
      if (state.view === "cases") loadCases();
    } catch (error) {
      $("dr-case-msg").textContent = `Could not open case: ${error.message}`;
    }
  }
});

$("dr-close").addEventListener("click", closeDrawer);
$("drawer-backdrop").addEventListener("click", closeDrawer);
$("refresh-btn").addEventListener("click", () => {
  checkHealth();
  refreshView();
});

$("v-toggle").addEventListener("click", () => $("v-body").classList.toggle("hidden"));
$("p-submit").addEventListener("click", submitPrediction);
$("s-load").addEventListener("click", loadSample);
$("s-clear").addEventListener("click", resetForm);

$("f-apply").addEventListener("click", () => {
  state.txFilters = {
    limit: parseInt($("f-limit").value, 10),
    offset: 0,
    risk_level: $("f-risk").value,
    prediction: $("f-prediction").value,
    start_date: $("f-start").value || "",
    end_date: $("f-end").value ? `${$("f-end").value}T23:59:59` : "",
  };
  loadTransactions();
});
$("f-clear").addEventListener("click", () => {
  ["f-risk", "f-prediction", "f-start", "f-end"].forEach((id) => ($(id).value = ""));
  state.txFilters = { limit: parseInt($("f-limit").value, 10), offset: 0 };
  loadTransactions();
});
$("t-prev").addEventListener("click", () => {
  state.txFilters.offset = Math.max(0, (state.txFilters.offset || 0) - state.txFilters.limit);
  loadTransactions();
});
$("t-next").addEventListener("click", () => {
  const next = (state.txFilters.offset || 0) + state.txFilters.limit;
  if (next < state.txTotal) {
    state.txFilters.offset = next;
    loadTransactions();
  }
});
$("c-apply").addEventListener("click", () => {
  state.caseStatus = $("c-status").value;
  loadCases();
});

buildVInputs();
checkHealth();
navigate("dashboard");
