const storageKeys = {
  backendUrl: "elyan-train.backend-url",
  accessToken: "elyan-train.access-token",
  email: "elyan-train.email",
};

const remoteBackendUrl = "https://api.elyan.dev";

const elements = {
  settingsPanel: document.querySelector("#settings-panel"),
  toggleSettings: document.querySelector("#toggle-settings"),
  connectionChip: document.querySelector("#connection-chip"),
  backendUrl: document.querySelector("#backend-url"),
  email: document.querySelector("#email"),
  password: document.querySelector("#password"),
  loginButton: document.querySelector("#login-button"),
  refreshProfile: document.querySelector("#refresh-profile"),
  trainingText: document.querySelector("#training-text"),
  trainButton: document.querySelector("#train-button"),
  clearButton: document.querySelector("#clear-button"),
  profileOutput: document.querySelector("#profile-output"),
  resultOutput: document.querySelector("#result-output"),
  brainChatInput: document.querySelector("#brain-chat-input"),
  brainChatSend: document.querySelector("#brain-chat-send"),
  brainChatClear: document.querySelector("#brain-chat-clear"),
  chatOutput: document.querySelector("#chat-output"),
};

const defaultCopy = {
  profile: "Henüz yüklenmedi.",
  result: "Henüz eğitim gönderilmedi.",
  chat: "Henüz sohbet yok.",
};

const brainChatHistory = [];

function setConnectionChip(label, tone = "neutral") {
  if (!elements.connectionChip) {
    return;
  }
  elements.connectionChip.textContent = label;
  elements.connectionChip.dataset.tone = tone;
}

function setAuthUiState(authed) {
  elements.trainButton.disabled = !authed;
  elements.refreshProfile.disabled = !authed;
  elements.brainChatInput.disabled = !authed;
  elements.brainChatSend.disabled = !authed;
  elements.brainChatClear.disabled = !authed;
  elements.loginButton.disabled = false;
  elements.toggleSettings.textContent = "Bağlantı";
  setConnectionChip(authed ? "Bağlandı" : "Oturum kapalı", authed ? "ready" : "idle");
}

function clearAuthState(reason = "Oturum gerekli.") {
  localStorage.removeItem(storageKeys.accessToken);
  writeStatus(elements.profileOutput, reason);
  setConnectionChip("Bağlantı yok", "error");
  setAuthUiState(false);
}

function resolveDefaultBackendUrl() {
  const { location } = window;
  const hostname = String(location?.hostname || "").toLowerCase();
  const protocol = String(location?.protocol || "").toLowerCase();
  const isBrowserHttp = protocol === "http:" || protocol === "https:";
  const isLocalHost =
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname.endsWith(".local");

  if (isBrowserHttp && !isLocalHost && location.origin) {
    return location.origin;
  }

  return remoteBackendUrl;
}

function readBackendUrl() {
  return (elements.backendUrl.value || localStorage.getItem(storageKeys.backendUrl) || resolveDefaultBackendUrl()).trim();
}

function readAccessToken() {
  const token = localStorage.getItem(storageKeys.accessToken) || "";
  if (!token) {
    return "";
  }
  const payload = parseJwtPayload(token);
  if (payload?.exp && Number.isFinite(payload.exp) && payload.exp * 1000 <= Date.now()) {
    localStorage.removeItem(storageKeys.accessToken);
    return "";
  }
  return token;
}

function parseJwtPayload(token) {
  const parts = String(token || "").split(".");
  if (parts.length !== 3) {
    return null;
  }
  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

function writeStatus(target, value) {
  target.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function compactText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function clampText(value, max = 96) {
  const text = compactText(value);
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function normalizeWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function stripLeadingGreetings(value) {
  return normalizeWhitespace(value)
    .replace(/^(selam|merhaba|hey|hi|hello|naber|nasılsın|nabersin)\b[\s,!.:-]*/i, "")
    .trim();
}

function trimTrailingDescriptors(value) {
  return normalizeWhitespace(value)
    .replace(
      /\b(hataylıyım|istanbulluyum|ankaralıyım|izmirliyim|boyum|yaşım|yaşıyorum|çalışıyorum|geliştiriciyim|geliştiricinim|geliştiricim|öğrenciyim|mühendisim)\b.*$/i,
      "",
    )
    .trim();
}

function extractName(text) {
  const match = text.match(/(?:benim\s+)?(?:adım|ismim|isim(?:im)?|ad soyadım|ad soyad(?:ım)?|ad soyadım)\s*[:\-]?\s*([^\n,.;!?]+)/i);
  if (!match?.[1]) {
    return null;
  }
  return trimTrailingDescriptors(match[1]);
}

function extractHeight(text) {
  const match = text.match(/\bboyum\s*[:\-]?\s*(\d+(?:[.,]\d+)?)(?:\s*(cm|m|metre))?/i);
  if (!match?.[1]) {
    return null;
  }
  const number = match[1].replace(",", ".");
  const unit = (match[2] || "").toLowerCase();
  if (unit === "cm") {
    return `${number} cm`;
  }
  if (unit === "m" || unit === "metre") {
    return `${number} m`;
  }
  return number.includes(".") ? `${number} m` : number;
}

function extractOrigin(text) {
  const match = text.match(/\b([a-zçğıöşü]+)lıyım\b/i);
  if (!match?.[1]) {
    return null;
  }
  const place = match[1].toLowerCase();
  if (place === "hatay") {
    return "Hatay";
  }
  return place.charAt(0).toUpperCase() + place.slice(1);
}

function extractRole(text) {
  const lowered = text.toLowerCase();
  if (
    lowered.includes("geliştiricim") ||
    lowered.includes("geliştiriciyim") ||
    lowered.includes("geliştiricinim") ||
    lowered.includes("ben senin geliştiricin")
  ) {
    return "Geliştirici";
  }
  if (lowered.includes("öğrenciyim")) {
    return "Öğrenci";
  }
  if (lowered.includes("mühendisim")) {
    return "Mühendis";
  }
  return null;
}

function formatProperNounPredicate(value) {
  const compact = normalizeWhitespace(value);
  if (!compact) {
    return compact;
  }
  return compact.endsWith("'") ? `${compact}dır` : `${compact}'dır`;
}

function formatHeightPredicate(value) {
  const compact = normalizeWhitespace(value);
  if (!compact) {
    return compact;
  }
  const unitMatch = compact.match(/^(.*?)(?:\s*(cm|m|metre))$/i);
  if (unitMatch?.[1]) {
    const number = normalizeWhitespace(unitMatch[1]);
    const unit = (unitMatch[2] || "").toLowerCase();
    if (unit === "cm") {
      return `${number} santimetredir`;
    }
    return `${number} metredir`;
  }
  return `${compact} metredir`;
}

function buildCanonicalFacts(text) {
  const cleaned = stripLeadingGreetings(text);
  const name = extractName(cleaned);
  const height = extractHeight(cleaned);
  const origin = extractOrigin(cleaned);
  const role = extractRole(cleaned);
  const facts = [];
  if (name) {
    if (role === "Geliştirici") {
      facts.push(`Kimlik: ${name}, Elyan'ın geliştiricisidir.`);
    } else {
      facts.push(`Kimlik: Kullanıcının adı ${formatProperNounPredicate(name)}.`);
    }
  }
  if (role) {
    if (role !== "Geliştirici") {
      if (role === "Öğrenci") {
        facts.push("Rol: Kullanıcı öğrencidir.");
      } else if (role === "Mühendis") {
        facts.push("Rol: Kullanıcı mühendistir.");
      } else {
        facts.push(`Rol: Kullanıcının rolü ${role.toLowerCase()}dir.`);
      }
    } else if (!name) {
      facts.push("Rol: Kullanıcı, Elyan'ın geliştiricisidir.");
    }
  }
  if (origin) {
    facts.push(`Köken: Kullanıcı ${origin}lıdır.`);
  }
  if (height) {
    facts.push(`Boy: Kullanıcının boyu ${formatHeightPredicate(height)}.`);
  }
  return { cleaned, name, height, origin, role, facts };
}

function normalizeTrainingText(text) {
  const compact = normalizeWhitespace(text);
  const facts = buildCanonicalFacts(compact);
  const fallbackSummary = clampText(stripLeadingGreetings(compact), 120);
  const bulletLines = facts.facts.length
    ? [
        "Kullanıcı bilgisi",
        ...facts.facts.map((fact) => `- ${fact}`),
      ]
    : [fallbackSummary];
  const normalizedText = bulletLines.join("\n");
  const chunks = facts.facts.length ? facts.facts.map((fact) => `Kullanıcı bilgisi\n${fact}`) : [normalizedText];
  const title = facts.name
    ? clampText(`${facts.name} · ${facts.role ?? "Bilgi notu"}`, 120)
    : deriveTitle(stripLeadingGreetings(compact));
  return {
    normalizedText,
    chunks,
    title,
    summary: facts.facts.length ? `Kullanıcı bilgisi: ${facts.facts.join(" ")}` : fallbackSummary,
    facts,
  };
}

function formatCount(value) {
  return Number.isFinite(Number(value)) ? String(Number(value)) : "0";
}

function formatProfile(profile) {
  const chat = profile?.chat ?? {};
  const policy = chat.currentServingPolicy ?? {};
  const providers = policy.primaryProviderByWorkload ?? {};
  const webGrounding = policy.webGrounding ?? {};
  const knowledge = chat.activeKnowledgeCorpus ?? {};
  const fallback = chat.fallbackStatus ?? {};
  const memoryProfile = profile?.memory?.userMemoryProfile ?? {};
  const memoryCompaction = profile?.memory?.compaction ?? {};
  const lines = [
    `mode            : ${policy.mode ?? "n/a"}`,
    `fast provider   : ${providers.mobileChatFast ?? "n/a"}`,
    `balanced        : ${providers.mobileChatBalanced ?? "n/a"}`,
    `planning        : ${providers.planning ?? "n/a"}`,
    `web grounding   : ${webGrounding.enabled ? "on" : "off"} | ${webGrounding.source ?? "n/a"} | ${formatCount(webGrounding.maxResults)} results`,
    `knowledge corpus: ${knowledge.mode ?? "n/a"} | docs=${formatCount(knowledge.readyDocuments)} | datasets=${formatCount(knowledge.readyDatasets)}`,
    `memory profile  : ${clampText(memoryProfile.summary ?? "n/a", 100)}`,
    `memory compact  : kept=${formatCount(memoryCompaction.activeSnapshotCount)} | dropped=${formatCount(memoryCompaction.compactedCount)} | stale=${formatCount(memoryCompaction.staleCount)}`,
    `fallback        : ${fallback.active ? "active" : "idle"} | ${fallback.fallbackModel ?? "n/a"}`,
  ];
  return lines.join("\n");
}

function deriveProbeQuery(text) {
  const compact = compactText(text);
  if (!compact) {
    return "Elyan eğitim notu";
  }
  const firstSentence = compact.split(/[.!?]+/).map((part) => part.trim()).find(Boolean) || compact;
  return clampText(firstSentence, 120);
}

function formatSearchProof(query, searchResult) {
  const results = Array.isArray(searchResult?.results) ? searchResult.results : [];
  const top = results[0];
  const matchedDocumentId = searchResult?.matchedDocumentId ?? null;
  const lines = [
    `query           : ${clampText(query, 120)}`,
    `retrieval mode  : ${searchResult?.retrievalMode ?? "n/a"}`,
    `results         : ${formatCount(results.length)}`,
    `degraded reason : ${searchResult?.degradedReason ?? "none"}`,
    `learned         : ${matchedDocumentId ? "yes" : "unknown"}`,
  ];

  if (top) {
    lines.push(`top match       : ${clampText(top.title ?? "n/a", 60)}`);
    lines.push(`score           : ${Number(top.score ?? 0).toFixed(3)}`);
    lines.push(`excerpt         : ${clampText(top.summary || top.content || "", 180)}`);
  } else {
    lines.push("top match       : none");
  }

  return lines.join("\n");
}

function formatTrainingReceipt(payload) {
  const document = payload?.document ?? {};
  const dataset = payload?.dataset ?? {};
  const retrievalJob = payload?.retrievalJob ?? {};
  const trainingJob = payload?.trainingJob ?? {};
  return [
    `document        : ${clampText(document.title ?? "n/a", 60)}`,
    `scope           : ${document.scope ?? "n/a"}`,
    `dataset         : ${clampText(dataset.name ?? "n/a", 60)}`,
    `retrieval job   : ${retrievalJob.status ?? "n/a"} | ${retrievalJob.kind ?? "n/a"}`,
    `training job    : ${trainingJob.status ?? "n/a"} | ${trainingJob.kind ?? "n/a"}`,
    `reuse           : ${payload?.reusedDataset ? "yes" : "no"}`,
    `normalized      : ${clampText(document.summary ?? "n/a", 80)}`,
  ].join("\n");
}

function formatBrainChatLine(role, content, meta = null) {
  const prefix = role === "assistant" ? "ELYAN" : role === "user" ? "SEN" : role.toUpperCase();
  const lines = [`${prefix}: ${compactText(content)}`];
  if (meta) {
    lines.push(`META: ${meta}`);
  }
  return lines.join("\n");
}

function renderBrainChat() {
  if (!brainChatHistory.length) {
    writeStatus(elements.chatOutput, defaultCopy.chat);
    return;
  }

  writeStatus(
    elements.chatOutput,
    brainChatHistory
      .map((message) =>
        formatBrainChatLine(
          message.role,
          message.content,
          message.meta ? `provider=${message.meta.provider ?? "n/a"} | model=${message.meta.model ?? "n/a"} | ${formatCount(message.meta.latencyMs)} ms` : null,
        ),
      )
      .join("\n\n"),
  );
}

function resetOutputs() {
  writeStatus(elements.profileOutput, defaultCopy.profile);
  writeStatus(elements.resultOutput, defaultCopy.result);
  brainChatHistory.length = 0;
  writeStatus(elements.chatOutput, defaultCopy.chat);
  setConnectionChip("Hazır", "idle");
}

function buildBrainChatConversation() {
  return brainChatHistory
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({
      role: message.role,
      content: message.content,
    }))
    .slice(-8);
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("content-type", "application/json");
  const token = readAccessToken();
  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }
  const controller = options.timeoutMs ? new AbortController() : null;
  const timeoutId = controller
    ? window.setTimeout(() => {
        controller.abort();
      }, options.timeoutMs)
    : null;
  try {
    const response = await fetch(`${readBackendUrl()}${path}`, {
      ...options,
      signal: controller?.signal,
      headers,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) {
        clearAuthState("Oturum süresi doldu. Lütfen tekrar giriş yap.");
      }
      throw new Error(payload.message || payload.code || `HTTP ${response.status}`);
    }
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("Elyan beyni şu anda yavaş. Tekrar dene.");
    }
    throw error;
  } finally {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
    }
  }
}

async function login() {
  const backendUrl = readBackendUrl();
  const email = elements.email.value.trim();
  const password = elements.password.value;
  if (!backendUrl || !email || !password) {
    throw new Error("Backend URL, admin e-posta ve şifre gerekli.");
  }
  localStorage.setItem(storageKeys.backendUrl, backendUrl);
  localStorage.setItem(storageKeys.email, email);
  const payload = await fetch(`${backendUrl}/v1/auth/login`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify({ email, password }),
  }).then(async (response) => {
    const json = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(json.message || json.code || `HTTP ${response.status}`);
    }
    return json;
  });
  const token = payload?.tokens?.accessToken;
  if (!token) {
    throw new Error("Access token alınamadı.");
  }
  localStorage.setItem(storageKeys.accessToken, token);
  elements.password.value = "";
  setAuthUiState(true);
  renderBrainChat();
  await refreshProfile();
  writeStatus(elements.resultOutput, "Oturum açıldı.");
}

async function refreshProfile() {
  const profile = await request("/v1/brain/profile", {
    method: "GET",
  });
  writeStatus(elements.profileOutput, formatProfile(profile));
  const mode = profile?.chat?.currentServingPolicy?.mode ?? "unknown";
  const docs = profile?.chat?.activeKnowledgeCorpus?.readyDocuments ?? 0;
  setConnectionChip(`${mode} · ${docs} belge`, "ready");
  return profile;
}

function deriveTitle(text) {
  const firstLine = text
    .split(/\n+/)
    .map((line) => line.trim())
    .find(Boolean);
  return (firstLine || "Elyan eğitim notu").slice(0, 80);
}

async function train() {
  const text = elements.trainingText.value.trim();
  if (!text) {
    throw new Error("Elyan'a öğretilecek metin boş olamaz.");
  }
  setConnectionChip("Gönderiliyor", "busy");
  const normalized = normalizeTrainingText(text);
  const payload = await request("/v1/brain/knowledge/documents", {
    method: "POST",
    body: JSON.stringify({
      title: normalized.title,
      scope: "shared",
      sourceType: "manual",
      text: normalized.normalizedText,
      chunks: normalized.chunks,
      learningMode: "shared_corpus_train",
      languageTags: [],
      autoQueueTraining: true,
      metadata: {
        source: "elyan-train",
        uiVersion: "v1",
        normalizedText: normalized.normalizedText,
        normalizationMode: "structured_facts_v1",
        privacyMode: "no_raw_text",
        extractedFacts: normalized.facts,
      },
    }),
  });
  const receipt = formatTrainingReceipt(payload);
  writeStatus(elements.resultOutput, `${receipt}\n\nkanıt aranıyor...`);
  const documentId = payload?.document?.id ?? null;
  const probeQuery = normalized.facts.name || normalized.facts.role || deriveProbeQuery(normalized.normalizedText);

  try {
    const proof = await request("/v1/brain/retrieval/search", {
      method: "POST",
      body: JSON.stringify({
        query: probeQuery,
        limit: 3,
      }),
    });
    const matchedDocumentId = Array.isArray(proof?.results)
      ? proof.results.find((item) => item?.documentId === documentId)?.documentId ?? null
      : null;
    const proofText = formatSearchProof(probeQuery, {
      ...proof,
      matchedDocumentId,
    });
    writeStatus(elements.resultOutput, `${receipt}\n\n${proofText}`);
    setConnectionChip(
      proof?.results?.length ? "Öğrenildi" : "Kayıt alındı",
      proof?.results?.length ? "ready" : "idle",
    );
  } catch (error) {
    writeStatus(elements.resultOutput, `${receipt}\n\nkanıt doğrulanamadı: ${error.message}`);
    setConnectionChip("Kayıt alındı", "idle");
  }

  await refreshProfile();
}

async function sendBrainChat() {
  const prompt = elements.brainChatInput.value.trim();
  if (!prompt) {
    throw new Error("Sohbet metni boş olamaz.");
  }

  elements.brainChatSend.disabled = true;
  elements.brainChatClear.disabled = true;
  setConnectionChip("Chat gönderiliyor", "busy");

  brainChatHistory.push({
    role: "user",
    content: prompt,
  });
  renderBrainChat();

  const payload = await request("/v1/brain/chat", {
    method: "POST",
    timeoutMs: 12000,
    body: JSON.stringify({
      prompt,
      title: "Elyan Train direct chat",
      conversation: buildBrainChatConversation().slice(0, -1),
    }),
  });

  const reply = payload?.reply ?? {};
  brainChatHistory.push({
    role: "assistant",
    content: reply.text ?? "",
    meta: {
      provider: reply.provider ?? "n/a",
      model: reply.model ?? "n/a",
      latencyMs: reply.latencyMs ?? 0,
    },
  });
  elements.brainChatInput.value = "";
  renderBrainChat();
  setConnectionChip(reply.provider ? `Chat · ${reply.provider}` : "Chat", "ready");
  elements.brainChatSend.disabled = false;
  elements.brainChatClear.disabled = false;
}

function bootstrap() {
  elements.backendUrl.value = localStorage.getItem(storageKeys.backendUrl) || resolveDefaultBackendUrl();
  elements.email.value = localStorage.getItem(storageKeys.email) || "";

  elements.toggleSettings.addEventListener("click", () => {
    elements.settingsPanel.classList.toggle("hidden");
  });
  elements.loginButton.addEventListener("click", () => {
    login().catch((error) => writeStatus(elements.resultOutput, error.message));
  });
  elements.refreshProfile.addEventListener("click", () => {
    refreshProfile().catch((error) => writeStatus(elements.profileOutput, error.message));
  });
  elements.trainButton.addEventListener("click", () => {
    train().catch((error) => writeStatus(elements.resultOutput, error.message));
  });
  elements.clearButton.addEventListener("click", () => {
    elements.trainingText.value = "";
    resetOutputs();
  });
  elements.brainChatSend.addEventListener("click", () => {
    sendBrainChat().catch((error) => {
      writeStatus(elements.chatOutput, error.message);
      setConnectionChip("Chat hata", "error");
      elements.brainChatSend.disabled = false;
      elements.brainChatClear.disabled = false;
    });
  });
  elements.brainChatClear.addEventListener("click", () => {
    elements.brainChatInput.value = "";
    brainChatHistory.length = 0;
    renderBrainChat();
  });
  elements.brainChatInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      sendBrainChat().catch((error) => {
        writeStatus(elements.chatOutput, error.message);
        setConnectionChip("Chat hata", "error");
        elements.brainChatSend.disabled = false;
        elements.brainChatClear.disabled = false;
      });
    }
  });

  if (readAccessToken()) {
    setAuthUiState(true);
    renderBrainChat();
    refreshProfile().catch((error) => {
      clearAuthState(error.message);
      writeStatus(elements.resultOutput, error.message);
    });
  } else {
    setAuthUiState(false);
    elements.settingsPanel.classList.remove("hidden");
    writeStatus(elements.profileOutput, "Önce giriş yap.");
    writeStatus(elements.chatOutput, "Önce giriş yap.");
    setConnectionChip("Oturum kapalı", "idle");
  }
}

bootstrap();
