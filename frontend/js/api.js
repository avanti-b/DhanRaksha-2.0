/**
 * API client for DhanRaksha 2.0.
 *
 * When the page is served by Flask the API is same-origin. When index.html is
 * opened directly from disk (file://) it falls back to localhost:5000, which is
 * what CORS is enabled for.
 */
const API_BASE = (() => {
  if (window.location.protocol === "file:") return "http://localhost:5000/api/v1";
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
