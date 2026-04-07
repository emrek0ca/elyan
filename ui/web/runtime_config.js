(function (global) {
  const DEFAULT_API_BASE_PATH = "/api/v1";

  function normalizeBaseUrl(value) {
    return String(value || "").trim().replace(/\/+$/, "");
  }

  function resolveApiBaseUrl() {
    const explicit = normalizeBaseUrl(global.ELYAN_API_BASE_URL || global.ELYAN_RUNTIME_CONFIG?.apiBaseUrl);
    if (explicit) return explicit;

    try {
      if (global.location && (global.location.protocol === "http:" || global.location.protocol === "https:")) {
        return normalizeBaseUrl(new URL(DEFAULT_API_BASE_PATH, global.location.origin).toString());
      }
    } catch (error) {
      // Fall through to relative path.
    }

    return DEFAULT_API_BASE_PATH;
  }

  global.getElyanApiBaseUrl = resolveApiBaseUrl;
})(window);
