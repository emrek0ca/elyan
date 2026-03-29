type RequestOptions = {
  method?: "GET" | "POST";
  body?: unknown;
  signal?: AbortSignal;
};

export const DEFAULT_BASE_URL =
  import.meta.env.VITE_ELYAN_API_BASE_URL?.trim() || "http://127.0.0.1:18889";

export class ApiClient {
  private sessionToken = "";
  private adminToken = "";
  private baseUrl: string;

  constructor(baseUrl = DEFAULT_BASE_URL) {
    this.baseUrl = baseUrl;
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

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const csrfToken =
      document.cookie
        .split("; ")
        .find((chunk) => chunk.startsWith("elyan_csrf="))
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
      this.sessionToken = responseSessionToken;
    }

    if (responseIsJson) {
      return (responseBody as T) ?? ({} as T);
    }
    return (responseText as unknown as T) || ({} as T);
  }
}

export const apiClient = new ApiClient();
