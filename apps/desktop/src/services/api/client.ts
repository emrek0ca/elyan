type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
};

type JsonRecord = Record<string, unknown>;

export const DEFAULT_BASE_URL =
  import.meta.env.VITE_ELYAN_API_BASE_URL?.trim() || "http://127.0.0.1:18789";

const SESSION_TOKEN_STORAGE_KEY = "elyan_session_token";

export class ApiClient {
  private sessionToken = "";
  private adminToken = "";
  private baseUrl: string;

  constructor(baseUrl = DEFAULT_BASE_URL) {
    this.baseUrl = baseUrl;
    this.clearLegacyStoredSessionToken();
  }

  setBaseUrl(baseUrl: string) {
    const normalized = baseUrl.trim().replace(/\/+$/, "");
    this.baseUrl = normalized || DEFAULT_BASE_URL;
  }

  getBaseUrl() {
    return this.baseUrl;
  }

  setAdminToken(adminToken: string) {
    this.adminToken = adminToken.trim();
  }

  hasAdminToken() {
    return Boolean(this.adminToken);
  }

  getSessionToken() {
    return this.sessionToken;
  }

  setSessionToken(sessionToken: string) {
    this.sessionToken = sessionToken.trim();
  }

  clearSessionToken() {
    this.sessionToken = "";
  }

  private clearLegacyStoredSessionToken() {
    if (typeof localStorage === "undefined") {
      return;
    }
    try {
      localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
    } catch {
      // Ignore storage failures and keep auth cookie driven.
    }
  }

  private normalizeEnvelope<T>(payload: T): T {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return payload;
    }
    const normalized = { ...(payload as JsonRecord) };
    if ("success" in normalized && !("ok" in normalized)) {
      normalized.ok = Boolean(normalized.success);
    }
    if ("ok" in normalized && !("success" in normalized)) {
      normalized.success = Boolean(normalized.ok);
    }
    return normalized as T;
  }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const csrfToken =
      document.cookie
        .split("; ")
        .find((chunk) => chunk.startsWith("elyan_csrf_token="))
        ?.split("=")[1] || "";

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method: options.method ?? "GET",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(csrfToken ? { "X-Elyan-CSRF": decodeURIComponent(csrfToken) } : {}),
          ...(this.sessionToken ? { "X-Elyan-Session-Token": this.sessionToken } : {}),
          ...(this.adminToken ? { "X-Elyan-Admin-Token": this.adminToken } : {}),
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: options.signal,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      if (/load failed|failed to fetch|networkerror/i.test(message)) {
        throw new Error("Runtime henüz hazır değil. Birkaç saniye bekleyip tekrar dene.");
      }
      throw error;
    }

    const contentType = response.headers.get("content-type") || "";
    const responseIsJson = contentType.includes("application/json");
    const responseBody = responseIsJson ? await response.clone().json().catch(() => null) : null;
    const responseText = responseIsJson ? "" : await response.clone().text().catch(() => "");

    if (!response.ok) {
      let detail = "";
      if (responseIsJson) {
        const payload = responseBody as Record<string, unknown> | null;
        detail = String(payload?.error || payload?.message || payload?.detail || "").trim();
      } else {
        detail = responseText.trim();
      }
      throw new Error(detail || `HTTP ${response.status} for ${path}`);
    }

    const responseSessionToken =
      response.headers.get("X-Elyan-Session-Token") ||
      (responseIsJson && responseBody && typeof responseBody === "object"
        ? String((responseBody as Record<string, unknown>).session_token || "")
        : "");
    if (responseSessionToken) {
      this.setSessionToken(responseSessionToken);
    }

    if (responseIsJson) {
      return this.normalizeEnvelope((responseBody as T) ?? ({} as T));
    }
    return (responseText as unknown as T) || ({} as T);
  }
}

export const apiClient = new ApiClient();
