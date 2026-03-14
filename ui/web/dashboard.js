const qs = (selector) => document.querySelector(selector);
const HERO_WORKFLOWS = new Set([
  "telegram_desktop_task_completion",
  "research_document_creation_verification",
  "login_continue_upload_flow",
]);

let runningWorkflowName = "";
window.__elyanProductHome = {};
window.__elyanModels = {};
window.__moduleAutomations = { summary: {}, health_rows: [], tasks: [] };

const els = {
  tabs: Array.from(document.querySelectorAll("[data-tab]")),
  panels: Array.from(document.querySelectorAll("[data-panel]")),
  gateway: qs("#gateway-pill"),
  refresh: qs("#refresh-btn"),
  model: qs("#model-value"),
  uptime: qs("#uptime-value"),
  tools: qs("#tools-value"),
  channelsCount: qs("#channels-value"),
  channels: qs("#channel-list"),
  runs: qs("#run-list"),
  chatLog: qs("#chat-log"),
  chatInput: qs("#chat-input"),
  send: qs("#send-btn"),
  statusNote: qs("#status-note"),
  statusDetail: qs("#status-detail"),
  lastSync: qs("#last-sync"),
  tasks: qs("#task-list"),
  activity: qs("#activity-list"),
  toolEvents: qs("#tool-event-list"),
  evidence: qs("#evidence-list"),
  readiness: qs("#readiness-list"),
  benchmark: qs("#benchmark-summary"),
  workflowPresets: qs("#workflow-preset-list"),
  workflowReport: qs("#workflow-report"),
  setup: qs("#setup-list"),
  moduleHealthSummary: qs("#module-health-summary"),
  moduleHealth: qs("#module-health-list"),
  onboarding: qs("#onboarding-list"),
  release: qs("#release-list"),
  modelPoolSummary: qs("#model-pool-summary"),
  modelRegistry: qs("#model-registry-list"),
  modelDefaultSummary: qs("#model-default-summary"),
  modelFallbackSummary: qs("#model-fallback-summary"),
  modelRouterSummary: qs("#model-router-summary"),
  modelProviderStatus: qs("#model-provider-status"),
  modelProviderInput: qs("#model-provider-input"),
  modelNameInput: qs("#model-name-input"),
  modelAliasInput: qs("#model-alias-input"),
  modelRolesInput: qs("#model-roles-input"),
  modelKeyInput: qs("#model-key-input"),
  modelAddBtn: qs("#model-add-btn"),
  collabEnabledInput: qs("#collab-enabled-input"),
  collabStrategyInput: qs("#collab-strategy-input"),
  collabMaxModelsInput: qs("#collab-max-models-input"),
  collabRolesInput: qs("#collab-roles-input"),
  collabSaveBtn: qs("#collab-save-btn"),
  profileSummary: qs("#profile-summary"),
  agentNameInput: qs("#agent-name-input"),
  agentLanguageInput: qs("#agent-language-input"),
  agentPersonalityInput: qs("#agent-personality-input"),
  responseModeInput: qs("#response-mode-input"),
  responseBiasInput: qs("#response-bias-input"),
  profileLocalFirstInput: qs("#profile-local-first-input"),
  profileAutonomousInput: qs("#profile-autonomous-input"),
  systemPromptInput: qs("#system-prompt-input"),
  profileSaveBtn: qs("#profile-save-btn"),
  quickActions: Array.from(document.querySelectorAll("[data-quick-prompt]")),
};

function h(text) {
  return String(text == null ? "" : text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function basename(path) {
  const value = String(path || "").trim();
  if (!value) return "";
  const parts = value.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : value;
}

function friendlyStatus(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (raw === "completed" || raw === "success") return "Tamamlandi";
  if (raw === "failed") return "Basarisiz";
  if (raw === "running" || raw === "processing") return "Calisiyor";
  if (raw === "queued") return "Sirada";
  return raw ? raw : "Bilinmiyor";
}

function friendlyFailure(value) {
  const code = String(value || "").trim().toUpperCase();
  if (!code) return "Yok";
  const labels = {
    WORKFLOW_RUN_FAILED: "Workflow calismasi tamamlanamadi",
    UNKNOWN_TOOL: "Gerekli arac bulunamadi",
    TIMEOUT: "Adim zaman asimina ugradi",
    EXECUTION_EXCEPTION: "Calisma sirasinda beklenmeyen hata olustu",
    UI_TARGET_NOT_FOUND: "Ekrandaki hedef bulunamadi",
    NO_VISUAL_CHANGE: "Tiklama beklenen degisikligi uretmedi",
    DOM_UNAVAILABLE: "Tarayici sayfa verisine ulasilamadi",
    NATIVE_DIALOG_REQUIRED: "Islem yerel pencere onayi gerektirdi",
    UNCONTROLLED_BROWSER_CHROME: "Tarayici kontrol disi pencereye gecti",
  };
  return labels[code] || code;
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeoutMs = Number(options.timeoutMs || 12000);
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
      signal: controller.signal,
    });
  } catch (err) {
    if (err && (err.name === "AbortError" || String(err.message || err).includes("aborted"))) {
      throw new Error(`Istek zaman asimina ugradi (${timeoutMs}ms).`);
    }
    throw err;
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`HTTP ${response.status} ${body}`.trim());
  }
  return response.json();
}

function addChat(text, who = "bot") {
  const row = document.createElement("div");
  row.className = `bubble ${who}`;
  row.textContent = text;
  els.chatLog.appendChild(row);
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function activateTab(name) {
  const target = String(name || "overview").trim();
  els.tabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === target);
  });
  els.panels.forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === target);
  });
}

function renderChannels(payload) {
  const rows = Array.isArray(payload?.channels) ? payload.channels : [];
  const active = rows.filter((channel) => channel && channel.enabled).length;
  els.channelsCount.textContent = String(active);
  els.channels.innerHTML = rows.length
    ? rows.map((channel) => {
        const name = h(channel?.name || channel?.id || "kanal");
        const state = channel?.enabled ? "aktif" : "pasif";
        const cls = channel?.enabled ? "ok" : "";
        return `<li><strong>${name}</strong><div class="meta"><span class="pill ${cls}">${state}</span></div></li>`;
      }).join("")
    : "<li>Kanal bilgisi bulunamadi.</li>";
}

function renderRuns(payload) {
  const rows = Array.isArray(payload?.runs) ? payload.runs : [];
  const fmtDuration = (ms) => {
    const value = Number(ms || 0);
    if (!Number.isFinite(value) || value <= 0) return "-";
    if (value < 1000) return `${Math.round(value)}ms`;
    return `${(value / 1000).toFixed(1)}s`;
  };
  const fmtRatio = (value) => {
    const ratio = Number(value || 0);
    if (!Number.isFinite(ratio) || ratio <= 0) return "-";
    return `${Math.round(ratio * 100)}%`;
  };
  els.runs.innerHTML = rows.length
    ? rows.slice(0, 12).map((run) => {
        const id = h(run?.run_id || run?.id || "-");
        const status = h(run?.status || "unknown");
        const err = run?.error ? ` | ${h(run.error)}` : "";
        const errorCode = h(run?.error_code || "-");
        const duration = fmtDuration(run?.duration_ms);
        const action = h(run?.action || "-");
        const artifacts = Number(run?.artifacts || 0);
        const qualityStatus = String(run?.quality_status || "").trim();
        const claimCoverage = fmtRatio(run?.claim_coverage);
        const criticalClaimCoverage = fmtRatio(run?.critical_claim_coverage);
        const uncertaintyCount = Number(run?.uncertainty_count || 0);
        const conflictCount = Number(run?.conflict_count || 0);
        const manualReviewCount = Number(run?.manual_review_claim_count || 0);
        const teamQualityAvg = Number(run?.team_quality_avg || 0);
        const teamClaimCoverage = fmtRatio(run?.team_research_claim_coverage);
        const teamCriticalCoverage = fmtRatio(run?.team_research_critical_claim_coverage);
        const teamUncertaintyCount = Number(run?.team_research_uncertainty_count || 0);
        const workflowProfile = String(run?.workflow_profile || "").trim();
        const workflowPhase = String(run?.workflow_phase || "").trim();
        const approvalStatus = String(run?.approval_status || "").trim();
        const planProgress = String(run?.plan_progress || "").trim();
        const reviewStatus = String(run?.review_status || "").trim();
        const workspaceMode = String(run?.workspace_mode || "").trim();
        const qualityBits = [];
        if (workflowProfile || workflowPhase) qualityBits.push(`workflow: ${h([workflowProfile, workflowPhase].filter(Boolean).join("/"))}`);
        if (approvalStatus) qualityBits.push(`approval: ${h(approvalStatus)}`);
        if (planProgress) qualityBits.push(`plan: ${h(planProgress)}`);
        if (reviewStatus) qualityBits.push(`review: ${h(reviewStatus)}`);
        if (workspaceMode) qualityBits.push(`workspace: ${h(workspaceMode)}`);
        if (qualityStatus) qualityBits.push(`quality: ${h(qualityStatus)}`);
        if (claimCoverage !== "-") qualityBits.push(`claim coverage: ${h(claimCoverage)}`);
        if (criticalClaimCoverage !== "-") qualityBits.push(`critical claim: ${h(criticalClaimCoverage)}`);
        if (qualityStatus || uncertaintyCount > 0) qualityBits.push(`uncertainty: ${h(String(uncertaintyCount))}`);
        if (conflictCount > 0) qualityBits.push(`conflicts: ${h(String(conflictCount))}`);
        if (manualReviewCount > 0) qualityBits.push(`manual review: ${h(String(manualReviewCount))}`);
        if (teamQualityAvg > 0) qualityBits.push(`team q: ${h(teamQualityAvg.toFixed(2))}`);
        if (teamClaimCoverage !== "-") qualityBits.push(`team claim: ${h(teamClaimCoverage)}`);
        if (teamCriticalCoverage !== "-") qualityBits.push(`team critical: ${h(teamCriticalCoverage)}`);
        if (teamUncertaintyCount > 0) qualityBits.push(`team uncertainty: ${h(String(teamUncertaintyCount))}`);
        const qualityLine = qualityBits.length ? `<div class="meta">${qualityBits.join(" | ")}</div>` : "";
        return `<li><strong>${id}</strong><div class="meta">status: ${status}${err}</div><div class="meta">action: ${action} | duration: ${duration} | error_code: ${errorCode} | artifacts: ${artifacts}</div>${qualityLine}</li>`;
      }).join("")
    : "<li>Run verisi yok.</li>";
}

function renderActivity(payload) {
  const rows = Array.isArray(payload?.events)
    ? payload.events
    : Array.isArray(payload?.activity)
      ? payload.activity
      : (Array.isArray(payload) ? payload : []);
  els.activity.innerHTML = rows.length
    ? rows.slice(0, 30)
        .map((item) => `<li><strong>${h(item?.type || "event")}</strong><div class="meta">${h(item?.ts || "-")} | ${h(item?.detail || "")}</div></li>`)
        .join("")
    : "<li>Aktivite kaydi yok.</li>";
}

function renderTasks(payload) {
  const active = Array.isArray(payload?.active) ? payload.active : [];
  const history = Array.isArray(payload?.history) ? payload.history : [];
  const rows = active.length ? active : history;
  els.tasks.innerHTML = rows.length
    ? rows.slice(0, 12).map((item) => {
        const taskId = h(item?.task_id || item?.id || "-");
        const status = h(item?.status || item?.state || "unknown");
        const summary = h(item?.description || item?.title || item?.objective || item?.action || "");
        return `<li><strong>${taskId}</strong><div class="meta">${status}</div>${summary ? `<div class="meta">${summary}</div>` : ""}</li>`;
      }).join("")
    : "<li>Aktif veya yakin task yok.</li>";
}

function renderReadiness(payload) {
  const readiness = payload?.readiness || {};
  const rows = [
    ["Elyan readiness", readiness?.elyan_ready, `${h(readiness?.runtime_health || "-")} | ${h(`${readiness?.connected_provider || "-"} / ${readiness?.connected_model || "-"}`)}`],
    ["Desktop operator", readiness?.desktop_operator_ready, readiness?.desktop_state_available ? "live state hazir" : "live state bekliyor"],
    ["Browser runtime", readiness?.browser_ready, readiness?.browser_ready ? "DOM-first veya fallback hazir" : "hazir degil"],
    ["Telegram", readiness?.telegram_ready, readiness?.telegram_ready ? "bagli" : "bekliyor"],
  ];
  els.readiness.innerHTML = rows.map(([label, ready, detail]) => {
    const cls = ready ? "ok" : "err";
    const text = ready ? "hazir" : "eksik";
    return `<li><strong>${h(label)}</strong><div class="meta"><span class="pill ${cls}">${text}</span> ${h(detail)}</div></li>`;
  }).join("");
}

function renderBenchmark(payload) {
  const benchmark = payload?.benchmark || {};
  const failureCodes = Array.isArray(benchmark?.remaining_failure_codes) ? benchmark.remaining_failure_codes : [];
  els.benchmark.innerHTML = [
    `<li><strong>Pass Count</strong><div class="meta">${h(`${benchmark?.pass_count ?? 0}/${benchmark?.total ?? 0}`)}</div></li>`,
    `<li><strong>Average Retries</strong><div class="meta">${h(String(benchmark?.average_retries ?? 0))}</div></li>`,
    `<li><strong>Average Replans</strong><div class="meta">${h(String(benchmark?.average_replans ?? 0))}</div></li>`,
    `<li><strong>Remaining Failure Codes</strong><div class="meta">${h(failureCodes.length ? failureCodes.join(", ") : "none")}</div></li>`,
    `<li><strong>Last Benchmark</strong><div class="meta">${h(benchmark?.last_benchmark_timestamp || "-")}</div></li>`,
  ].join("");
}

function fmtTimestamp(seconds) {
  const raw = Number(seconds || 0);
  if (!Number.isFinite(raw) || raw <= 0) return "-";
  try {
    return new Date(raw * 1000).toLocaleString("tr-TR");
  } catch {
    return "-";
  }
}

function renderModuleHealth(payload) {
  const prevState = window.__moduleAutomations || {};
  const automations = payload?.automations || {};
  const moduleHealth = payload?.module_health || automations?.module_health || {};
  const summary = payload?.summary || moduleHealth?.summary || prevState.summary || {};
  const healthRows = Array.isArray(payload?.health_rows)
    ? payload.health_rows
    : (Array.isArray(moduleHealth?.modules) ? moduleHealth.modules : (Array.isArray(prevState.health_rows) ? prevState.health_rows : []));
  const taskRows = Array.isArray(payload?.tasks)
    ? payload.tasks
    : (Array.isArray(prevState.tasks) ? prevState.tasks : []);

  window.__moduleAutomations = {
    summary,
    health_rows: healthRows,
    tasks: taskRows,
  };

  const healthByTaskId = {};
  healthRows.forEach((row) => {
    const taskId = String(row?.task_id || "").trim();
    if (taskId) healthByTaskId[taskId] = row;
  });
  const rows = taskRows.length
    ? taskRows.map((task) => {
        const taskId = String(task?.task_id || "").trim();
        const merged = { ...task, ...(healthByTaskId[taskId] || {}) };
        merged.task_id = taskId;
        return merged;
      })
    : healthRows;

  if (els.moduleHealthSummary) {
    els.moduleHealthSummary.textContent =
      `Aktif: ${Number(summary.active_modules || summary.active || 0)} | Saglikli: ${Number(summary.healthy || 0)} | ` +
      `Sorunlu: ${Number(summary.failing || 0)} | Circuit Open: ${Number(summary.circuit_open || 0)} | Beklemede: ${Number(summary.paused || 0)}`;
  }

  if (!els.moduleHealth) return;
  els.moduleHealth.innerHTML = rows.length
    ? rows.map((row) => {
        const health = String(row?.health || "unknown");
        const healthLabel = health === "healthy"
          ? "healthy"
          : (health === "failing" ? "failing" : (health === "circuit_open" ? "circuit_open" : "unknown"));
        const pillCls = health === "healthy" ? "ok" : (health === "failing" ? "err" : (health === "circuit_open" ? "warn" : ""));
        const nextRetryAt = Number(row?.next_retry_at || 0);
        const circuitUntil = Number(row?.circuit_open_until || 0);
        const now = Math.floor(Date.now() / 1000);
        const retryHint = nextRetryAt > now ? `retry: ${Math.max(1, Math.round((nextRetryAt - now) / 60))} dk` : "retry: hazir";
        const circuitHint = circuitUntil > now ? `circuit: ${Math.max(1, Math.round((circuitUntil - now) / 60))} dk` : "circuit: kapali";
        const moduleId = h(row?.module_id || "-");
        const taskId = h(row?.task_id || "");
        const status = String(row?.status || "active").toLowerCase();
        const paused = status === "paused" || status === "disabled";
        const duration = Number(row?.last_duration_ms || 0);
        const durationTxt = duration > 0 ? `${duration}ms` : "-";
        return `<li><strong>${moduleId}</strong><div class="meta"><span class="pill ${pillCls}">${h(healthLabel)}</span> status=${h(status)} | fail_streak=${h(String(row?.fail_streak ?? 0))} | timeout=${h(String(row?.timeout_seconds ?? 0))}s | duration=${h(durationTxt)}</div><div class="meta">last_run: ${h(fmtTimestamp(row?.last_run))} | ${h(retryHint)} | ${h(circuitHint)}</div><div class="preset-actions"><button class="btn" type="button" data-module-action="run_now" data-module-task-id="${taskId}">Run now</button><button class="btn" type="button" data-module-action="${paused ? "resume" : "pause"}" data-module-task-id="${taskId}">${paused ? "Resume" : "Pause"}</button><button class="btn" type="button" data-module-action="remove" data-module-task-id="${taskId}">Remove</button></div></li>`;
      }).join("")
    : "<li>Module health verisi yok.</li>";
}

function renderWorkflowPresets(payload) {
  const rows = Array.isArray(payload?.preset_workflows) ? payload.preset_workflows : [];
  els.workflowPresets.innerHTML = rows.length
    ? rows.map((row) => {
        const name = String(row?.name || "").trim();
        const workflowName = String(row?.workflow_name || row?.name || "workflow").trim();
        const isHero = HERO_WORKFLOWS.has(name);
        const isRunning = runningWorkflowName === name;
        const statusPill = row?.last_status
          ? `<span class="pill ${row?.last_failure_code ? "warn" : "ok"}">${h(friendlyStatus(row.last_status))}</span>`
          : `<span class="pill">Yeni</span>`;
        const heroPill = isHero ? `<span class="pill hero">Hero Workflow</span>` : "";
        const last = row?.last_status
          ? `<div class="report-meta">Son kosu: ${h(friendlyStatus(row.last_status))} | retry=${h(String(row?.last_retry_count ?? 0))} | replan=${h(String(row?.last_replan_count ?? 0))}${row?.last_failure_code ? ` | hata=${h(friendlyFailure(row.last_failure_code))}` : ""}</div>`
          : `<div class="report-meta">Bu workflow henuz calistirilmadi.</div>`;
        return `<div class="preset-item"><div class="preset-head"><strong>${h(workflowName)}</strong><div>${heroPill}${statusPill}</div></div><div class="preset-description">${h(row?.description || "")}</div>${last}<div class="preset-actions"><button class="btn primary" type="button" data-workflow-run="${h(name)}" ${isRunning ? "disabled" : ""}>${isRunning ? "Calisiyor..." : "Workflow'u Calistir"}</button></div></div>`;
      }).join("")
    : `<div class="preset-item">Preset workflow bulunamadi.</div>`;
}

function renderWorkflowReport(report) {
  if (!report || typeof report !== "object") {
    els.workflowReport.textContent = "Henuz bir workflow sonucu yok.";
    return;
  }
  const artifacts = Array.isArray(report?.artifacts) ? report.artifacts : [];
  const screenshots = Array.isArray(report?.screenshots) ? report.screenshots : [];
  const completed = Array.isArray(report?.completed_step_names) ? report.completed_step_names : [];
  const failureLabel = friendlyFailure(report?.failure_code || "");
  const ok = !report?.failure_code && ["completed", "success"].includes(String(report?.status || "").toLowerCase());
  const statusPill = `<span class="pill ${ok ? "ok" : "err"}">${h(friendlyStatus(report?.status || ""))}</span>`;
  const summary = ok
    ? "Workflow tamamlandi. Dogrulanan adimlar ve olusan artifact'ler asagida."
    : `Workflow tamamlanamadi. Ana neden: ${h(failureLabel)}${report?.failure_code ? ` (${h(report.failure_code)})` : ""}.`;
  els.workflowReport.innerHTML = `
    <div class="report-head">
      <strong>${h(report?.workflow_name || report?.name || "Workflow")}</strong>
      ${statusPill}
    </div>
    <div class="report-summary ${ok ? "ok" : "err"}">${summary}</div>
    <div class="report-grid">
      <div class="report-chip"><div class="k">Tamamlanan Adimlar</div><div class="v">${h(`${report?.completed_steps ?? 0}/${report?.planned_steps ?? 0}`)}</div></div>
      <div class="report-chip"><div class="k">Retry</div><div class="v">${h(String(report?.retry_count ?? 0))}</div></div>
      <div class="report-chip"><div class="k">Replan</div><div class="v">${h(String(report?.replan_count ?? 0))}</div></div>
      <div class="report-chip"><div class="k">Ana Hata</div><div class="v">${h(failureLabel)}</div></div>
    </div>
    <div class="report-meta">Gorev ozeti: ${h(report?.summary || "-")}</div>
    <div class="report-meta">Gorev kimligi: ${h(report?.task_id || "-")}</div>
    <div class="report-meta">Dogrulanan adimlar: ${h(completed.join(", ") || "-")}</div>
    <div class="report-meta">Ekran goruntusu: ${h(String(screenshots.length))} | Artifact: ${h(String(artifacts.length))}</div>
    <ul class="artifact-list">${screenshots.slice(0, 4).map((item) => `<li>${h(basename(item?.path || ""))}</li>`).join("") || "<li>Ekran goruntusu yok</li>"}</ul>
    <ul class="artifact-list">${artifacts.slice(0, 6).map((item) => `<li>${h(item?.type || "artifact")}: ${h(basename(item?.path || ""))}</li>`).join("") || "<li>Artifact yok</li>"}</ul>
  `;
}

function renderSetup(payload) {
  const rows = Array.isArray(payload?.setup) ? payload.setup : [];
  const release = payload?.release || {};
  const readyCount = rows.filter((row) => row?.ready).length;
  els.setup.innerHTML = rows.length
    ? rows.map((row) => {
        const cls = row?.ready ? "ok" : "err";
        const text = row?.ready ? "hazir" : "bekliyor";
        return `<li><strong>${h(row?.label || row?.key || "check")}</strong><div class="meta"><span class="pill ${cls}">${text}</span> ${h(row?.detail || "")}</div></li>`;
      }).join("")
      + `<li><strong>Version</strong><div class="meta">${h(release?.version || "-")} | entrypoint=${h(release?.entrypoint || "/dashboard")} | health=${h(release?.health_status || "-")}</div></li>`
      + `<li><div class="check-summary">${h(`${readyCount}/${rows.length} kritik hazirlik kalemi tamamlandi.`)}</div></li>`
    : "<li>Setup verisi yok.</li>";
}

function renderOnboarding(payload) {
  const onboarding = payload?.onboarding || {};
  const steps = Array.isArray(onboarding?.recommended_steps) ? onboarding.recommended_steps : [];
  const presets = Array.isArray(payload?.preset_workflows) ? payload.preset_workflows : [];
  const firstDemo = String(onboarding?.first_demo_workflow || "").trim();
  const firstDemoPreset = presets.find((item) => String(item?.name || "").trim() === firstDemo) || null;
  const firstDemoLabel = String(firstDemoPreset?.workflow_name || firstDemo || "").trim();
  const readyCount = steps.filter((row) => row?.ready).length;
  const allReady = steps.length > 0 && readyCount === steps.length;
  const items = [`<li><div class="check-summary">${h(allReady ? "Tum onboarding adimlari tamamlandi." : `${readyCount}/${steps.length || 1} onboarding adimi hazir.`)}</div></li>`];
  steps.forEach((row) => {
    const cls = row?.ready ? "ok" : "err";
    items.push(`<li><strong>${h(row?.label || "step")}</strong><div class="meta"><span class="pill ${cls}">${row?.ready ? "hazir" : "sirada"}</span></div></li>`);
  });
  if (firstDemo) {
    const isRunning = runningWorkflowName === firstDemo;
    items.push(`<li><strong>Ilk demo workflow</strong><div class="meta">${h(firstDemoLabel || firstDemo)}</div><div class="preset-actions"><button class="btn primary" type="button" data-workflow-run="${h(firstDemo)}" ${isRunning ? "disabled" : ""}>${isRunning ? "Calisiyor..." : "Ilk demoyu calistir"}</button></div></li>`);
  }
  els.onboarding.innerHTML = items.join("") || "<li>Onboarding verisi yok.</li>";
}

function renderRelease(payload) {
  const release = payload?.release || {};
  const checks = Array.isArray(release?.quickstart_checks) ? release.quickstart_checks : [];
  const aliases = Array.isArray(release?.entrypoint_aliases) ? release.entrypoint_aliases : [];
  const items = [
    `<li><strong>Version</strong><div class="meta">${h(release?.version || "-")}</div></li>`,
    `<li><strong>Stable Entrypoint</strong><div class="meta">${h(release?.entrypoint || "/product")}</div></li>`,
    `<li><strong>Health Page</strong><div class="meta">${h(release?.health_endpoint || "/healthz")}</div></li>`,
    `<li><strong>Entrypoint Aliases</strong><div class="meta">${h(aliases.join(", ") || "-")}</div></li>`,
  ];
  checks.forEach((row) => {
    items.push(`<li><strong>${h(row?.label || "check")}</strong><div class="meta">${h(row?.value || "-")}</div></li>`);
  });
  els.release.innerHTML = items.join("");
}

function renderProductBanner(payload) {
  const readiness = payload?.readiness || {};
  const benchmark = payload?.benchmark || {};
  const setup = Array.isArray(payload?.setup) ? payload.setup : [];
  const readyCount = setup.filter((row) => row?.ready).length;
  const totalSetup = setup.length || 0;
  const passCount = Number(benchmark?.pass_count ?? 0);
  const totalBench = Number(benchmark?.total ?? 0);
  const lastBenchmark = String(benchmark?.last_benchmark_timestamp || "").trim();
  if (readiness?.elyan_ready) {
    els.statusNote.textContent = "Elyan kullanima hazir. Hero workflow calistirabilir veya dogrudan komut verebilirsiniz.";
  } else {
    els.statusNote.textContent = "Elyan kismen hazir. Kullanim oncesi eksik hazirlik kalemlerini tamamlayin.";
  }
  const pieces = [
    totalBench ? `${passCount}/${totalBench} benchmark gecti` : "benchmark verisi yok",
    totalSetup ? `${readyCount}/${totalSetup} hazirlik kalemi tamam` : "hazirlik verisi yok",
  ];
  if (lastBenchmark) pieces.push(`son benchmark: ${lastBenchmark}`);
  if (els.statusDetail) {
    els.statusDetail.textContent = pieces.join(" | ");
  }
}

function renderToolEvents(payload) {
  const rows = Array.isArray(payload?.events) ? payload.events : (Array.isArray(payload) ? payload : []);
  els.toolEvents.innerHTML = rows.length
    ? rows.slice(0, 40).map((row) => {
        const stage = h(row?.stage || "-");
        const tool = h(row?.tool || "-");
        const step = h(row?.step || "");
        const latency = Number(row?.latency_ms || 0);
        const latencyTxt = latency > 0 ? `${latency}ms` : "-";
        const okRaw = row?.success;
        const ok = okRaw === true ? "ok" : (okRaw === false ? "err" : "");
        const summary = h(row?.payload?.text || row?.payload?.status || "");
        const meta = `${h(row?.ts || "-")} | ${stage} | ${latencyTxt}`;
        const stepLine = step ? `<div class="meta">step: ${step}</div>` : "";
        const payloadLine = summary ? `<div class="meta">${summary}</div>` : "";
        return `<li><strong>${tool}</strong> <span class="pill ${ok}">${stage}</span><div class="meta">${meta}</div>${stepLine}${payloadLine}</li>`;
      }).join("")
    : "<li>Tool event yok.</li>";
}

function renderEvidence(payload) {
  const rows = Array.isArray(payload?.records) ? payload.records : [];
  const filtered = rows.filter((row) => Array.isArray(row?.artifacts) && row.artifacts.length > 0).slice(0, 24);
  els.evidence.innerHTML = filtered.length
    ? filtered.map((row) => {
        const tool = h(row?.tool || "-");
        const req = h(row?.request_id || "-");
        const artifacts = (row?.artifacts || []).slice(0, 3).map((item) => h(item)).join(" | ");
        const ok = row?.success === true ? "ok" : "err";
        return `<li><strong>${tool}</strong> <span class="pill ${ok}">${row?.success ? "ok" : "fail"}</span><div class="meta">${req}</div><div class="meta">${artifacts}</div></li>`;
      }).join("")
    : "<li>Henuz kanit/artifact kaydi yok.</li>";
}

function formatUptime(value) {
  if (typeof value === "string" && value.trim()) return value;
  const seconds = Number(value || 0);
  if (!Number.isFinite(seconds) || seconds <= 0) return "-";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}s ${minutes}dk`;
}

function renderStatus(payload) {
  const status = String(payload?.status || "").toLowerCase();
  const ok = status === "online" || Boolean(payload?.gateway_running ?? payload?.ok ?? true);
  els.gateway.textContent = `Gateway: ${ok ? "calisiyor" : "kapali"}`;
  els.gateway.className = `pill ${ok ? "ok" : "err"}`;
  els.statusNote.textContent = ok
    ? "Elyan hazir. Hero workflow veya dogrudan komut calistirabilirsiniz."
    : "Gateway erisilemiyor. Once urun sagligini ve baglantiyi kontrol edin.";
  const runtime = payload?.runtime || {};
  const model = payload?.models?.active_model || runtime?.active_model || payload?.active_model || "-";
  const provider = payload?.models?.active_provider || runtime?.active_provider || payload?.active_provider || "-";
  els.model.textContent = `${provider}/${model}`;
  const uptime = payload?.uptime_s ?? payload?.uptime_seconds ?? runtime?.uptime_seconds ?? payload?.uptime ?? 0;
  els.uptime.textContent = formatUptime(uptime);
  const totalTools = payload?.tools_total ?? runtime?.tools_total ?? payload?.tool_count;
  els.tools.textContent = totalTools == null ? "-" : String(totalTools);
  const health = payload?.runtime_health?.status || runtime?.health_status || "";
  if (health) {
    els.gateway.textContent += ` (${health})`;
  }
}

function currentModelState() {
  return window.__elyanModels || {};
}

function renderModels(payload) {
  const state = payload || {};
  window.__elyanModels = state;
  const registry = Array.isArray(state.registered_models) && state.registered_models.length
    ? state.registered_models
    : (Array.isArray(state.registry) ? state.registry : []);
  const collaboration = state.collaboration || {};
  const enabledCount = registry.filter((item) => item && item.enabled !== false).length;
  const readyCount = registry.filter((item) => item && item.enabled !== false && item.status !== "missing_credentials" && item.has_api_key !== false).length;
  const strategy = String(collaboration.strategy || "synthesize");
  const maxModels = Number(collaboration.max_models || 1);
  const roles = Array.isArray(collaboration.roles) ? collaboration.roles : [];
  if (els.modelPoolSummary) {
    els.modelPoolSummary.textContent = `${enabledCount} kayitli model | ${readyCount} kullanima hazir | collab=${collaboration.enabled ? "acik" : "kapali"} | strategy=${strategy} | max=${maxModels}`;
  }
  if (els.modelDefaultSummary) {
    els.modelDefaultSummary.textContent = `${state.default?.provider || "-"} / ${state.default?.model || "-"}`;
  }
  if (els.modelFallbackSummary) {
    els.modelFallbackSummary.textContent = `${state.fallback?.provider || "-"} / ${state.fallback?.model || "-"}`;
  }
  if (els.modelRouterSummary) {
    const active = `${state.active_provider || "-"} / ${state.active_model || "-"}`;
    els.modelRouterSummary.textContent = `${state.router_enabled ? "acik" : "kapali"} | aktif: ${active}`;
  }
  if (els.modelProviderStatus) {
    const providerRows = Object.entries(state.provider_keys || {});
    els.modelProviderStatus.innerHTML = providerRows.length
      ? providerRows.map(([provider, meta]) => {
          const configured = Boolean(meta?.configured);
          const label = configured ? "bagli" : "eksik";
          return `<li><strong>${h(provider)}</strong><div class="meta"><span class="pill ${configured ? "ok" : "warn"}">${label}</span> ${h(meta?.via || meta?.source || "")}</div></li>`;
        }).join("")
      : "<li>Provider key durumu yok.</li>";
  }
  if (els.modelRegistry) {
    els.modelRegistry.innerHTML = registry.length
      ? registry.map((item) => {
          const id = h(item.id || `${item.provider}:${item.model}`);
          const provider = h(item.provider || "-");
          const model = h(item.model || "-");
          const alias = h(item.alias || item.label || "");
          const status = item.enabled === false ? "disabled" : (item.status || (item.has_api_key === false ? "missing_credentials" : "configured"));
          const rolesText = Array.isArray(item.roles) && item.roles.length ? item.roles.join(", ") : "all roles";
          const okCls = status === "configured" ? "ok" : (status === "disabled" ? "" : "warn");
          return `<li><strong>${alias || `${provider}/${model}`}</strong><div class="model-meta">${provider}/${model}</div><div class="model-meta">roles: ${h(rolesText)} | priority: ${h(String(item.priority ?? 50))}</div><div class="model-meta"><span class="pill ${okCls}">${h(status)}</span></div><div class="model-actions"><button class="btn" type="button" data-model-default="${id}">Varsayilan Yap</button><button class="btn" type="button" data-model-fallback="${id}">Fallback Yap</button><button class="btn" type="button" data-model-remove="${id}">Kaldir</button></div></li>`;
        }).join("")
      : "<li>Henuz kayitli model yok.</li>";
  }
  if (els.collabEnabledInput) {
    els.collabEnabledInput.checked = Boolean(collaboration.enabled);
  }
  if (els.collabStrategyInput) {
    els.collabStrategyInput.value = strategy;
  }
  if (els.collabMaxModelsInput) {
    els.collabMaxModelsInput.value = String(maxModels || 3);
  }
  if (els.collabRolesInput) {
    els.collabRolesInput.value = roles.join(", ");
  }
}

function renderAgentProfile(payload) {
  const profile = payload?.profile || payload || {};
  const runtimePolicy = profile.runtime_policy || {};
  const userProfile = profile.user_profile || {};
  if (els.agentNameInput) {
    els.agentNameInput.value = String(profile.name || "Elyan");
  }
  if (els.agentLanguageInput) {
    els.agentLanguageInput.value = String(profile.language || "tr");
  }
  if (els.agentPersonalityInput) {
    els.agentPersonalityInput.value = String(profile.personality || "professional");
  }
  if (els.responseModeInput) {
    els.responseModeInput.value = String(runtimePolicy.response_mode || "friendly");
  }
  if (els.responseBiasInput) {
    els.responseBiasInput.value = String(userProfile.response_length_bias || "short");
  }
  if (els.profileLocalFirstInput) {
    els.profileLocalFirstInput.checked = Boolean(runtimePolicy.model_local_first);
  }
  if (els.profileAutonomousInput) {
    els.profileAutonomousInput.checked = Boolean(profile.autonomous);
  }
  if (els.systemPromptInput) {
    els.systemPromptInput.value = String(profile.system_prompt || "");
  }
  if (els.profileSummary) {
    const topTopics = Array.isArray(userProfile.top_topics) && userProfile.top_topics.length ? userProfile.top_topics.join(", ") : "henuz ogrenilmedi";
    const topActions = Array.isArray(userProfile.top_actions) && userProfile.top_actions.length ? userProfile.top_actions.join(", ") : "henuz ogrenilmedi";
    els.profileSummary.innerHTML = [
      `<div class="profile-line"><strong>Calisma Dili</strong><div>${h(userProfile.preferred_language || profile.language || "tr")}</div></div>`,
      `<div class="profile-line"><strong>Yanıt Uzunlugu</strong><div>${h(userProfile.response_length_bias || "short")}</div></div>`,
      `<div class="profile-line"><strong>Sik Konular</strong><div>${h(topTopics)}</div></div>`,
      `<div class="profile-line"><strong>Basarili Aksiyonlar</strong><div>${h(topActions)}</div></div>`,
    ].join("");
  }
}

function buildRegistryEntryFromInputs() {
  const provider = String(els.modelProviderInput?.value || "").trim().toLowerCase();
  const model = String(els.modelNameInput?.value || "").trim();
  const alias = String(els.modelAliasInput?.value || "").trim();
  const roles = String(els.modelRolesInput?.value || "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  if (!provider || !model) return null;
  return {
    id: `${provider}:${model}`,
    provider,
    model,
    alias,
    enabled: true,
    roles,
    priority: 50,
  };
}

function buildCollaborationPayload() {
  return {
    enabled: Boolean(els.collabEnabledInput?.checked),
    strategy: String(els.collabStrategyInput?.value || "synthesize").trim(),
    max_models: Number(els.collabMaxModelsInput?.value || 3),
    roles: String(els.collabRolesInput?.value || "")
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean),
  };
}

async function saveModels(payload) {
  const current = currentModelState();
  const body = {
    provider: current.default?.provider,
    model: current.default?.model,
    fallback_provider: current.fallback?.provider,
    fallback_model: current.fallback?.model,
    sync_roles: false,
    ...payload,
  };
  const out = await api("/api/models", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 30000,
  });
  renderModels(out || {});
  return out;
}

function buildAgentProfilePayload() {
  return {
    name: String(els.agentNameInput?.value || "Elyan").trim() || "Elyan",
    language: String(els.agentLanguageInput?.value || "tr").trim().toLowerCase(),
    personality: String(els.agentPersonalityInput?.value || "professional").trim().toLowerCase(),
    autonomous: Boolean(els.profileAutonomousInput?.checked),
    system_prompt: String(els.systemPromptInput?.value || "").trim(),
    runtime_policy: {
      response_mode: String(els.responseModeInput?.value || "friendly").trim().toLowerCase(),
      model_local_first: Boolean(els.profileLocalFirstInput?.checked),
    },
    user_profile: {
      response_length_bias: String(els.responseBiasInput?.value || "short").trim().toLowerCase(),
    },
  };
}

async function addOrUpdateModelEntry() {
  const entry = buildRegistryEntryFromInputs();
  if (!entry) {
    els.statusNote.textContent = "Provider ve model zorunlu.";
    return;
  }
  const keyValue = String(els.modelKeyInput?.value || "").trim();
  const current = currentModelState();
  const registry = Array.isArray(current.registry) ? [...current.registry] : [];
  const next = registry.filter((item) => String(item.id || `${item.provider}:${item.model}`) !== entry.id);
  next.push(entry);
  await saveModels({
    registry: next,
    collaboration: buildCollaborationPayload(),
    api_keys: keyValue ? { [entry.provider]: keyValue } : {},
  });
  els.statusNote.textContent = `Model kaydedildi: ${entry.provider}/${entry.model}`;
  if (els.modelKeyInput) els.modelKeyInput.value = "";
}

async function saveCollaborationSettings() {
  const current = currentModelState();
  await saveModels({
    registry: Array.isArray(current.registry) ? current.registry : [],
    collaboration: buildCollaborationPayload(),
  });
  els.statusNote.textContent = "Collaboration ayarlari kaydedildi.";
}

async function saveAgentProfile() {
  const out = await api("/api/agent/profile", {
    method: "POST",
    body: JSON.stringify(buildAgentProfilePayload()),
    timeoutMs: 30000,
  });
  renderAgentProfile(out || {});
  els.statusNote.textContent = "Kisisellestirme ayarlari kaydedildi.";
}

async function removeModelEntry(entryId) {
  const current = currentModelState();
  const registry = Array.isArray(current.registry) ? current.registry : [];
  const next = registry.filter((item) => String(item.id || `${item.provider}:${item.model}`) !== String(entryId || ""));
  await saveModels({
    registry: next,
    collaboration: buildCollaborationPayload(),
  });
  els.statusNote.textContent = `Model kaldirildi: ${entryId}`;
}

async function setDefaultModel(entryId) {
  const current = currentModelState();
  const registry = Array.isArray(current.registry) ? current.registry : [];
  const selected = registry.find((item) => String(item.id || `${item.provider}:${item.model}`) === String(entryId || ""));
  if (!selected) return;
  await saveModels({
    provider: selected.provider,
    model: selected.model,
    registry,
    collaboration: buildCollaborationPayload(),
    sync_roles: true,
  });
  els.statusNote.textContent = `Varsayilan model guncellendi: ${selected.provider}/${selected.model}`;
}

async function setFallbackModel(entryId) {
  const current = currentModelState();
  const registry = Array.isArray(current.registry) ? current.registry : [];
  const selected = registry.find((item) => String(item.id || `${item.provider}:${item.model}`) === String(entryId || ""));
  if (!selected) return;
  await saveModels({
    fallback_provider: selected.provider,
    fallback_model: selected.model,
    registry,
    collaboration: buildCollaborationPayload(),
    sync_roles: false,
  });
  els.statusNote.textContent = `Fallback model guncellendi: ${selected.provider}/${selected.model}`;
}

function renderProductHome(payload) {
  window.__elyanProductHome = payload || {};
  renderProductBanner(payload || {});
  renderReadiness(payload || {});
  renderBenchmark(payload || {});
  renderWorkflowPresets(payload || {});
  renderSetup(payload || {});
  renderOnboarding(payload || {});
  renderRelease(payload || {});
  const reports = Array.isArray(payload?.recent_workflow_reports) ? payload.recent_workflow_reports : [];
  renderWorkflowReport(reports[0] || null);
}

function setSyncNote(text) {
  els.lastSync.textContent = `Son senkron: ${text}`;
}

async function loadAll() {
  els.refresh.disabled = true;
  setSyncNote("yenileniyor");
  try {
    const product = await api("/api/product/home").catch(() => ({ ok: false }));
    const [status, channels, runs, tasks, activity, toolEvents, evidence, models, agentProfile, telemetry, moduleAutomations] = await Promise.all([
      api("/api/status"),
      api("/api/channels"),
      api("/api/runs/recent"),
      api("/api/tasks"),
      api("/api/activity"),
      api("/api/tool-events?limit=80"),
      api("/api/tool-requests?limit=80"),
      api("/api/models"),
      api("/api/agent/profile"),
      api("/api/health/telemetry").catch(() => ({ ok: false, automations: { active_count: 0, module_health: { summary: {}, modules: [] } } })),
      api("/api/automations/modules?include_inactive=1&limit=100").catch(() => ({ ok: false, summary: {}, health_rows: [], tasks: [] })),
    ]);
    renderStatus(status || {});
    renderChannels(channels || {});
    renderRuns(runs || {});
    renderTasks(tasks || {});
    renderActivity(activity || {});
    renderToolEvents(toolEvents || {});
    renderEvidence(evidence || {});
    renderModels(models || {});
    renderAgentProfile(agentProfile || {});
    renderModuleHealth((moduleAutomations && moduleAutomations.ok) ? moduleAutomations : (telemetry || {}));
    if (product && product.ok) {
      renderProductHome(product);
    }
    setSyncNote(new Date().toLocaleTimeString("tr-TR"));
  } catch (err) {
    console.error(err);
    els.gateway.textContent = "Gateway: baglanti hatasi";
    els.gateway.className = "pill err";
    els.statusNote.textContent = `Baglanti hatasi: ${err.message || err}`;
    if (els.statusDetail) {
      els.statusDetail.textContent = "Product verisi alinmadi. /healthz ve gateway durumunu kontrol edin.";
    }
    setSyncNote("basarisiz");
  } finally {
    els.refresh.disabled = false;
  }
}

async function runPresetWorkflow(name) {
  const workflowName = String(name || "").trim();
  if (!workflowName) return;
  runningWorkflowName = workflowName;
  renderWorkflowPresets(window.__elyanProductHome || {});
  renderOnboarding(window.__elyanProductHome || {});
  els.statusNote.textContent = `Preset workflow calisiyor: ${workflowName}`;
  try {
    const out = await api("/api/product/workflows/run", {
      method: "POST",
      body: JSON.stringify({ name: workflowName, clear_live_state: true }),
      timeoutMs: 190000,
    });
    renderWorkflowReport(out?.workflow || null);
    els.statusNote.textContent = `Preset workflow tamamlandi: ${workflowName}`;
    await loadAll();
  } catch (err) {
    els.statusNote.textContent = `Preset workflow hatasi: ${err.message || err}`;
    renderWorkflowReport({
      name: workflowName,
      workflow_name: workflowName,
      status: "failed",
      completed_steps: 0,
      planned_steps: 0,
      retry_count: 0,
      replan_count: 0,
      failure_code: "WORKFLOW_RUN_FAILED",
      summary: String(err?.message || err || "workflow run failed"),
      artifacts: [],
      screenshots: [],
      completed_step_names: [],
    });
  } finally {
    runningWorkflowName = "";
    renderWorkflowPresets(window.__elyanProductHome || {});
    renderOnboarding(window.__elyanProductHome || {});
  }
}

async function runModuleAutomationAction(action, taskId) {
  const act = String(action || "").trim().toLowerCase();
  const rid = String(taskId || "").trim();
  if (!act || !rid) return;
  els.statusNote.textContent = `Module action: ${act} (${rid})`;
  try {
    const out = await api("/api/automations/modules/action", {
      method: "POST",
      body: JSON.stringify({ action: act, task_id: rid }),
      timeoutMs: 120000,
    });
    renderModuleHealth(out || {});
    els.statusNote.textContent = `Module action tamamlandi: ${act} (${rid})`;
  } catch (err) {
    els.statusNote.textContent = `Module action hatasi: ${err.message || err}`;
  }
}

async function sendMessage() {
  const text = els.chatInput.value.trim();
  if (!text) return;
  els.chatInput.value = "";
  addChat(text, "user");
  els.send.disabled = true;
  els.statusNote.textContent = "Komut isleniyor...";
  try {
    const out = await api("/api/message", {
      method: "POST",
      body: JSON.stringify({ text, channel: "dashboard", wait: true, timeout_s: 120 }),
      timeoutMs: 130000,
    });
    const response = out?.response || out?.text || out?.message || JSON.stringify(out);
    addChat(String(response || "Bos yanit"), "bot");
    els.statusNote.textContent = "Komut tamamlandi.";
    loadAll();
  } catch (err) {
    addChat(`Hata: ${err.message || err}`, "bot");
    els.statusNote.textContent = `Komut hatasi: ${err.message || err}`;
  } finally {
    els.send.disabled = false;
  }
}

function pushActivityRow(item) {
  if (!item) return;
  const li = document.createElement("li");
  const type = h(item.type || item.event || "event");
  const ts = h(item.ts || "-");
  const detail = h(item.detail || item.text || "");
  li.innerHTML = `<strong>${type}</strong><div class="meta">${ts} | ${detail}</div>`;
  els.activity.prepend(li);
  while (els.activity.children.length > 30) {
    els.activity.removeChild(els.activity.lastChild);
  }
}

function pushToolEventRow(item) {
  if (!item) return;
  const li = document.createElement("li");
  const stage = h(item.stage || "-");
  const tool = h(item.tool || "-");
  const latency = Number(item.latency_ms || 0);
  const latencyTxt = latency > 0 ? `${latency}ms` : "-";
  const okRaw = item.success;
  const ok = okRaw === true ? "ok" : (okRaw === false ? "err" : "");
  const summary = h(item?.payload?.text || item?.payload?.status || "");
  li.innerHTML = `<strong>${tool}</strong> <span class="pill ${ok}">${stage}</span><div class="meta">${h(item.ts || "-")} | ${latencyTxt}</div>${summary ? `<div class="meta">${summary}</div>` : ""}`;
  els.toolEvents.prepend(li);
  while (els.toolEvents.children.length > 40) {
    els.toolEvents.removeChild(els.toolEvents.lastChild);
  }
}

function connectWs() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws/dashboard`);
  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      const ev = payload?.event || payload?.type || "";
      if (!payload || !ev) return;
      if (ev === "history" && Array.isArray(payload.data)) {
        payload.data.slice().reverse().forEach(pushActivityRow);
        return;
      }
      if (ev === "activity") {
        pushActivityRow(payload.data || {});
        return;
      }
      if (ev === "tool_history" && Array.isArray(payload.data)) {
        payload.data.slice().reverse().forEach(pushToolEventRow);
        return;
      }
      if (ev === "tool_event") {
        pushToolEventRow(payload.data || {});
        return;
      }
      if (ev === "telemetry" && payload.data) {
        const data = payload.data || {};
        if (data.hardware) {
          const cpu = Number(data.hardware.cpu || 0).toFixed(0);
          const ram = Number(data.hardware.ram || 0).toFixed(0);
          els.gateway.textContent = `${els.gateway.textContent.split("(")[0].trim()} (cpu:${cpu}% ram:${ram}%)`;
        }
        if (data.automations) {
          renderModuleHealth({ automations: data.automations });
        }
      }
    } catch (err) {
      console.warn("WS parse error", err);
    }
  };
  ws.onclose = () => setTimeout(connectWs, 1500);
  ws.onerror = () => ws.close();
}

els.refresh.addEventListener("click", loadAll);
els.send.addEventListener("click", sendMessage);
els.quickActions.forEach((button) => {
  button.addEventListener("click", () => {
    const prompt = String(button.getAttribute("data-quick-prompt") || "").trim();
    if (!prompt) return;
    els.chatInput.value = prompt;
    sendMessage();
  });
});
els.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") sendMessage();
});
document.addEventListener("click", (event) => {
  const tabButton = event.target && typeof event.target.closest === "function"
    ? event.target.closest("[data-tab]")
    : null;
  if (tabButton) {
    const tab = String(tabButton.getAttribute("data-tab") || "").trim();
    if (tab) activateTab(tab);
    return;
  }
  const button = event.target && typeof event.target.closest === "function"
    ? event.target.closest("[data-workflow-run]")
    : null;
  if (button) {
    const name = String(button.getAttribute("data-workflow-run") || "").trim();
    if (!name) return;
    runPresetWorkflow(name);
    return;
  }
  const removeButton = event.target && typeof event.target.closest === "function"
    ? event.target.closest("[data-model-remove]")
    : null;
  if (removeButton) {
    const id = String(removeButton.getAttribute("data-model-remove") || "").trim();
    if (!id) return;
    removeModelEntry(id);
    return;
  }
  const defaultButton = event.target && typeof event.target.closest === "function"
    ? event.target.closest("[data-model-default]")
    : null;
  if (defaultButton) {
    const id = String(defaultButton.getAttribute("data-model-default") || "").trim();
    if (!id) return;
    setDefaultModel(id);
    return;
  }
  const fallbackButton = event.target && typeof event.target.closest === "function"
    ? event.target.closest("[data-model-fallback]")
    : null;
  if (fallbackButton) {
    const id = String(fallbackButton.getAttribute("data-model-fallback") || "").trim();
    if (!id) return;
    setFallbackModel(id);
    return;
  }
  const moduleButton = event.target && typeof event.target.closest === "function"
    ? event.target.closest("[data-module-action]")
    : null;
  if (moduleButton) {
    const action = String(moduleButton.getAttribute("data-module-action") || "").trim();
    const taskId = String(moduleButton.getAttribute("data-module-task-id") || "").trim();
    if (!action || !taskId) return;
    runModuleAutomationAction(action, taskId);
  }
});

els.modelAddBtn?.addEventListener("click", addOrUpdateModelEntry);
els.collabSaveBtn?.addEventListener("click", saveCollaborationSettings);
els.profileSaveBtn?.addEventListener("click", saveAgentProfile);

activateTab("overview");
addChat("Elyan hazir. Komut verebilirsin.", "bot");
loadAll();
connectWs();
setInterval(loadAll, 30000);
