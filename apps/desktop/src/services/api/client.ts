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

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const csrfToken =
      document.cookie
        .split("; ")
        .find((chunk) => chunk.startsWith("elyan_csrf="))
        ?.split("=")[1] || "";

    const response = await fetch(`${this.baseUrl}${path}`, {
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

    const responseSessionToken = response.headers.get("X-Elyan-Session-Token");
    if (responseSessionToken) {
      this.sessionToken = responseSessionToken;
    }

    if (!response.ok) {
      const contentType = response.headers.get("content-type") || "";
      let detail = "";
      if (contentType.includes("application/json")) {
        const payload = (await response.clone().json().catch(() => null)) as Record<string, unknown> | null;
        detail = String(payload?.error || payload?.message || payload?.detail || "").trim();
      } else {
        detail = (await response.clone().text().catch(() => "")).trim();
      }
      throw new Error(detail || `HTTP ${response.status} for ${path}`);
    }

    return (await response.json()) as T;
  }
}

export const apiClient = new ApiClient();
