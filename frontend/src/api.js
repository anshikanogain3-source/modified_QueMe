const API_BASE = (import.meta.env.VITE_API_BASE || "/api").replace(/\/$/, "");
const TOKEN_KEY = "queme_token";
export const SESSION_EXPIRED_EVENT = "queme:session-expired";
let expiredToken = null;

export class ApiError extends Error {
  constructor(message, status, code, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new ApiError("Could not reach QueMe. Check that the backend is running.", 0, "network_error");
  }

  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.blob();
  if (!response.ok) {
    const isPublicAuthRequest = /^\/auth\/(login|register|forgot-password|reset-password)(\/|$)/.test(path);
    if (response.status === 401 && token && !isPublicAuthRequest && localStorage.getItem(TOKEN_KEY) === token && expiredToken !== token) {
      expiredToken = token;
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
    }
    throw new ApiError(
      payload?.error || `Request failed (${response.status}).`,
      response.status,
      payload?.code,
      payload,
    );
  }
  return payload;
}

export function saveToken(token) {
  expiredToken = null;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function hasToken() {
  return Boolean(getToken());
}
