/**
 * API client for DhanRaksha 2.0.
 *
 * The frontend and the API are served by the same Flask app, so the API is
 * always same-origin: wherever the page is loaded from, the API sits at
 * /api/v1 on that same host. No hostname is hardcoded anywhere, so the
 * identical files run locally and in production with no build step and no
 * environment swap. A test enforces this.
 *
 * localhost is used ONLY when the page is opened straight off disk with a
 * file:// URL, which cannot happen once deployed.
 */
const API_BASE = (() => {
  if (window.location.protocol === "file:") {
    // Local development convenience only. Never reached in production.
    return "http://localhost:5000/api/v1";
  }
  return `${window.location.origin}/api/v1`;
})();

class ApiError extends Error {
  constructor(code, message, status, details) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details || {};
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const code = body?.error || "REQUEST_FAILED";
    const message = body?.message || `Request failed with status ${response.status}`;
    throw new ApiError(code, message, response.status, body?.details);
  }
  return body;
}

function queryString(params) {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") search.append(key, value);
  });
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

const api = {
  health: () => request("/health"),
  modelInfo: () => request("/model-info"),
  analytics: () => request("/analytics"),
  predict: (payload) =>
    request("/predict", { method: "POST", body: JSON.stringify(payload) }),
  transactions: (filters) => request(`/transactions${queryString(filters)}`),
  transaction: (id) => request(`/transactions/${encodeURIComponent(id)}`),
  cases: (filters) => request(`/cases${queryString(filters)}`),
  case: (id) => request(`/cases/${encodeURIComponent(id)}`),
  createCase: (payload) =>
    request("/cases", { method: "POST", body: JSON.stringify(payload) }),
  updateCase: (id, payload) =>
    request(`/cases/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  samples: () => request("/sample-transactions"),
};
