/* ================================================================
   Elyan Dashboard — Production JS
   All event binding inside DOMContentLoaded to prevent null errors.
   API responses match core/llm_setup.py + core/gateway/server.py.
   ================================================================ */

document.addEventListener("DOMContentLoaded", function () {
  "use strict";

  /* ── helpers ── */
  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }
  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return document.querySelectorAll(s); };

  /* ── state ── */
  var providers = [];
  var ollamaData = {};
  var settingsState = { primaryLLM: "", strategy: "balanced", language: "tr", localFirst: false };
  var missionState = {
    overview: {},
    missions: [],
    approvals: [],
    skills: [],
    memory: { profile: [], workflow: [], task: [], evidence: [] },
    selectedMissionId: ""
  };
  var traceState = {
    taskId: "",
    bundle: {},
    evidence: [],
    live: []
  };
  var skillCatalogState = {
    skills: [],
    workflows: [],
    summary: { total: 0, enabled: 0, runtime_ready: 0, workflows_total: 0, workflows_enabled: 0 }
  };
  var marketplaceState = {
    query: "",
    listings: [],
    categories: [],
    total: 0
  };
  var integrationState = {
    provider: "google",
    accounts: [],
    traces: [],
    summary: { accounts_total: 0, trace_total: 0, fallback_count: 0 }
  };
  var channelState = {
    items: [],
    catalog: [],
    selectedId: "",
    selectedType: "",
    isDraft: false,
    summary: { total: 0, enabled: 0, connected: 0, degraded: 0 }
  };
  var autopilotState = {
    enabled: false,
    running: false,
    tick_count: 0,
    last_tick_reason: "",
    last_actions: [],
    maintenance: {},
    predictive: {},
    automation: {}
  };
  var packState = {
    packs: [],
    lastLoadedAt: 0
  };
  var toolsPolicyState = {
    allow: [],
    deny: [],
    requireApproval: [],
    defaultDeny: true,
    defaults: {}
  };
  var initialMissionId = "";
  var initialTraceId = "";
  try {
    var params = new URLSearchParams(window.location.search || "");
    initialMissionId = params.get("mission_id") || params.get("selected_mission_id") || "";
    initialTraceId = params.get("trace_id") || params.get("task_id") || "";
  } catch (e) {
    initialMissionId = "";
    initialTraceId = "";
  }
  var requestedMissionId = initialMissionId;
  if (initialMissionId) {
    missionState.selectedMissionId = initialMissionId;
  }
  if (initialTraceId) {
    traceState.taskId = initialTraceId;
    if (!missionState.selectedMissionId) {
      missionState.selectedMissionId = initialTraceId;
    }
    if (!requestedMissionId) {
      requestedMissionId = initialTraceId;
    }
  }
  var missionFilter = "all";
  var activeTab = initialTraceId ? "trace" : "mission";
  var REQUEST_TIMEOUT = { timeoutMs: 130000 };
  var timeoutMs = 130000;
  var PACK_ACTIONS = {
    quivr: {
      scaffold: {
        mode: "Sprint",
        prompt: "Quivr icin second-brain scaffold olustur: Brain.from_files, RetrievalConfig.from_yaml, grounded Q&A ve sample docs hazirla."
      },
      workflow: {
        mode: "Balanced",
        prompt: "Quivr workspace icin workflow bundle hazirla, grounded cevap zincirini ve teslim akisini toparla."
      }
    },
    "cloudflare-agents": {
      scaffold: {
        mode: "Sprint",
        prompt: "Cloudflare Agents worker app scaffold olustur: routeAgentRequest, useAgent, useAgentChat, workflow notlari ve MCP notlari hazirla."
      },
      workflow: {
        mode: "Balanced",
        prompt: "Cloudflare Agents icin workflow bundle hazirla, edge agent akisini ve deployment notlarini toparla."
      }
    },
    opengauss: {
      scaffold: {
        mode: "Sprint",
        prompt: "OpenGauss database workspace scaffold olustur: docker compose, schema bootstrap, query script, backup ve restore akislarini hazirla."
      },
      query: {
        mode: "Audit",
        prompt: "OpenGauss icin guvenli read-only query akisi hazirla ve gerekirse execute ederek kanitla."
      }
    }
  };

  function friendlyFailure(error) {
    var low = String(error || "").toLowerCase();
    if (low.indexOf("timeout") >= 0 || low.indexOf("zaman") >= 0) return "Istek zaman asimina ugradi";
    return "Mission simdilik tamamlanamadi";
  }

  /* ── toast ── */
  function toast(msg, type) {
    var el = document.createElement("div");
    el.className = "toast " + (type || "info");
    el.textContent = msg;
    var c = $("#toasts");
    if (c) c.appendChild(el);
    setTimeout(function () { el.remove(); }, 3500);
  }

  /* ── api ── */
  function api(url, opts) {
    var options = opts || {};
    var controller = new AbortController();
    var t = window.setTimeout(function () { controller.abort(); }, Number(options.timeoutMs || timeoutMs));
    var headers = options.headers || {};
    return fetch(url, {
      method: options.method || "GET",
      headers: headers,
      body: options.body,
      signal: controller.signal,
      credentials: "same-origin"
    })
      .then(function (r) {
        var contentType = String(r.headers && r.headers.get ? r.headers.get("content-type") : "").toLowerCase();
        if (contentType.indexOf("application/json") >= 0) {
          return r.json().then(function (data) {
            if (!r.ok && data && typeof data === "object" && data.ok === undefined) {
              data.ok = false;
              data.status = r.status;
            }
            return data;
          });
        }
        return r.text().then(function (text) {
          var fallback = { ok: r.ok, status: r.status, error: "HTTP " + r.status };
          if (text) fallback.body = text.slice(0, 500);
          return fallback;
        });
      })
      .catch(function (e) { console.error("api", url, e); return { ok: false, error: e.message }; })
      .finally(function () { window.clearTimeout(t); });
  }
  function GET(url) { return api(url); }
  function POST(url, body) {
    return api(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      timeoutMs: timeoutMs
    });
  }

  function fmtDate(ts) {
    var v = Number(ts || 0);
    if (!v) return "-";
    try { return new Date(v * 1000).toLocaleString("tr-TR"); } catch (e) { return "-"; }
  }

  function copyText(text, okMessage) {
    var value = String(text || "");
    if (!value) {
      toast("Kopyalanacak veri yok", "err");
      return Promise.resolve(false);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value).then(function () {
        if (okMessage) toast(okMessage, "ok");
        return true;
      }).catch(function () {
        return fallbackCopy(value, okMessage);
      });
    }
    return fallbackCopy(value, okMessage);
  }

  function fallbackCopy(value, okMessage) {
    var ta = document.createElement("textarea");
    ta.value = value;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      document.execCommand("copy");
      if (okMessage) toast(okMessage, "ok");
      return Promise.resolve(true);
    } catch (e) {
      toast("Kopyalama basarisiz", "err");
      return Promise.resolve(false);
    } finally {
      ta.remove();
    }
  }

  function bindCopyCommandButtons(root) {
    var scope = root || document;
    if (!scope || !scope.querySelectorAll) return;
    scope.querySelectorAll(".js-copy-command").forEach(function (btn) {
      if (btn.__elyanCopyBound) return;
      btn.__elyanCopyBound = true;
      btn.addEventListener("click", function () {
        var command = String(btn.getAttribute("data-command") || "").trim();
        if (!command) {
          toast("Komut bulunamadı", "err");
          return;
        }
        copyText(command, "Komut kopyalandı");
      });
    });
  }

  function safeFileName(value) {
    var text = String(value || "trace").trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
    return text || "trace";
  }

  function downloadJson(filename, payload) {
    var blob = new Blob([JSON.stringify(payload || {}, null, 2)], { type: "application/json;charset=utf-8" });
    var url = window.URL.createObjectURL(blob);
    var anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = String(filename || "elyan-trace.json");
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(function () { window.URL.revokeObjectURL(url); }, 500);
  }

  function safeDomId(value) {
    return String(value || "").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  }

  function parseCsvList(value) {
    return String(value || "")
      .split(/[\n,]/)
      .map(function (item) { return String(item || "").trim(); })
      .filter(Boolean);
  }

  function joinCsvList(items) {
    return (Array.isArray(items) ? items : []).map(function (item) {
      return String(item || "").trim();
    }).filter(Boolean).join(", ");
  }

  function normalizeChannelType(value) {
    return String(value || "").trim().toLowerCase();
  }

  function channelCatalogEntry(type) {
    var wanted = normalizeChannelType(type);
    var items = Array.isArray(channelState.catalog) ? channelState.catalog : [];
    for (var i = 0; i < items.length; i++) {
      if (normalizeChannelType(items[i] && items[i].type) === wanted) {
        return items[i];
      }
    }
    return null;
  }

  function channelItemLabel(item) {
    var label = String((item && item.label) || (channelCatalogEntry(item && item.type) || {}).label || item.type || "Channel");
    var ctype = String((item && item.type) || "");
    return label + (ctype ? " · " + ctype : "");
  }

  function channelFieldValue(item, field) {
    if (!item || !field) return "";
    if (field.secret) return "";
    var value = item[field.name];
    if (value == null) return "";
    return String(value);
  }

  function channelFieldInputId(fieldName) {
    return "channel-field-" + safeDomId(fieldName);
  }

  function providerReadyNote(ready, total, connected) {
    var providerText = total ? ready + " reachable" : "no providers";
    return providerText + " • " + connected + " connected";
  }

  function renderInvestorHero() {
    var readinessEl = $("#hero-readiness");
    if (!readinessEl) return;
    var providersReady = (providers || []).filter(function (p) { return !!p.reachable; }).length;
    var providerTotal = (providers || []).length;
    var connectedAccounts = (integrationState.accounts || []).filter(function (item) {
      return String(item.status || "").toLowerCase() === "ready";
    }).length;
    var connectedChannels = (channelState.items || []).filter(function (item) {
      return !!item.connected;
    }).length;
    var enabledChannels = (channelState.items || []).filter(function (item) {
      return !!item.enabled;
    }).length;
    var skillsEnabled = Number((skillCatalogState.summary && skillCatalogState.summary.enabled) || 0);
    var evidenceCount = Number((traceState.evidence || []).length || 0);
    var activeMissions = Number((missionState.overview && missionState.overview.active) || 0);
    var completedMissions = Number((missionState.overview && missionState.overview.completed) || 0);
    var autopilotRunning = !!autopilotState.running;
    var demoReady = providersReady > 0 && skillsEnabled > 0 && connectedChannels > 0;
    var readiness = demoReady ? "Investor-ready" : ((providersReady > 0 || skillsEnabled > 0 || enabledChannels > 0) ? "Warming up" : "Setup needed");
    var readinessNote = (autopilotRunning ? "Autopilot on" : "Autopilot idle") + " • " + activeMissions + " aktif • " + completedMissions + " tamamlanan • " + connectedChannels + "/" + enabledChannels + " channels";
    $("#hero-readiness").textContent = readiness;
    var noteEl = $("#hero-readiness-note");
    if (noteEl) noteEl.textContent = readinessNote;
    var providerEl = $("#hero-providers");
    if (providerEl) providerEl.textContent = providerTotal ? providersReady + "/" + providerTotal : String(providersReady);
    var providerNoteEl = $("#hero-providers-note");
    if (providerNoteEl) providerNoteEl.textContent = providerReadyNote(providersReady, providerTotal, connectedAccounts);
    var evidenceEl = $("#hero-evidence");
    if (evidenceEl) evidenceEl.textContent = String(evidenceCount);
    var skillsEl = $("#hero-skills");
    if (skillsEl) skillsEl.textContent = String(skillsEnabled);
    var skillsNoteEl = $("#hero-skills-note");
    if (skillsNoteEl) skillsNoteEl.textContent = skillsEnabled ? "enabled workflows" : "no skills yet";
    renderInvestorReadiness();
  }

  function buildInvestorReadiness() {
    var providersReady = (providers || []).filter(function (p) { return !!p.reachable; }).length;
    var providerTotal = (providers || []).length;
    var connectedAccounts = (integrationState.accounts || []).filter(function (item) {
      return String(item.status || "").toLowerCase() === "ready";
    }).length;
    var connectedChannels = (channelState.items || []).filter(function (item) {
      return !!item.connected;
    }).length;
    var enabledChannels = (channelState.items || []).filter(function (item) {
      return !!item.enabled;
    }).length;
    var skillsEnabled = Number((skillCatalogState.summary && skillCatalogState.summary.enabled) || 0);
    var evidenceCount = Number((traceState.evidence || []).length || 0);
    var autopilotRunning = !!autopilotState.running;
    var items = [
      {
        label: "Local model reachable",
        ok: providersReady > 0,
        note: providerTotal ? providersReady + "/" + providerTotal + " provider reachable" : "No provider configured"
      },
      {
        label: "Skills enabled",
        ok: skillsEnabled > 0,
        note: skillsEnabled ? skillsEnabled + " workflows active" : "Enable browser, desktop, calendar"
      },
      {
        label: "Channels connected",
        ok: connectedChannels > 0,
        note: connectedChannels ? connectedChannels + " channel connected" : (enabledChannels ? enabledChannels + " enabled, runtime sync bekliyor" : "No messaging channel configured")
      },
      {
        label: "Integrations connected",
        ok: connectedAccounts > 0,
        note: connectedAccounts ? connectedAccounts + " account ready" : "Connect Gmail or Calendar"
      },
      {
        label: "Evidence trail present",
        ok: evidenceCount > 0,
        note: evidenceCount ? evidenceCount + " artifact captured" : "Run a demo to generate proof"
      },
      {
        label: "Autopilot running",
        ok: autopilotRunning,
        note: autopilotRunning ? "Proactive mode on" : "Manual mode"
      }
    ];
    var next = null;
    for (var i = 0; i < items.length; i++) {
      if (!items[i].ok) {
        next = items[i];
        break;
      }
    }
    return {
      items: items,
      complete: items.filter(function (item) { return !!item.ok; }).length,
      total: items.length,
      next: next,
      providersReady: providersReady,
      providerTotal: providerTotal,
      connectedChannels: connectedChannels,
      enabledChannels: enabledChannels,
      connectedAccounts: connectedAccounts,
      skillsEnabled: skillsEnabled,
      evidenceCount: evidenceCount,
      autopilotRunning: autopilotRunning
    };
  }

  function readinessLabel(count, total) {
    if (count >= total) return "Investor-ready";
    if (count >= 3) return "Almost ready";
    return "Setup needed";
  }

  function readinessNextStep(snapshot) {
    var next = snapshot && snapshot.next;
    if (!next) return "Demo-ready: run a live mission, export the trace and share the link.";
    if (next.label === "Local model reachable") return "Connect a provider or start Ollama so the operator can run locally.";
    if (next.label === "Skills enabled") return "Enable browser, desktop and calendar skills for the first demo.";
    if (next.label === "Channels connected") return "Configure Telegram, Slack, WhatsApp or WebChat from the Channels tab and sync runtime.";
    if (next.label === "Integrations connected") return "Connect one account such as Gmail or Calendar for a richer flow.";
    if (next.label === "Evidence trail present") return "Run a short demo to capture screenshots, video and artifacts.";
    if (next.label === "Autopilot running") return "Start autopilot so the system can brief, maintain and suggest proactively.";
    return "Run a live mission and share the trace.";
  }

  function renderInvestorReadiness() {
    var root = $("#readiness-items");
    var scoreEl = $("#readiness-score-value");
    var labelEl = $("#readiness-score-label");
    var nextEl = $("#readiness-next");
    if (!root || !scoreEl || !labelEl || !nextEl) return;
    var snapshot = buildInvestorReadiness();
    root.innerHTML = snapshot.items.map(function (item) {
      return '<div class="readiness-item ' + (item.ok ? "ok" : "warn") + '"><div class="readiness-dot"></div><div><strong>' + esc(item.label) + '</strong><p>' + esc(item.note) + '</p></div></div>';
    }).join("");
    scoreEl.textContent = snapshot.complete + "/" + snapshot.total;
    labelEl.textContent = readinessLabel(snapshot.complete, snapshot.total);
    nextEl.textContent = readinessNextStep(snapshot);
  }

  function badge(state) {
    var value = String(state || "").toLowerCase();
    var cls = "warn";
    if (value === "completed" || value === "approved") cls = "ok";
    else if (value === "failed" || value === "denied") cls = "err";
    return '<span class="pill ' + cls + '">' + esc(state || "-") + "</span>";
  }

  function missionArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function missionOverview(mission) {
    var m = mission || {};
    var graph = m.graph || {};
    var nodes = missionArray(graph.nodes);
    var counts = {
      total: nodes.length,
      completed: 0,
      running: 0,
      queued: 0,
      failed: 0,
      waiting_approval: 0,
      blocked: 0
    };
    nodes.forEach(function (node) {
      var status = String((node || {}).status || "queued").toLowerCase();
      if (counts.hasOwnProperty(status)) {
        counts[status] += 1;
      } else {
        counts.queued += 1;
      }
    });

    var evidence = missionArray(m.evidence);
    var approvals = missionArray(m.approvals);
    var quality = {};
    if (m.quality_summary && typeof m.quality_summary === "object") {
      quality = m.quality_summary;
    } else if (m.metadata && typeof m.metadata.quality_summary === "object") {
      quality = m.metadata.quality_summary;
    }
    var control = m.control_summary && typeof m.control_summary === "object" ? m.control_summary : {};

    var artifactCount = 0;
    for (var i = 0; i < evidence.length; i++) {
      if (evidence[i] && evidence[i].path) artifactCount += 1;
    }

    var pendingApprovals = 0;
    for (var j = 0; j < approvals.length; j++) {
      if (!approvals[j] || !approvals[j].status || String(approvals[j].status).toLowerCase() === "pending") {
        pendingApprovals += 1;
      }
    }

    return {
      counts: counts,
      evidence_count: evidence.length,
      artifact_count: artifactCount,
      pending_approvals: pendingApprovals,
      quality: quality,
      control: control,
      meta: m.metadata || {}
    };
  }

  function missionStatusTone(status) {
    var value = String(status || "").toLowerCase();
    if (value === "completed" || value === "approved") return "ok";
    if (value === "failed" || value === "denied") return "err";
    if (value === "waiting_approval" || value === "waiting-approval") return "warn";
    return "warn";
  }

  function missionQualityTone(quality) {
    var value = String((quality && (quality.status || quality.quality_status)) || "").toLowerCase();
    if (value === "pass" || value === "ready" || value === "approved") return "ok";
    if (value === "partial" || value === "pending") return "warn";
    if (value === "fail" || value === "blocked") return "err";
    return "warn";
  }

  function missionChip(label, value, tone) {
    return '<span class="control-chip ' + esc(tone || "") + '"><strong>' + esc(label) + ':</strong> ' + esc(value) + "</span>";
  }

  function missionMetricCard(label, value, tone, detail) {
    var cls = tone || "warn";
    var html = '<div class="quality-card ' + esc(cls) + '"><strong>' + esc(label) + "</strong><span>" + esc(value) + "</span>";
    if (detail) {
      html += '<div class="muted-sm" style="margin-top:6px">' + esc(detail) + "</div>";
    }
    html += "</div>";
    return html;
  }

  function missionFilterMatches(mission) {
    var status = String((mission || {}).status || "").toLowerCase();
    if (missionFilter === "all") return true;
    if (missionFilter === "active") return status === "queued" || status === "running" || status === "waiting_approval";
    return status === missionFilter;
  }

  /* ================================================================
     MISSION CONTROL
     ================================================================ */
  function currentMission() {
    var list = missionState.missions || [];
    if (!list.length) return null;
    if (!missionState.selectedMissionId) missionState.selectedMissionId = list[0].mission_id;
    for (var i = 0; i < list.length; i++) {
      if (list[i].mission_id === missionState.selectedMissionId) return list[i];
    }
    missionState.selectedMissionId = list[0].mission_id;
    return list[0];
  }

  function ensureRequestedMissionVisible() {
    if (!requestedMissionId) {
      return Promise.resolve();
    }
    var found = false;
    for (var i = 0; i < missionState.missions.length; i++) {
      if (missionState.missions[i] && missionState.missions[i].mission_id === requestedMissionId) {
        found = true;
        break;
      }
    }
    if (found) {
      return Promise.resolve();
    }
    return GET("/api/missions/" + encodeURIComponent(requestedMissionId) + "?user_id=local").then(function (data) {
      if (data && data.ok && data.mission) {
        missionState.missions.unshift(data.mission);
        missionState.selectedMissionId = data.mission.mission_id;
      }
    });
  }

  function renderMissionKPIs() {
    var o = missionState.overview || {};
    var el = $("#mission-kpis");
    if (!el) return;
    el.innerHTML =
      mkKPI("Aktif", o.active || 0) +
      mkKPI("Approval", o.waiting_approval || 0) +
      mkKPI("Tamamlanan", o.completed || 0) +
      mkKPI("Skill", o.skills || 0);
    renderInvestorHero();
  }

  function renderMissionList() {
    var list = $("#mission-list");
    if (!list) return;
    var missions = (missionState.missions || []).filter(missionFilterMatches);
    if (!missions.length) {
      if ((missionState.missions || []).length && missionFilter !== "all") {
        list.innerHTML = '<div class="empty">Bu filtrede mission yok. Farklı bir görünüm seç.</div>';
      } else {
        list.innerHTML = '<div class="empty">Henüz mission yok. Outcome yazıp başlat.</div>';
      }
      return;
    }
    list.innerHTML = missions.map(function (mission) {
      var active = mission.mission_id === missionState.selectedMissionId ? " active" : "";
      var summary = missionOverview(mission);
      var qualityStatus = String((summary.quality && (summary.quality.status || summary.quality.quality_status)) || mission.quality_status || "-");
      var meta = [
        "mode: " + esc(mission.mode || "Balanced"),
        "status: " + esc(mission.status || "queued"),
        "quality: " + esc(qualityStatus || "-"),
        "evidence: " + esc(summary.evidence_count || 0),
        "waves: " + esc(mission.parallel_waves || 0)
      ].join(" • ");
      return (
        '<article class="mission-card' + active + '" data-mission-id="' + esc(mission.mission_id) + '">' +
          "<h4>" + esc(mission.goal || "Mission") + "</h4>" +
          '<div class="muted-sm">' + esc(mission.deliverable_preview || "Teslim bekleniyor") + "</div>" +
          '<div class="mission-meta"><span>' + meta + "</span></div>" +
        "</article>"
      );
    }).join("");
    list.querySelectorAll(".mission-card").forEach(function (card) {
      card.addEventListener("click", function () {
        missionState.selectedMissionId = card.getAttribute("data-mission-id");
        loadMissionDetail();
      });
    });
  }

  function renderMissionControlStrip(mission) {
    var root = $("#mission-control-strip");
    if (!root) return;
    if (!mission) {
      root.innerHTML = '<div class="empty">Mission seç.</div>';
      return;
    }
    var summary = missionOverview(mission);
    var quality = summary.quality || {};
    var chips = [];
    chips.push(missionChip("Route", mission.route_mode || "-", "ok"));
    chips.push(missionChip("Status", mission.status || "-", missionStatusTone(mission.status)));
    chips.push(missionChip("Evidence", String(summary.evidence_count || 0), summary.evidence_count ? "ok" : "warn"));
    chips.push(missionChip("Approvals", String(summary.pending_approvals || 0), summary.pending_approvals ? "warn" : "ok"));
    chips.push(missionChip("Nodes", String(summary.counts.completed || 0) + "/" + String(summary.counts.total || 0), summary.counts.failed ? "err" : "ok"));
    if (quality && typeof quality === "object" && (quality.status || quality.quality_status || quality.claim_coverage !== undefined || quality.critical_claim_coverage !== undefined)) {
      chips.push(missionChip("Quality", quality.status || quality.quality_status || "-", missionQualityTone(quality)));
    }
    root.innerHTML = chips.join("");
  }

  function renderMissionQuality(mission) {
    var root = $("#mission-quality");
    if (!root) return;
    if (!mission) {
      root.innerHTML = '<div class="empty">Research quality sinyali yok.</div>';
      return;
    }
    var summary = missionOverview(mission);
    var quality = summary.quality || {};
    var cards = [];
    if (quality && typeof quality === "object" && Object.keys(quality).length > 0) {
      if (quality.status || quality.quality_status) cards.push(missionMetricCard("Durum", quality.status || quality.quality_status, missionQualityTone(quality), "Veri sinyalleri"));
      if (quality.claim_coverage !== undefined) cards.push(missionMetricCard("Claim coverage", (Number(quality.claim_coverage) * 100).toFixed(0) + "%", missionQualityTone(quality), "Toplam claim kapsami"));
      if (quality.critical_claim_coverage !== undefined) cards.push(missionMetricCard("Critical coverage", (Number(quality.critical_claim_coverage) * 100).toFixed(0) + "%", missionQualityTone(quality), "Kritik claim kapsami"));
      if (quality.uncertainty_count !== undefined) cards.push(missionMetricCard("Uncertainty", String(quality.uncertainty_count), Number(quality.uncertainty_count) > 0 ? "warn" : "ok", "Belirsiz claim sayisi"));
      if (quality.conflict_count !== undefined) cards.push(missionMetricCard("Conflicts", String(quality.conflict_count), Number(quality.conflict_count) > 0 ? "warn" : "ok", "Cakisan bulgu sayisi"));
      if (quality.manual_review_claim_count !== undefined) cards.push(missionMetricCard("Manual review", String(quality.manual_review_claim_count), Number(quality.manual_review_claim_count) > 0 ? "warn" : "ok", "Elle kontrol gereken claim'ler"));
      if (quality.source_count !== undefined) cards.push(missionMetricCard("Sources", String(quality.source_count), "ok", "Kullanilan kaynak sayisi"));
      if (quality.avg_reliability !== undefined) cards.push(missionMetricCard("Reliability", (Number(quality.avg_reliability) * 100).toFixed(0) + "%", "ok", "Ortalama guvenilirlik"));
      if (quality.claim_map_path) cards.push(missionMetricCard("Claim map", "Hazir", "ok", quality.claim_map_path));
      if (quality.revision_summary_path) cards.push(missionMetricCard("Revision", "Hazir", "ok", quality.revision_summary_path));
    }
    if (!cards.length) {
      root.innerHTML = '<div class="empty">Research quality sinyali yok.</div>';
      return;
    }
    root.innerHTML = cards.join("");
  }

  function renderMissionDetail(mission) {
    var detail = $("#mission-detail");
    var rail = $("#mission-rail");
    var control = $("#mission-control-strip");
    var quality = $("#mission-quality");
    var timeline = $("#mission-timeline");
    var deliverable = $("#mission-deliverable");
    var evidence = $("#mission-evidence");
    if (!detail || !rail || !control || !quality || !timeline || !deliverable || !evidence) return;
    if (!mission) {
      detail.innerHTML = '<div class="empty">Bir mission seç.</div>';
      rail.innerHTML = "";
      control.innerHTML = '<div class="empty">Control strip yok.</div>';
      quality.innerHTML = '<div class="empty">Research quality yok.</div>';
      timeline.innerHTML = '<div class="empty">Timeline yok.</div>';
      deliverable.textContent = "Henüz bir mission seçilmedi.";
      evidence.innerHTML = '<div class="empty">Kanıt yok.</div>';
      return;
    }
    renderMissionControlStrip(mission);
    var preview = mission.preview_summary && typeof mission.preview_summary === "object"
      ? mission.preview_summary
      : (mission.metadata && typeof mission.metadata.request_contract === "object" ? mission.metadata.request_contract : {});
    var previewChips = [];
    if (preview.content_kind) previewChips.push("Tür: " + preview.content_kind);
    if (Array.isArray(preview.output_formats) && preview.output_formats.length) previewChips.push("Çıktı: " + preview.output_formats.slice(0, 4).join(", "));
    if (preview.style_profile) previewChips.push("Stil: " + preview.style_profile);
    if (preview.source_policy) previewChips.push("Kaynak: " + preview.source_policy);
    if (Array.isArray(preview.quality_contract) && preview.quality_contract.length) previewChips.push("Kalite: " + preview.quality_contract.slice(0, 3).join(", "));
    if (preview.needs_clarification) previewChips.push("Netleştirme gerekli");
    if (preview.clarifying_question) previewChips.push("Soru: " + preview.clarifying_question);

    detail.innerHTML =
      '<div class="row"><span class="row-k">Mission</span><span class="row-v">' + esc(mission.mission_id) + "</span></div>" +
      '<div class="row"><span class="row-k">Durum</span><span class="row-v">' + badge(mission.status) + "</span></div>" +
      '<div class="row"><span class="row-k">Mode</span><span class="row-v">' + esc(mission.mode || "Balanced") + "</span></div>" +
      '<div class="row"><span class="row-k">Route</span><span class="row-v">' + esc(mission.route_mode || "task") + "</span></div>" +
      '<div class="row"><span class="row-k">Risk</span><span class="row-v">' + esc(mission.risk_profile || "low") + "</span></div>" +
      '<div class="detail-lead">' + esc(mission.goal || "") + "</div>" +
      (preview.preview ? '<div class="detail-note">' + esc(preview.preview) + "</div>" : "") +
      (previewChips.length ? '<div class="mission-meta"><span>' + previewChips.map(function (item) { return esc(item); }).join("</span><span>") + "</span></div>" : "") +
      '<div class="btn-row"><button class="btn btn-s btn-sm" id="save-skill-btn">Save as Skill</button><button class="btn btn-s btn-sm" id="mission-open-trace" type="button">Trace Aç</button></div>';

    var nodes = (((mission.graph || {}).nodes) || []);
    rail.innerHTML = nodes.length ? nodes.map(function (node) {
      var cls = esc(String(node.status || "queued").replace(/\s+/g, "_"));
      return (
        '<div class="node-pill ' + cls + '">' +
          "<strong>" + esc(node.title || node.node_id || "node") + "</strong>" +
          "<span>" + esc(node.specialist || node.kind || "task") + " • " + esc(node.status || "queued") + "</span>" +
        "</div>"
      );
    }).join("") : '<div class="empty">Task graph yok.</div>';

    renderMissionQuality(mission);

    var events = mission.events || [];
    timeline.innerHTML = events.length ? events.slice().reverse().map(function (item) {
      return (
        '<div class="timeline-item">' +
          "<strong>" + esc(item.label || item.event_type || "event") + "</strong>" +
          "<p>" + esc(item.status || "") + " • " + esc(fmtDate(item.created_at)) + "</p>" +
        "</div>"
      );
    }).join("") : '<div class="empty">Timeline yok.</div>';

    deliverable.textContent = mission.deliverable || "Teslim henüz hazır değil.";

    var evidenceItems = mission.evidence || [];
    evidence.innerHTML = evidenceItems.length ? evidenceItems.slice().reverse().map(function (item) {
      var target = item.path || item.summary || "";
      return (
        '<div class="stack-item">' +
          "<strong>" + esc(item.label || item.kind || "evidence") + "</strong>" +
          "<p>" + esc(target) + "</p>" +
        "</div>"
      );
    }).join("") : '<div class="empty">Kanıt henüz yok.</div>';

    var saveSkillBtn = $("#save-skill-btn");
    if (saveSkillBtn) saveSkillBtn.addEventListener("click", function () { saveMissionSkill(mission.mission_id); });
    var traceBtn = $("#mission-open-trace");
    if (traceBtn) traceBtn.addEventListener("click", function () { openTraceTab(mission.mission_id); });
  }

  function renderMissionApprovals() {
    var root = $("#mission-approvals");
    if (!root) return;
    var approvals = missionState.approvals || [];
    if (!approvals.length) {
      root.innerHTML = '<div class="empty">Bekleyen approval yok.</div>';
      return;
    }
    root.innerHTML = approvals.map(function (item) {
      return (
        '<div class="approval-item">' +
          "<strong>" + esc(item.title || "Approval") + "</strong>" +
          "<p>" + esc(item.goal || item.summary || "") + "</p>" +
          '<div class="mission-meta"><span>risk: ' + esc(item.risk_level || "medium") + "</span><span>" + esc(fmtDate(item.created_at)) + "</span></div>" +
          '<div class="approval-actions">' +
            '<button class="btn btn-p btn-sm js-approve" data-a="' + esc(item.approval_id) + '">Onayla</button>' +
            '<button class="btn btn-d btn-sm js-deny" data-a="' + esc(item.approval_id) + '">Reddet</button>' +
          "</div>" +
        "</div>"
      );
    }).join("");
    root.querySelectorAll(".js-approve").forEach(function (btn) {
      btn.addEventListener("click", function () { resolveMissionApproval(btn.getAttribute("data-a"), true); });
    });
    root.querySelectorAll(".js-deny").forEach(function (btn) {
      btn.addEventListener("click", function () { resolveMissionApproval(btn.getAttribute("data-a"), false); });
    });
  }

  function renderMissionSkills() {
    var root = $("#mission-skills");
    if (!root) return;
    var skills = missionState.skills || [];
    if (!skills.length) {
      root.innerHTML = '<div class="empty">Henüz skill kaydı yok.</div>';
      return;
    }
    root.innerHTML = skills.map(function (item) {
      return (
        '<div class="stack-item">' +
          "<strong>" + esc(item.name || "Skill") + "</strong>" +
          "<p>risk: " + esc(item.risk_profile || "low") + " • mission: " + esc(item.source_mission_id || "-") + "</p>" +
        "</div>"
      );
    }).join("");
  }

  function renderMissionMemory() {
    var root = $("#mission-memory");
    if (!root) return;
    var groups = missionState.memory || {};
    var rows = [];
    ["profile", "workflow", "task", "evidence"].forEach(function (key) {
      var items = groups[key] || [];
      items.slice(0, 2).forEach(function (item) {
        rows.push(
          '<div class="memory-item">' +
            "<strong>" + esc(item.title || key) + "</strong>" +
            "<p>" + esc(item.content || "") + "</p>" +
            '<div class="muted-sm">' + esc(key) + " • confidence: " + esc(item.confidence || 0) + "</div>" +
          "</div>"
        );
      });
    });
    root.innerHTML = rows.length ? rows.join("") : '<div class="empty">Mission memory henüz boş.</div>';
  }

  function renderSkillCatalog() {
    var summary = skillCatalogState.summary || {};
    var kpis = $("#skills-kpis");
    if (kpis) {
      kpis.innerHTML =
        mkKPI("Toplam", summary.total || 0) +
        mkKPI("Etkin", summary.enabled || 0) +
        mkKPI("Hazır", summary.runtime_ready || 0) +
        mkKPI("Workflow", summary.workflows_enabled || 0);
    }

    var skillsRoot = $("#skills-list");
    if (skillsRoot) {
      var skills = Array.isArray(skillCatalogState.skills) ? skillCatalogState.skills : [];
      if (!skills.length) {
        skillsRoot.innerHTML = '<div class="empty">Registry boş.</div>';
      } else {
        skillsRoot.innerHTML = skills.slice(0, 8).map(function (item) {
          var tone = item.enabled && item.runtime_ready ? "ok" : (item.enabled ? "warn" : "err");
          return (
            '<div class="stack-item">' +
              '<div class="mission-meta" style="margin-top:0;margin-bottom:6px">' +
                '<span>' + esc(item.category || "general") + '</span>' +
                '<span>' + esc(item.latency_level || "standard") + '</span>' +
                '<span class="pill ' + tone + '">' + esc(item.enabled ? (item.runtime_ready ? "Ready" : "Partial") : "Off") + '</span>' +
              '</div>' +
              '<strong>' + esc(item.name || "Skill") + '</strong>' +
              '<p>' + esc(item.description || "") + '</p>' +
            '</div>'
          );
        }).join("");
      }
    }

    var workflowsRoot = $("#skills-workflow-list");
    if (workflowsRoot) {
      var workflows = Array.isArray(skillCatalogState.workflows) ? skillCatalogState.workflows : [];
      if (!workflows.length) {
        workflowsRoot.innerHTML = '<div class="empty">Workflow yok.</div>';
      } else {
        workflowsRoot.innerHTML = workflows.slice(0, 8).map(function (item) {
          var tone = item.enabled && item.runtime_ready ? "ok" : (item.enabled ? "warn" : "err");
          return (
            '<div class="stack-item">' +
              '<div class="mission-meta" style="margin-top:0;margin-bottom:6px">' +
                '<span>' + esc(item.category || "general") + '</span>' +
                '<span>' + esc(item.source || "builtin") + '</span>' +
                '<span class="pill ' + tone + '">' + esc(item.enabled ? (item.runtime_ready ? "Ready" : "Partial") : "Off") + '</span>' +
              '</div>' +
              '<strong>' + esc(item.name || item.id || "Workflow") + '</strong>' +
              '<p>' + esc((item.required_tools || []).join(", ") || item.description || "") + '</p>' +
            '</div>'
          );
        }).join("");
      }
    }
    renderInvestorHero();
  }

  function loadSkillCatalog() {
    return Promise.all([
      GET("/api/skills?available=1"),
      GET("/api/skills/workflows?enabled=0")
    ]).then(function (results) {
      var skillData = results[0] || {};
      var workflowData = results[1] || {};
      skillCatalogState = {
        skills: Array.isArray(skillData.skills) ? skillData.skills : [],
        workflows: Array.isArray(workflowData.workflows) ? workflowData.workflows : [],
        summary: {
          total: (skillData.summary && skillData.summary.total) || 0,
          enabled: (skillData.summary && skillData.summary.enabled) || 0,
          runtime_ready: (skillData.summary && skillData.summary.runtime_ready) || 0,
          workflows_total: (workflowData.summary && workflowData.summary.total) || 0,
          workflows_enabled: (workflowData.summary && workflowData.summary.enabled) || 0
        }
      };
      renderSkillCatalog();
    });
  }

  function refreshSkillRegistry() {
    return POST("/api/skills/refresh", {}).then(function (res) {
      if (res && res.ok) {
        toast("Skill registry yenilendi", "ok");
      } else {
        toast((res && res.error) || "Skill registry yenilenemedi", "err");
      }
      return loadSkillCatalog();
    });
  }

  function renderMarketplace() {
    var summary = marketplaceState || {};
    var kpis = $("#marketplace-kpis");
    if (kpis) {
      kpis.innerHTML =
        mkKPI("Toplam", summary.total || 0) +
        mkKPI("Kategori", (summary.categories || []).length || 0) +
        mkKPI("Sorgu", summary.query ? 1 : 0);
    }

    var root = $("#marketplace-list");
    if (!root) return;
    var listings = Array.isArray(summary.listings) ? summary.listings : [];
    if (!listings.length) {
      root.innerHTML = '<div class="empty">Marketplace sonucu yok.</div>';
      return;
    }
    root.innerHTML = listings.slice(0, 8).map(function (item) {
      var hasUrl = !!item.download_url;
      return (
        '<div class="stack-item">' +
          '<div class="mission-meta" style="margin-top:0;margin-bottom:6px">' +
            '<span>' + esc(item.category || "custom") + '</span>' +
            '<span>' + esc(String(item.rating || 0)) + '</span>' +
            '<span>' + esc(String(item.downloads || 0)) + ' indirme</span>' +
          '</div>' +
          '<strong>' + esc(item.name || "Skill") + '</strong>' +
          '<p>' + esc(item.description || "") + '</p>' +
          '<div class="mission-meta">' +
            '<span>' + esc(item.author || "unknown") + '</span>' +
            '<span>' + esc(item.updated_at || "-") + '</span>' +
          '</div>' +
          '<div class="btn-row">' +
            (hasUrl ? '<button class="btn btn-p btn-sm js-market-install" data-url="' + esc(item.download_url) + '" data-name="' + esc(item.name || "") + '">Kur</button>' : '') +
          '</div>' +
        '</div>'
      );
    }).join("");

    root.querySelectorAll(".js-market-install").forEach(function (btn) {
      btn.addEventListener("click", function () {
        installMarketplaceSkill(btn.getAttribute("data-url"), btn.getAttribute("data-name"), btn);
      });
    });
  }

  function loadMarketplace(query) {
    var q = typeof query === "string" ? query : String((marketplaceState && marketplaceState.query) || "");
    marketplaceState.query = q.trim();
    var url = "/api/marketplace/browse?sort=rating";
    if (marketplaceState.query) {
      url += "&q=" + encodeURIComponent(marketplaceState.query);
    }
    return Promise.all([
      GET(url),
      GET("/api/marketplace/categories")
    ]).then(function (results) {
      var data = results[0] || {};
      var catData = results[1] || {};
      marketplaceState.listings = Array.isArray(data.listings) ? data.listings : [];
      marketplaceState.categories = Array.isArray(catData.categories) ? catData.categories : [];
      marketplaceState.total = Number(data.total || marketplaceState.listings.length || 0);
      renderMarketplace();
    });
  }

  function installMarketplaceSkill(url, name, btn) {
    var button = btn || null;
    if (button) {
      button.disabled = true;
      button.textContent = "Kuruluyor...";
    }
    POST("/api/marketplace/install", { url: url }).then(function (res) {
      if (res && res.ok) {
        toast((name || "Skill") + " kuruldu", "ok");
        refreshSkillRegistry().then(function () {
          return loadMarketplace(marketplaceState.query || "");
        });
      } else {
        toast((res && res.error) || "Kurulum basarisiz", "err");
      }
      if (button) {
        button.disabled = false;
        button.textContent = "Kur";
      }
    });
  }

  /* ================================================================
     INTEGRATIONS
     ================================================================ */
  function integrationProviderPresetScopes(provider) {
    var map = {
      google: "gmail.read, calendar.read, drive.read, docs.read, sheets.read, slides.read, chat.read",
      gmail: "email.read, email.send",
      calendar: "calendar.read, calendar.write",
      drive: "drive.read, drive.write",
      docs: "docs.read, docs.write",
      sheets: "sheets.read, sheets.write",
      slides: "slides.read, slides.write",
      chat: "chat.read, chat.write",
      x: "x.read, x.write",
      instagram: "instagram.read, instagram.write",
      whatsapp: "whatsapp.read, whatsapp.write",
      email: "email.read, email.send",
      scheduler: "calendar.read, calendar.write"
    };
    return map[String(provider || "").toLowerCase()] || "";
  }

  function integrationQuickConnectPlan(appName) {
    var key = String(appName || "").trim().toLowerCase();
    var map = {
      google: { provider: "google", scopes: "gmail.read, calendar.read, drive.read, docs.read, sheets.read, slides.read, chat.read" },
      gmail: { provider: "google", scopes: "email.read, email.send" },
      "google calendar": { provider: "google", scopes: "calendar.read, calendar.write" },
      "google drive": { provider: "google", scopes: "drive.read, drive.write" },
      "google docs": { provider: "google", scopes: "docs.read, docs.write" },
      "google sheets": { provider: "google", scopes: "sheets.read, sheets.write" },
      "google slides": { provider: "google", scopes: "slides.read, slides.write" },
      "google chat": { provider: "google", scopes: "chat.read, chat.write" },
      whatsapp: { provider: "whatsapp", scopes: "whatsapp.read, whatsapp.write" },
      instagram: { provider: "instagram", scopes: "instagram.read, instagram.write" },
      x: { provider: "x", scopes: "x.read, x.write" }
    };
    return map[key] || { provider: "", scopes: "" };
  }

  function integrationProviderBadge(provider) {
    var key = String(provider || "").trim().toLowerCase();
    var glyphMap = {
      google: "G",
      gmail: "G",
      calendar: "C",
      drive: "D",
      docs: "D",
      sheets: "S",
      slides: "S",
      chat: "C",
      whatsapp: "W",
      instagram: "I",
      x: "X",
      email: "E",
      scheduler: "S"
    };
    var glyph = glyphMap[key] || (key ? key.charAt(0).toUpperCase() : "?");
    return '<span class="integration-logo ' + esc(key || "google") + '">' + esc(glyph) + "</span>";
  }

  function integrationConnectEndpoint() {
    return ["/api/integrations/connect", "/api/integrations/accounts/connect"];
  }

  function postIntegrationConnect(payload) {
    var endpoints = integrationConnectEndpoint();
    function attempt(index, lastError) {
      if (index >= endpoints.length) {
        return Promise.resolve({ ok: false, error: lastError || "Bağlantı kurulamadı" });
      }
      return POST(endpoints[index], payload).then(function (res) {
        if (res && res.ok) {
          res._endpoint = endpoints[index];
          return res;
        }
        if (index + 1 < endpoints.length) {
          return attempt(index + 1, (res && res.error) || lastError || "Bağlantı kurulamadı");
        }
        return res;
      }).catch(function (err) {
        if (index + 1 < endpoints.length) {
          return attempt(index + 1, (err && err.message) || lastError || "Bağlantı kurulamadı");
        }
        return { ok: false, error: (err && err.message) || "Bağlantı kurulamadı" };
      });
    }
    return attempt(0, "");
  }

  function renderIntegrationKPIs() {
    var el = $("#integration-kpis");
    if (!el) return;
    var accounts = Array.isArray(integrationState.accounts) ? integrationState.accounts : [];
    var traces = Array.isArray(integrationState.traces) ? integrationState.traces : [];
    var readyAccounts = accounts.filter(function (item) { return String(item.status || "").toLowerCase() === "ready"; }).length;
    var needsInput = accounts.filter(function (item) { return String(item.status || "").toLowerCase() === "needs_input"; }).length;
    var fallbackCount = traces.filter(function (item) { return !!item.fallback_used; }).length;
    el.innerHTML =
      mkKPI("Hesaplar", accounts.length) +
      mkKPI("Hazır", readyAccounts) +
      mkKPI("Needs input", needsInput) +
      mkKPI("Fallback", fallbackCount);
    renderInvestorHero();
  }

  function renderIntegrationAccounts() {
    var root = $("#integration-accounts");
    var note = $("#integration-auth-note");
    if (!root) return;
    var accounts = Array.isArray(integrationState.accounts) ? integrationState.accounts : [];
    if (!accounts.length) {
      root.innerHTML = '<div class="empty">Bağlı hesap yok. OAuth / API ile bağla.</div>';
      if (note) note.textContent = "Bağlı hesap bulunamadı.";
      return;
    }
    root.innerHTML = accounts.map(function (account) {
      var status = String(account.status || "").toLowerCase();
      var tone = status === "ready" ? "ok" : (status === "blocked" || status === "failed" ? "err" : "warn");
      var scopes = Array.isArray(account.granted_scopes) ? account.granted_scopes : [];
      return (
        '<div class="integration-account">' +
          '<div class="trace-meta">' +
            '<span>' + integrationProviderBadge(account.provider || "-") + ' ' + esc(account.provider || "-") + '</span>' +
            '<span>' + esc(account.account_alias || "default") + '</span>' +
            '<span class="pill ' + tone + '">' + esc(account.status || "-") + '</span>' +
          '</div>' +
          '<strong>' + esc(account.display_name || account.email || account.provider || "Account") + '</strong>' +
          '<div class="meta">' + esc(account.email || account.auth_url || "—") + '</div>' +
          '<div class="meta">Scopes: ' + esc(scopes.join(", ") || "—") + '</div>' +
          '<div class="meta">Fallback: ' + esc(account.fallback_mode || "-") + '</div>' +
          '<div class="btn-row">' +
            '<button class="btn btn-s btn-sm js-integration-revoke" data-provider="' + esc(account.provider || "") + '" data-alias="' + esc(account.account_alias || "default") + '">Revoke</button>' +
          '</div>' +
        '</div>'
      );
    }).join("");
    root.querySelectorAll(".js-integration-revoke").forEach(function (btn) {
      btn.addEventListener("click", function () {
        revokeIntegrationAccount(btn.getAttribute("data-provider"), btn.getAttribute("data-alias"));
      });
    });
    if (note) {
      var first = accounts[0] || {};
      note.textContent = String(first.status || "needs_input") === "ready"
        ? (first.display_name || first.provider || "Hazır")
        : ((first.auth_url || "OAuth gerekir"));
    }
  }

  function renderIntegrationTraces() {
    var root = $("#integration-traces");
    var kpis = $("#integration-trace-kpis");
    if (kpis) {
      var traces = Array.isArray(integrationState.traces) ? integrationState.traces : [];
      kpis.innerHTML =
        mkKPI("Toplam", traces.length) +
        mkKPI("Fallback", traces.filter(function (t) { return !!t.fallback_used; }).length) +
        mkKPI("Başarılı", traces.filter(function (t) { return !!t.success; }).length) +
        mkKPI("Latency", traces.length ? Math.round(traces.reduce(function (a, t) { return a + Number(t.latency_ms || 0); }, 0) / traces.length) + " ms" : "-");
    }
    if (!root) return;
    var tracesList = Array.isArray(integrationState.traces) ? integrationState.traces : [];
    if (!tracesList.length) {
      root.innerHTML = '<div class="empty">Trace yok. Bir hesap bağla veya bir entegrasyon çalıştır.</div>';
      return;
    }
    root.innerHTML = tracesList.map(function (item) {
      var tone = item.success ? "ok" : (item.fallback_used ? "warn" : "err");
      var providerHtml = integrationProviderBadge(item.provider || "-") + ' <span>' + esc(item.provider || "-") + '</span>';
      var meta = [
        providerHtml,
        '<span>' + esc(item.connector_name || "-") + '</span>',
        '<span>' + esc(item.integration_type || "-") + '</span>'
      ].join(" • ");
      var details = [
        "auth=" + (item.auth_state || "-"),
        "fallback=" + (item.fallback_reason || "-"),
        "latency=" + (item.latency_ms ? Math.round(Number(item.latency_ms)) + "ms" : "-"),
        "retry=" + (item.retry_count || 0)
      ].join(" • ");
      var evidence = Array.isArray(item.evidence) ? item.evidence.length : 0;
      var artifacts = Array.isArray(item.artifacts) ? item.artifacts.length : 0;
      return (
        '<div class="trace-item">' +
          '<div class="trace-meta">' +
            '<span>' + meta + '</span>' +
            '<span class="pill ' + tone + '">' + esc(item.status || (item.success ? "success" : "failed")) + '</span>' +
          '</div>' +
          '<strong>' + esc(item.operation || "connector") + '</strong>' +
          '<div class="meta">' + esc(details) + '</div>' +
          '<div class="meta">evidence: ' + esc(evidence) + ' • artifacts: ' + esc(artifacts) + ' • ' + esc(item.session_id || "") + '</div>' +
        '</div>'
      );
    }).join("");
  }

  function renderIntegrationSummary() {
    var root = $("#integration-summary");
    if (!root) return;
    var summary = integrationState.summary && integrationState.summary.detail ? integrationState.summary.detail : {};
    var accounts = summary.accounts || {};
    var traces = summary.traces || {};
    var accountCounts = accounts.counts || {};
    var statusCounts = traces.by_status || {};
    var providerCounts = traces.by_provider || {};
    var recent = Array.isArray(traces.recent) ? traces.recent : [];
    var lines = [];
    lines.push('<div class="integration-account"><strong>Accounts</strong><div class="meta">provider: ' + esc(accounts.provider || integrationState.provider || "-") + ' • total: ' + esc(accounts.total || 0) + '</div><div class="meta">counts: ' + esc(Object.keys(accountCounts).map(function (k) { return k + "=" + accountCounts[k]; }).join(", ") || "-") + '</div></div>');
    lines.push('<div class="integration-account"><strong>Traces</strong><div class="meta">total: ' + esc(traces.total || 0) + ' • avg latency: ' + esc((traces.avg_latency_ms != null ? traces.avg_latency_ms : "-")) + ' ms</div><div class="meta">fallback: ' + esc(traces.fallback_count || 0) + '</div></div>');
    lines.push('<div class="integration-account"><strong>Trace Distribution</strong><div class="meta">by provider: ' + esc(Object.keys(providerCounts).map(function (k) { return k + "=" + providerCounts[k]; }).join(", ") || "-") + '</div><div class="meta">by status: ' + esc(Object.keys(statusCounts).map(function (k) { return k + "=" + statusCounts[k]; }).join(", ") || "-") + '</div></div>');
    if (recent.length) {
      lines.push('<div class="integration-account"><strong>Recent Trace</strong><div class="meta">' + esc((recent[0].provider || "-") + ":" + (recent[0].connector_name || "-") + " " + (recent[0].operation || "connector")) + '</div><div class="meta">' + esc((recent[0].status || (recent[0].success ? "success" : "failed")) + " • " + (recent[0].fallback_reason || "no fallback")) + '</div></div>');
    }
    root.innerHTML = lines.join("");
  }

  function renderAutopilot() {
    var kpis = $("#autopilot-kpis");
    var summary = $("#autopilot-summary");
    var btnStart = $("#autopilot-start");
    var btnStop = $("#autopilot-stop");
    var btnTick = $("#autopilot-tick");
    var running = !!(autopilotState || {}).running;
    if (kpis) {
      kpis.innerHTML =
        mkKPI("Durum", running ? "aktif" : "pasif") +
        mkKPI("Tick", autopilotState.tick_count || 0) +
        mkKPI("Son tick", autopilotState.last_tick_reason || "-") +
        mkKPI("Eylem", (autopilotState.last_actions || []).length || 0);
    }
    if (summary) {
      var actions = Array.isArray(autopilotState.last_actions) ? autopilotState.last_actions : [];
      var maintenance = autopilotState.maintenance || {};
      var predictive = autopilotState.predictive || {};
      var automation = autopilotState.automation || {};
      var lines = [];
      lines.push('<div class="integration-account"><strong>Runtime</strong><div class="meta">running: ' + esc(String(running)) + ' • enabled: ' + esc(String(!!autopilotState.enabled)) + '</div><div class="meta">last tick: ' + esc(autopilotState.last_tick_reason || "-") + '</div></div>');
      lines.push('<div class="integration-account"><strong>Maintenance</strong><div class="meta">freed: ' + esc(maintenance.total_freed_mb != null ? maintenance.total_freed_mb : "-") + 'MB • tasks: ' + esc(maintenance.tasks_completed != null ? maintenance.tasks_completed : "-") + '</div></div>');
      lines.push('<div class="integration-account"><strong>Predictive</strong><div class="meta">monitoring: ' + esc(predictive.monitoring_active != null ? String(predictive.monitoring_active) : "-") + ' • predictions: ' + esc(predictive.active_predictions != null ? predictive.active_predictions : "-") + '</div></div>');
      lines.push('<div class="integration-account"><strong>Automation</strong><div class="meta">healthy: ' + esc((automation.summary && automation.summary.healthy) != null ? automation.summary.healthy : "-") + ' • failing: ' + esc((automation.summary && automation.summary.failing) != null ? automation.summary.failing : "-") + '</div></div>');
      if (actions.length) {
        lines.push('<div class="integration-account"><strong>Recent Actions</strong><div class="meta">' + esc(actions.slice(0, 3).map(function (item) {
          return (item.kind || "action") + ":" + (item.status || "-");
        }).join(" • ")) + '</div></div>');
      }
      summary.innerHTML = lines.join("");
    }
    if (btnStart) btnStart.disabled = running;
    if (btnStop) btnStop.disabled = !running;
    if (btnTick) btnTick.disabled = false;
    renderInvestorHero();
  }

  function loadIntegrationAccounts() {
    var provider = String((document.getElementById("integration-provider") || {}).value || "google");
    integrationState.provider = provider;
    return GET("/api/integrations/accounts?provider=" + encodeURIComponent(provider)).then(function (data) {
      integrationState.accounts = Array.isArray(data.accounts) ? data.accounts : [];
      integrationState.summary.accounts_total = Number(data.total || integrationState.accounts.length || 0);
      renderIntegrationKPIs();
      renderIntegrationAccounts();
    });
  }

  function loadIntegrationTraces(filterValue) {
    var raw = typeof filterValue === "string" ? filterValue : String((document.getElementById("integration-trace-filter") || {}).value || "");
    var parts = raw.trim().split(/\s+/).filter(Boolean);
    var params = ["limit=50"];
    if (parts[0]) params.push("provider=" + encodeURIComponent(parts[0]));
    if (parts[1]) params.push("connector_name=" + encodeURIComponent(parts[1]));
    if (parts[2]) params.push("user_id=" + encodeURIComponent(parts[2]));
    return GET("/api/integrations/traces?" + params.join("&")).then(function (data) {
      integrationState.traces = Array.isArray(data.traces) ? data.traces : [];
      integrationState.summary.trace_total = Number(data.total || integrationState.traces.length || 0);
      integrationState.summary.fallback_count = data.summary && data.summary.fallback_count ? Number(data.summary.fallback_count) : integrationState.traces.filter(function (item) { return !!item.fallback_used; }).length;
      renderIntegrationKPIs();
      renderIntegrationTraces();
    });
  }

  function loadIntegrationSummary() {
    var provider = String(integrationState.provider || (document.getElementById("integration-provider") || {}).value || "google");
    return GET("/api/integrations/summary?provider=" + encodeURIComponent(provider)).then(function (data) {
      integrationState.summary.detail = data && data.ok ? data : {};
      renderIntegrationSummary();
      return data;
    });
  }

  function refreshIntegrations() {
    return Promise.all([loadIntegrationAccounts(), loadIntegrationTraces(), loadIntegrationSummary()]);
  }

  function loadAutopilot() {
    return GET("/api/autopilot/status").then(function (data) {
      autopilotState = data && data.ok ? data : (data || {});
      renderAutopilot();
      return data;
    });
  }

  function startAutopilot() {
    return POST("/api/autopilot/start", {}).then(function (data) {
      if (data && data.ok) {
        toast("Autopilot başlatıldı", "ok");
      } else {
        toast((data && data.error) || "Autopilot başlatılamadı", "err");
      }
      return loadAutopilot();
    });
  }

  function stopAutopilot() {
    return POST("/api/autopilot/stop", {}).then(function (data) {
      if (data && data.ok) {
        toast("Autopilot durduruldu", "info");
      } else {
        toast((data && data.error) || "Autopilot durdurulamadı", "err");
      }
      return loadAutopilot();
    });
  }

  function tickAutopilot() {
    return POST("/api/autopilot/tick", { reason: "dashboard_manual" }).then(function (data) {
      if (data && data.ok) {
        toast("Autopilot tick çalıştı", "ok");
      } else {
        toast((data && data.error) || "Autopilot tick çalışmadı", "err");
      }
      return loadAutopilot();
    });
  }

  /* ================================================================
     CHANNELS
     ================================================================ */
  function selectedChannelItem() {
    var items = Array.isArray(channelState.items) ? channelState.items : [];
    if (channelState.selectedId) {
      for (var i = 0; i < items.length; i++) {
        if (String(items[i].id || items[i].type || "") === String(channelState.selectedId)) {
          return items[i];
        }
      }
    }
    if (channelState.isDraft) {
      return null;
    }
    if (channelState.selectedType) {
      for (var j = 0; j < items.length; j++) {
        if (normalizeChannelType(items[j].type) === normalizeChannelType(channelState.selectedType)) {
          return items[j];
        }
      }
      return null;
    }
    return items.length ? items[0] : null;
  }

  function channelActionTone(item) {
    if (!item) return "warn";
    if (item.connected) return "ok";
    if (item.enabled) return "warn";
    return "warn";
  }

  function renderChannelsKPIs() {
    var items = Array.isArray(channelState.items) ? channelState.items : [];
    var total = items.length;
    var enabled = items.filter(function (item) { return !!item.enabled; }).length;
    var connected = items.filter(function (item) { return !!item.connected; }).length;
    var degraded = items.filter(function (item) { return !!item.enabled && !item.connected; }).length;
    channelState.summary = { total: total, enabled: enabled, connected: connected, degraded: degraded };
    var el = $("#channel-kpis");
    if (el) {
      el.innerHTML =
        mkKPI("Toplam", total) +
        mkKPI("Enabled", enabled) +
        mkKPI("Connected", connected) +
        mkKPI("Degraded", degraded);
    }
    renderInvestorHero();
  }

  function renderChannelCatalog() {
    var root = $("#channel-catalog");
    if (!root) return;
    var catalog = Array.isArray(channelState.catalog) ? channelState.catalog : [];
    if (!catalog.length) {
      root.innerHTML = '<div class="channel-empty">Catalog yüklenemedi.</div>';
      return;
    }
    root.innerHTML = catalog.map(function (item) {
      var fieldCount = Array.isArray(item.fields) ? item.fields.length : 0;
      return (
        '<article class="channel-catalog-item">' +
          '<div class="channel-list-top">' +
            '<div>' +
              '<strong>' + esc(item.label || item.type || "Channel") + '</strong>' +
              '<div class="channel-note">' + esc(item.notes || "") + '</div>' +
            '</div>' +
            '<span class="pill warn">' + esc(fieldCount) + ' fields</span>' +
          '</div>' +
          '<div class="channel-list-meta">' +
            '<span>' + esc(item.type || "-") + '</span>' +
            '<span>' + esc(fieldCount) + ' field</span>' +
          '</div>' +
          '<div class="btn-row">' +
            '<button class="btn btn-p btn-sm js-channel-new" data-type="' + esc(item.type || "") + '">Yeni</button>' +
          '</div>' +
        '</article>'
      );
    }).join("");
    root.querySelectorAll(".js-channel-new").forEach(function (btn) {
      btn.addEventListener("click", function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        startChannelDraft(btn.getAttribute("data-type"));
      });
    });
  }

  function renderChannelList() {
    var root = $("#channel-list");
    if (!root) return;
    var items = Array.isArray(channelState.items) ? channelState.items : [];
    if (!items.length) {
      root.innerHTML = '<div class="channel-empty">Henüz kanal yok. Catalog’dan yeni kanal ekle.</div>';
      return;
    }
    root.innerHTML = items.map(function (item) {
      var active = String(item.id || item.type || "") === String(channelState.selectedId || "");
      var tone = channelActionTone(item);
      var statusText = item.connected ? "connected" : (item.enabled ? "enabled" : "disabled");
      var metrics = item.message_metrics || {};
      var meta = [
        "status: " + String(item.status || "-"),
        "fail: " + String(item.failure_rate_pct != null ? item.failure_rate_pct + "%" : "-"),
        "last: " + String(item.last_activity || "-")
      ];
      return (
        '<article class="channel-list-item' + (active ? " active" : "") + '" data-channel-id="' + esc(item.id || item.type || "") + '">' +
          '<div class="channel-list-top">' +
            '<div>' +
              '<strong>' + esc(channelItemLabel(item)) + '</strong>' +
              '<div class="channel-list-meta">' + meta.map(function (value) { return '<span>' + esc(value) + '</span>'; }).join("") + '</div>' +
            '</div>' +
            '<span class="pill ' + tone + '">' + esc(statusText) + '</span>' +
          '</div>' +
          '<div class="channel-list-meta">' +
            '<span>recv ' + esc(metrics.received || 0) + '</span>' +
            '<span>sent ' + esc(metrics.sent || 0) + '</span>' +
            '<span>errors ' + esc((metrics.send_failures || 0) + (metrics.processing_errors || 0)) + '</span>' +
          '</div>' +
          '<div class="btn-row">' +
            '<button class="btn btn-s btn-sm js-channel-edit" data-channel-id="' + esc(item.id || item.type || "") + '">Edit</button>' +
            '<button class="btn btn-s btn-sm js-channel-test" data-channel-id="' + esc(item.id || item.type || "") + '">Test</button>' +
            '<button class="btn btn-s btn-sm js-channel-toggle" data-channel-id="' + esc(item.id || item.type || "") + '" data-enabled="' + esc(!item.enabled) + '">' + (item.enabled ? "Disable" : "Enable") + '</button>' +
            '<button class="btn btn-d btn-sm js-channel-delete" data-channel-id="' + esc(item.id || item.type || "") + '">Delete</button>' +
          '</div>' +
        '</article>'
      );
    }).join("");
    root.querySelectorAll(".channel-list-item").forEach(function (card) {
      card.addEventListener("click", function () {
        selectChannel(card.getAttribute("data-channel-id"));
      });
    });
    root.querySelectorAll(".js-channel-edit").forEach(function (btn) {
      btn.addEventListener("click", function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        selectChannel(btn.getAttribute("data-channel-id"));
      });
    });
    root.querySelectorAll(".js-channel-test").forEach(function (btn) {
      btn.addEventListener("click", function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        testChannel(btn.getAttribute("data-channel-id"));
      });
    });
    root.querySelectorAll(".js-channel-toggle").forEach(function (btn) {
      btn.addEventListener("click", function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        toggleChannel(btn.getAttribute("data-channel-id"), String(btn.getAttribute("data-enabled")) === "true");
      });
    });
    root.querySelectorAll(".js-channel-delete").forEach(function (btn) {
      btn.addEventListener("click", function (evt) {
        evt.preventDefault();
        evt.stopPropagation();
        deleteChannel(btn.getAttribute("data-channel-id"));
      });
    });
  }

  function renderChannelEditor() {
    var typeSelect = $("#channel-type");
    var idInput = $("#channel-id");
    var enabledInput = $("#channel-enabled");
    var statusEl = $("#channel-editor-status");
    var notesEl = $("#channel-notes");
    var fieldsRoot = $("#channel-field-list");
    if (!typeSelect || !idInput || !enabledInput || !statusEl || !notesEl || !fieldsRoot) return;

    var catalog = Array.isArray(channelState.catalog) ? channelState.catalog : [];
    if (!catalog.length) {
      typeSelect.innerHTML = '<option value="">Loading...</option>';
      fieldsRoot.innerHTML = '<div class="channel-empty">Channel catalog yükleniyor.</div>';
      notesEl.textContent = "Catalog bekleniyor.";
      return;
    }

    var current = selectedChannelItem();
    var type = normalizeChannelType(channelState.selectedType || (current && current.type) || catalog[0].type);
    var currentCatalog = channelCatalogEntry(type) || catalog[0];
    if (!channelState.selectedType) {
      channelState.selectedType = type;
    }

    typeSelect.innerHTML = catalog.map(function (item) {
      return '<option value="' + esc(item.type || "") + '">' + esc((item.label || item.type || "Channel") + " — " + (item.type || "")) + '</option>';
    }).join("");
    typeSelect.value = type;

    var editingId = String(channelState.selectedId || (current && (current.id || current.type)) || "");
    var editingExisting = !!editingId && !!current;
    if (editingExisting) {
      idInput.value = String(current.id || current.type || type);
      enabledInput.checked = !!current.enabled;
      statusEl.textContent = "Editing";
      statusEl.className = "pill " + channelActionTone(current);
    } else {
      if (!idInput.value || String(idInput.value).trim() === "") {
        idInput.value = type;
      }
      enabledInput.checked = true;
      statusEl.textContent = "New";
      statusEl.className = "pill warn";
    }

    notesEl.textContent = String(currentCatalog && currentCatalog.notes ? currentCatalog.notes : "Secret alanları boş bırakırsan mevcut değer korunur.");

    var fieldHtml = [];
    var fields = Array.isArray(currentCatalog && currentCatalog.fields) ? currentCatalog.fields : [];
    fields.forEach(function (field) {
      if (!field || field.name === "id") return;
      var name = String(field.name || "").trim();
      if (!name) return;
      var fieldId = channelFieldInputId(name);
      var secret = !!field.secret;
      var required = !!field.required;
      var currentValue = channelFieldValue(current || {}, field);
      var inputType = secret ? "password" : ((/port$/i.test(name) || /_port$/i.test(name)) ? "number" : "text");
      var hint = secret ? "Boş bırakmak mevcut değeri korur." : (required ? "Zorunlu alan." : "Opsiyonel.");
      var inputHtml = "";
      if (type === "whatsapp" && name === "mode") {
        inputHtml =
          '<select class="sel" id="' + esc(fieldId) + '">' +
            '<option value="bridge">bridge</option>' +
            '<option value="cloud">cloud</option>' +
          '</select>';
      } else {
        inputHtml = '<input class="sel" id="' + esc(fieldId) + '" type="' + esc(inputType) + '" placeholder="' + esc(field.label || name) + '" />';
      }
      fieldHtml.push(
        '<label class="field">' +
          '<span class="field-label">' + esc(field.label || name) + '</span>' +
          inputHtml +
          '<span class="field-hint">' + esc(hint) + '</span>' +
        '</label>'
      );
    });
    fieldsRoot.innerHTML = fieldHtml.length ? fieldHtml.join("") : '<div class="channel-empty">Bu kanal tipi için ekstra alan yok.</div>';

    fields.forEach(function (field) {
      if (!field || field.name === "id") return;
      var name = String(field.name || "").trim();
      var el = document.getElementById(channelFieldInputId(name));
      if (!el) return;
      if (type === "whatsapp" && name === "mode") {
        el.value = String((current || {}).mode || "bridge");
      } else if (!field.secret) {
        el.value = channelFieldValue(current || {}, field);
      } else {
        el.value = "";
      }
    });
  }

  function selectChannel(channelId) {
    var items = Array.isArray(channelState.items) ? channelState.items : [];
    var found = null;
    for (var i = 0; i < items.length; i++) {
      if (String(items[i].id || items[i].type || "") === String(channelId || "")) {
        found = items[i];
        break;
      }
    }
    if (found) {
      channelState.selectedId = String(found.id || found.type || "");
      channelState.selectedType = String(found.type || channelState.selectedType || "");
      channelState.isDraft = false;
    } else {
      channelState.selectedId = "";
      if (channelId) {
        channelState.selectedType = String(channelId);
      }
      channelState.isDraft = true;
    }
    renderChannelList();
    renderChannelEditor();
  }

  function startChannelDraft(type) {
    channelState.selectedId = "";
    channelState.selectedType = normalizeChannelType(type || channelState.selectedType || (channelState.catalog[0] && channelState.catalog[0].type) || "");
    channelState.isDraft = true;
    renderChannelList();
    renderChannelEditor();
  }

  function readChannelDraft() {
    var type = normalizeChannelType((document.getElementById("channel-type") || {}).value || channelState.selectedType || "");
    var catalog = channelCatalogEntry(type) || { fields: [] };
    var id = String((document.getElementById("channel-id") || {}).value || "").trim() || type;
    var enabled = !!((document.getElementById("channel-enabled") || {}).checked);
    var payload = {
      type: type,
      id: id,
      enabled: enabled
    };
    (catalog.fields || []).forEach(function (field) {
      if (!field || field.name === "id") return;
      var name = String(field.name || "").trim();
      if (!name) return;
      var el = document.getElementById(channelFieldInputId(name));
      if (!el) return;
      var value = String(el.value || "").trim();
      if (!value) {
        return;
      }
      if (el.type === "number") {
        var numeric = Number(value);
        if (!Number.isNaN(numeric)) {
          payload[name] = numeric;
          return;
        }
      }
      payload[name] = value;
    });
    return { channel: payload, clear_secret_fields: [] };
  }

  function saveChannel() {
    var draft = readChannelDraft();
    var current = selectedChannelItem();
    if (!draft.channel.type) {
      toast("Channel type gerekli", "err");
      return Promise.resolve({ ok: false });
    }
    if (!draft.channel.id) {
      toast("Channel id gerekli", "err");
      return Promise.resolve({ ok: false });
    }
    var saveBtn = $("#channel-save");
    if (saveBtn) saveBtn.disabled = true;
    if (current && !channelState.isDraft) {
      draft.original_id = String(current.id || current.type || "");
      draft.original_type = String(current.type || "");
    }
    return POST("/api/channels/upsert", draft).then(function (res) {
      if (res && res.ok) {
        toast((res.channel && (res.channel.id || res.channel.type)) + " kaydedildi", "ok");
        channelState.selectedId = String((res.channel && (res.channel.id || res.channel.type)) || draft.channel.id);
        channelState.selectedType = String((res.channel && res.channel.type) || draft.channel.type);
        channelState.isDraft = false;
        return loadChannels();
      }
      toast((res && res.error) || "Channel kaydedilemedi", "err");
      return res;
    }).finally(function () {
      if (saveBtn) saveBtn.disabled = false;
    });
  }

  function toggleChannel(channelId, enabled) {
    if (!channelId) {
      toast("Channel seç", "err");
      return Promise.resolve();
    }
    return POST("/api/channels/toggle", { id: channelId, enabled: !!enabled }).then(function (res) {
      if (res && res.ok) {
        toast(channelId + " " + (enabled ? "enabled" : "disabled"), "ok");
        return loadChannels();
      }
      toast((res && res.error) || "Channel toggle başarısız", "err");
      return res;
    });
  }

  function deleteChannel(channelId) {
    if (!channelId) {
      toast("Channel seç", "err");
      return Promise.resolve();
    }
    if (!confirm(channelId + " silinsin mi?")) return Promise.resolve();
    return api("/api/channels/" + encodeURIComponent(channelId), { method: "DELETE", timeoutMs: timeoutMs }).then(function (res) {
      if (res && res.ok) {
        toast(channelId + " silindi", "info");
        if (String(channelState.selectedId || "") === String(channelId)) {
          channelState.selectedId = "";
          channelState.isDraft = false;
        }
        return loadChannels();
      }
      toast((res && res.error) || "Channel silinemedi", "err");
      return res;
    });
  }

  function testChannel(channelId) {
    var payload = {};
    if (channelId) {
      payload.channel = channelId;
    } else {
      payload.channel = "all";
    }
    return POST("/api/channels/test", payload).then(function (res) {
      if (res && res.ok) {
        toast(res.message || "Channel test tamamlandı", "ok");
      } else {
        toast((res && res.message) || (res && res.error) || "Channel test başarısız", "err");
      }
      return res;
    });
  }

  function syncChannels() {
    return POST("/api/channels/sync", {}).then(function (res) {
      if (res && res.ok) {
        toast("Channel runtime sync edildi", "ok");
        return loadChannels();
      }
      toast((res && res.message) || (res && res.error) || "Channel sync başarısız", "err");
      return res;
    });
  }

  function loadChannels() {
    return Promise.all([GET("/api/channels"), GET("/api/channels/catalog")]).then(function (results) {
      var data = results[0] || {};
      var catalogData = results[1] || {};
      channelState.items = Array.isArray(data.channels) ? data.channels : [];
      channelState.catalog = Array.isArray(catalogData.catalog) ? catalogData.catalog : [];
      if (channelState.selectedId) {
        var selectedExists = false;
        for (var i = 0; i < channelState.items.length; i++) {
          if (String(channelState.items[i].id || channelState.items[i].type || "") === String(channelState.selectedId)) {
            selectedExists = true;
            break;
          }
        }
        if (!selectedExists) {
          channelState.selectedId = channelState.items.length ? String(channelState.items[0].id || channelState.items[0].type || "") : "";
        }
        channelState.isDraft = false;
      }
      if (!channelState.selectedType) {
        channelState.selectedType = String((selectedChannelItem() && selectedChannelItem().type) || (channelState.catalog[0] && channelState.catalog[0].type) || "");
      }
      renderChannelsKPIs();
      renderChannelCatalog();
      renderChannelList();
      renderChannelEditor();
      return data;
    });
  }

  function connectIntegration(options) {
    var opts = options || {};
    var providerEl = $("#integration-provider");
    var aliasEl = $("#integration-account-alias");
    var scopesEl = $("#integration-scopes");
    var modeEl = $("#integration-mode");
    var codeEl = $("#integration-auth-code");
    var redirectEl = $("#integration-redirect-uri");
    var appEl = $("#integration-app");
    var appName = String(opts.appName || (appEl ? appEl.value : "") || "").trim();
    var inferredPlan = integrationQuickConnectPlan(appName);
    var provider = String(opts.provider || "").trim().toLowerCase();
    if (!provider && appName) {
      provider = String(inferredPlan.provider || "").trim().toLowerCase();
    }
    if (!provider && !appName && providerEl) {
      provider = String(providerEl.value || "google").trim().toLowerCase();
    }
    var scopesText = String(opts.scopes || (scopesEl ? scopesEl.value : "") || "");
    var scopes = scopesText.split(",").map(function (item) { return item.trim(); }).filter(Boolean);
    if (!scopes.length && inferredPlan.scopes) {
      scopes = String(inferredPlan.scopes).split(",").map(function (item) { return item.trim(); }).filter(Boolean);
    }
    var mode = modeEl ? modeEl.value : "auto";
    var requestPayload = {
      app_name: appName,
      provider: provider,
      account_alias: aliasEl ? aliasEl.value.trim() : "default",
      scopes: scopes,
      mode: mode,
      authorization_code: codeEl ? codeEl.value.trim() : "",
      redirect_uri: redirectEl ? redirectEl.value.trim() : "",
    };
    return postIntegrationConnect(requestPayload).then(function (res) {
      if (res && res.ok) {
        var account = res.account || {};
        if (res.needs_input && res.auth_url) {
          if ($("#integration-auth-note")) {
            $("#integration-auth-note").innerHTML =
              '<div class="empty">OAuth gerekiyor: <span class="code-box">' + esc(res.auth_url) + '</span></div>' +
              '<div class="muted-sm" style="margin-top:8px">Resolved: ' + esc(res.resolved_app_name || appName || provider) + ' → ' + esc(res.resolved_provider || provider) + '</div>' +
              '<div class="muted-sm">Endpoint: ' + esc(res._endpoint || integrationConnectEndpoint()[0]) + '</div>';
          }
          try {
            if (res.launch_url) {
              window.open(res.launch_url, "_blank", "noopener");
            }
          } catch (e) {}
          toast("OAuth bağlantısı başlatıldı", "info");
        } else {
          toast((res.resolved_app_name || account.provider || provider) + " bağlandı", "ok");
          if ($("#integration-auth-note")) {
            $("#integration-auth-note").textContent = String(res.resolved_app_name || account.provider || provider) + " → " + String(res.resolved_provider || provider) + " bağlandı";
          }
        }
        return refreshIntegrations();
      }
      toast((res && res.error) || "Bağlantı kurulamadı", "err");
      return loadIntegrationAccounts();
    });
  }

  function revokeIntegrationAccount(provider, alias) {
    if (!provider) {
      toast("Provider gerekli", "err");
      return Promise.resolve();
    }
    return POST("/api/integrations/accounts/revoke", {
      provider: provider,
      account_alias: alias || "default"
    }).then(function (res) {
      if (res && res.ok) {
        toast(provider + " hesabı kaldırıldı", "ok");
        return refreshIntegrations();
      }
      toast((res && res.error) || "Hesap kaldırılamadı", "err");
      return loadIntegrationAccounts();
    });
  }

  function updateMissionFilterButtons() {
    $$(".js-mission-filter").forEach(function (btn) {
      var active = String(btn.getAttribute("data-filter") || "all") === missionFilter;
      btn.classList.toggle("active", active);
    });
  }

  function loadMissionDetail() {
    var mission = currentMission();
    if (!mission) {
      renderMissionDetail(null);
      return Promise.resolve();
    }
    return GET("/api/missions/" + encodeURIComponent(mission.mission_id) + "?user_id=local").then(function (data) {
      if (data && data.ok && data.mission) {
        renderMissionDetail(data.mission);
      } else {
        renderMissionDetail(null);
      }
    });
  }

  function loadMissionControl() {
    return Promise.all([
      GET("/api/missions/overview?user_id=local"),
      GET("/api/missions?user_id=local&limit=12"),
      GET("/api/missions/approvals?user_id=local"),
      GET("/api/missions/skills"),
      GET("/api/missions/memory?user_id=local")
    ]).then(function (results) {
      missionState.overview = results[0] || {};
      missionState.missions = Array.isArray((results[1] || {}).missions) ? results[1].missions : [];
      missionState.approvals = Array.isArray((results[2] || {}).pending) ? results[2].pending : [];
      missionState.skills = Array.isArray((results[3] || {}).skills) ? results[3].skills : [];
      missionState.memory = (results[4] && results[4].ok) ? results[4] : { profile: [], workflow: [], task: [], evidence: [] };
      return ensureRequestedMissionVisible().then(function () {
        if (!missionState.selectedMissionId && missionState.missions.length) {
          missionState.selectedMissionId = missionState.missions[0].mission_id;
        }
        renderMissionKPIs();
        renderMissionList();
        renderMissionApprovals();
        renderMissionSkills();
        renderMissionMemory();
        return loadMissionDetail().then(function () {
          if (activeTab === "trace") {
            return loadTrace();
          }
        });
      });
    });
  }

  function submitMission(goal, mode, opts) {
    var resolvedGoal = String(goal || "").trim();
    if (!resolvedGoal) {
      toast("Mission hedefi bos olamaz", "err");
      return Promise.resolve({ ok: false });
    }
    var input = $("#mission-input");
    if (input && !opts) {
      input.value = resolvedGoal;
    }
    return POST("/api/missions", { goal: resolvedGoal, mode: String(mode || "Balanced"), user_id: "local", channel: "dashboard" }).then(function (res) {
      if (res && res.ok && res.mission) {
        missionState.selectedMissionId = res.mission.mission_id;
        toast("Mission baslatildi", "ok");
        if (!opts || opts.clearInput !== false) {
          if (input) input.value = "";
        }
        loadMissionControl();
      } else {
        toast(friendlyFailure((res || {}).error || "mission_create_failed"), "err");
      }
      return res;
    });
  }

  function createMission() {
    var input = $("#mission-input");
    var modeEl = $("#mission-mode");
    var goal = input ? input.value.trim() : "";
    return submitMission(goal, (modeEl && modeEl.value) || "Balanced");
  }

  function launchPackMission(pack, action) {
    var normalizedPack = String(pack || "").trim().toLowerCase();
    var normalizedAction = String(action || "").trim().toLowerCase();
    var packSpec = PACK_ACTIONS[normalizedPack];
    if (!packSpec || !packSpec[normalizedAction]) {
      toast("Pack aksiyonu bulunamadi", "err");
      return Promise.resolve({ ok: false });
    }
    var spec = packSpec[normalizedAction];
    var input = $("#mission-input");
    if (input) input.value = spec.prompt;
    return submitMission(spec.prompt, spec.mode, { clearInput: false });
  }

  function packDomId(pack, suffix) {
    return "pack-" + String(pack || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") + "-" + String(suffix || "").trim();
  }

  function packBadgeClass(status) {
    var low = String(status || "").toLowerCase();
    if (low === "success" || low === "ready" || low === "ok") return "ok";
    if (low === "partial" || low === "missing" || low === "warn") return "warn";
    return "err";
  }

  function renderPackStatusCard(item) {
    var pack = String(item && item.pack || "").trim();
    if (!pack) return;
    var statusEl = $("#" + packDomId(pack, "status"));
    var commandEl = $("#" + packDomId(pack, "command"));
    var rootEl = $("#" + packDomId(pack, "root"));
    var bundleEl = $("#" + packDomId(pack, "bundle"));
    var readinessEl = $("#" + packDomId(pack, "readiness"));
    var scoreEl = $("#" + packDomId(pack, "score"));
    var countEl = $("#" + packDomId(pack, "count"));
    var missingEl = $("#" + packDomId(pack, "missing"));
    var nextEl = $("#" + packDomId(pack, "next"));
    var featuresEl = $("#" + packDomId(pack, "features"));
    var commandsEl = $("#" + packDomId(pack, "commands"));

    var statusText = String(item.status || (item.success ? "ready" : "missing"));
    if (statusEl) {
      statusEl.textContent = statusText;
      statusEl.className = "pack-status-badge " + packBadgeClass(statusText);
    }
    if (commandEl) {
      commandEl.textContent = String(item.command || item.commands && item.commands.status || "");
    }
    if (rootEl) {
      rootEl.textContent = "root: " + String(item.root || (item.project && item.project.root) || "-");
    }
    if (bundleEl) {
      bundleEl.textContent = "bundle: " + String(item.bundle_id || (item.bundle && (item.bundle.id || item.bundle.workflow_id)) || "-");
    }
    if (readinessEl) {
      readinessEl.textContent = "readiness: " + String(item.readiness || (item.success ? "ready" : "missing"));
    }
    if (scoreEl) {
      var score = item.readiness_percent != null ? item.readiness_percent : 0;
      scoreEl.textContent = "score: " + String(score) + "%";
    }
    if (countEl) {
      countEl.textContent = "features: " + String(item.feature_count != null ? item.feature_count : 0);
    }
    if (missingEl) {
      var missing = Array.isArray(item.missing_features) ? item.missing_features : [];
      missingEl.textContent = missing.length ? "missing: " + missing.slice(0, 3).join(", ") : "missing: none";
    }
    if (nextEl) {
      nextEl.textContent = String(item.next_step || item.message || item.summary || "Live durum yok");
    }
    if (featuresEl) {
      var features = Array.isArray(item.feature_sample) ? item.feature_sample : [];
      featuresEl.innerHTML = features.length ? features.map(function (feature) {
        return "<span>" + esc(feature) + "</span>";
      }).join("") : "";
    }
    if (commandsEl) {
      var commands = item.commands && typeof item.commands === "object" ? item.commands : {};
      var labels = ["status", "project", "scaffold", "workflow", "ask", "query"];
      var chips = labels.map(function (key) {
        var command = String(commands[key] || "").trim();
        if (!command) return "";
        return '<button type="button" class="pack-command-chip js-copy-command" data-command="' + esc(command) + '">' + esc(key) + "</button>";
      }).filter(Boolean);
      var recommended = String(item.recommended_command || "").trim();
      if (recommended) {
        chips.unshift('<button type="button" class="pack-command-chip pack-command-highlight js-copy-command" data-command="' + esc(recommended) + '">recommended</button>');
      }
      commandsEl.innerHTML = chips.length ? chips.join("") : "";
      bindCopyCommandButtons(commandsEl);
    }
  }

  function applyPackOverview(payload) {
    var rows = Array.isArray(payload && payload.packs) ? payload.packs : [];
    packState.packs = rows;
    packState.lastLoadedAt = Date.now();
    rows.forEach(renderPackStatusCard);
    return rows;
  }

  function loadPackOverview(pack) {
    var target = String(pack || "all").trim().toLowerCase() || "all";
    return GET("/api/packs" + (target !== "all" ? "/" + encodeURIComponent(target) : "")).then(function (data) {
      if (data && data.ok) {
        applyPackOverview(data);
      }
      return data;
    });
  }

  function refreshPackOverview(pack) {
    return loadPackOverview(pack || "all");
  }

  function resolveMissionApproval(approvalId, approved) {
    POST("/api/missions/approvals/resolve", { id: approvalId, approved: approved }).then(function (res) {
      if (res && res.ok) {
        toast(approved ? "Approval onaylandi" : "Approval reddedildi", approved ? "ok" : "info");
        loadMissionControl();
      } else {
        toast((res && res.error) || "Approval guncellenemedi", "err");
      }
    });
  }

  function saveMissionSkill(missionId) {
    POST("/api/missions/skills/save", { mission_id: missionId }).then(function (res) {
      if (res && res.ok) {
        toast("Mission skill olarak kaydedildi", "ok");
        loadMissionControl();
      } else {
        toast((res && res.error) || "Skill kaydedilemedi", "err");
      }
    });
  }

  function currentTraceTaskId() {
    return String(traceState.taskId || missionState.selectedMissionId || requestedMissionId || initialTraceId || initialMissionId || "").trim();
  }

  function traceSummaryCard(label, value, detail) {
    var html = '<div class="stack-item"><strong>' + esc(label) + '</strong><p>' + esc(value) + '</p>';
    if (detail) {
      html += '<div class="muted-sm">' + esc(detail) + '</div>';
    }
    html += '</div>';
    return html;
  }

  function tracePreview(item) {
    var mediaKind = String((item || {}).media_kind || "").toLowerCase();
    var url = String((item || {}).url || "");
    var label = String((item || {}).label || item.kind || "Evidence");
    if (url && mediaKind === "image") {
      return '<img src="' + esc(url) + '" alt="' + esc(label) + '" class="trace-preview" loading="lazy" />';
    }
    if (url && mediaKind === "video") {
      return '<video src="' + esc(url) + '" controls class="trace-preview"></video>';
    }
    return '<div class="trace-preview-fallback">' + esc(String(mediaKind || (item && item.kind) || "FILE").toUpperCase()) + '</div>';
  }

  function traceEvidenceCard(item) {
    var meta = [];
    if (item.node_id) meta.push("node:" + item.node_id);
    if (item.mime_type) meta.push(item.mime_type);
    if (item.size_bytes) meta.push(String(item.size_bytes) + " bytes");
    var body = '<article class="trace-evidence-card">' + tracePreview(item) + '<div class="trace-evidence-body">';
    body += '<strong>' + esc(item.label || item.kind || "Evidence") + '</strong>';
    body += '<p>' + esc(item.summary || item.display_path || "") + '</p>';
    if (meta.length) {
      body += '<div class="trace-evidence-meta">' + esc(meta.join(" • ")) + '</div>';
    }
    if (item.url) {
      body += '<a href="' + esc(item.url) + '" target="_blank" rel="noreferrer" class="trace-link">Aç</a>';
    }
    body += '</div></article>';
    return body;
  }

  function traceTimelineCard(item) {
    return (
      '<div class="stack-item">' +
        '<strong>' + esc(item.label || item.event_type || item.kind || "event") + '</strong>' +
        '<p>' + esc(item.status || "") + ' • ' + esc(fmtDate(item.created_at)) + '</p>' +
      '</div>'
    );
  }

  function traceApprovalCard(item) {
    return (
      '<div class="stack-item">' +
        '<strong>' + esc(item.title || item.operation || "approval") + '</strong>' +
        '<p>' + esc(item.status || "") + '</p>' +
      '</div>'
    );
  }

  function renderTraceLive(items) {
    var root = $("#trace-live");
    if (!root) return;
    var rows = Array.isArray(items) ? items : traceState.live || [];
    if (!rows.length) {
      root.innerHTML = '<div class="empty">Live event yok.</div>';
      return;
    }
    root.innerHTML = rows.slice(-40).map(function (item) {
      var detail = item.detail;
      var detailText = typeof detail === "string" ? detail : JSON.stringify(detail || item, null, 2);
      return (
        '<div class="trace-live-item">' +
          '<strong>' + esc(item.label || item.type || "event") + '</strong>' +
          '<p>' + esc(item.status || "") + '</p>' +
          '<pre>' + esc(String(detailText || "").slice(0, 1200)) + '</pre>' +
        '</div>'
      );
    }).join("");
  }

  function traceMatchesCurrent(payload) {
    var wanted = currentTraceTaskId();
    if (!wanted) return true;
    if (!payload || typeof payload !== "object") return true;
    var ids = [payload.task_id, payload.mission_id, payload.request_id, payload.id];
    for (var i = 0; i < ids.length; i++) {
      if (ids[i] != null && String(ids[i]) === wanted) return true;
    }
    return !ids.some(function (value) { return value != null; });
  }

  function appendTraceLive(eventName, payload) {
    if (!traceMatchesCurrent(payload)) return;
    var entry = {
      label: String(eventName || (payload && payload.type) || "event"),
      status: String((payload && (payload.status || payload.state || payload.channel)) || ""),
      detail: payload
    };
    traceState.live = (traceState.live || []).concat([entry]).slice(-40);
    renderTraceLive(traceState.live);
  }

  function renderTraceView(bundle) {
    var trace = bundle || {};
    var history = trace.history || {};
    var evidence = Array.isArray(trace.evidence) ? trace.evidence : [];
    var timeline = Array.isArray(history.timeline) ? history.timeline : [];
    var approvals = Array.isArray(history.approvals) ? history.approvals : [];
    var live = Array.isArray(history.live_events) ? history.live_events : [];
    var taskId = String(trace.task_id || history.task_id || currentTraceTaskId() || "").trim();
    traceState.taskId = taskId;
    traceState.bundle = trace;
    traceState.evidence = evidence;
    traceState.live = live.slice(-40);

    var input = $("#trace-task-id");
    if (input) input.value = taskId;
    var openBtn = $("#trace-open-full");
    if (openBtn) {
      openBtn.disabled = !taskId;
    }

    var title = history.goal || history.skill_name || taskId || "Trace";
    document.title = "Elyan Trace • " + title;

    var kpis = $("#trace-kpis");
    if (kpis) {
      kpis.innerHTML =
        mkKPI("Status", history.status || "-") +
        mkKPI("Evidence", evidence.length || 0) +
        mkKPI("Approvals", approvals.length || 0) +
        mkKPI("Timeline", timeline.length || 0) +
        mkKPI("Controls", history.control && history.control.node_count != null ? history.control.node_count : (history.graph && history.graph.nodes ? history.graph.nodes.length : 0));
    }

    var summary = $("#trace-summary");
    if (summary) {
      summary.innerHTML =
        traceSummaryCard("Goal", history.goal || "-", history.skill_name || "") +
        traceSummaryCard("Route", history.route_mode || "-", history.mode || "") +
        traceSummaryCard("Risk", history.risk_profile || "-", history.status || "") +
        traceSummaryCard("Evidence file", String(evidence.filter(function (item) { return !!item.path; }).length || 0), "Artifact ready");
    }

    var decision = $("#trace-decision");
    if (decision) {
      decision.textContent = JSON.stringify(history.decision_trace || {}, null, 2);
    }

    var evidenceRoot = $("#trace-evidence");
    if (evidenceRoot) {
      evidenceRoot.innerHTML = evidence.length ? evidence.slice().reverse().map(traceEvidenceCard).join("") : '<div class="empty">Evidence yok.</div>';
    }

    var timelineRoot = $("#trace-timeline");
    if (timelineRoot) {
      timelineRoot.innerHTML = timeline.length ? timeline.slice().reverse().map(traceTimelineCard).join("") : '<div class="empty">Timeline yok.</div>';
    }

    var approvalsRoot = $("#trace-approvals");
    if (approvalsRoot) {
      approvalsRoot.innerHTML = approvals.length ? approvals.slice().reverse().map(traceApprovalCard).join("") : '<div class="empty">Approval yok.</div>';
    }

    renderTraceLive(traceState.live);
    renderInvestorHero();
  }

  function loadTrace(taskId) {
    var resolved = String(taskId || currentTraceTaskId() || "").trim();
    traceState.taskId = resolved;
    var input = $("#trace-task-id");
    if (input) input.value = resolved;
    if (!resolved) {
      renderTraceView({ task_id: "", history: { status: "missing", decision_trace: {} }, evidence: [] });
      return Promise.resolve();
    }
    return GET("/api/trace/" + encodeURIComponent(resolved)).then(function (data) {
      if (data && data.ok && data.trace) {
        renderTraceView(data.trace);
      } else {
        renderTraceView({ task_id: resolved, history: { status: "missing", decision_trace: {} }, evidence: [] });
      }
      return data;
    });
  }

  function openTraceTab(taskId) {
    var resolved = String(taskId || currentTraceTaskId() || "").trim();
    if (resolved) {
      traceState.taskId = resolved;
    }
    activateTab("trace");
    return Promise.resolve();
  }

  function exportCurrentTrace() {
    var taskId = currentTraceTaskId();
    if (!taskId) {
      toast("Trace ID gerekli", "err");
      return Promise.resolve();
    }
    if (!traceState.bundle || !traceState.bundle.history) {
      return loadTrace(taskId).then(function () {
        return exportCurrentTrace();
      });
    }
    downloadJson("elyan-trace-" + safeFileName(taskId) + ".json", traceState.bundle);
    toast("Trace JSON indirildi", "ok");
    return Promise.resolve();
  }

  /* ================================================================
     TABS
     ================================================================ */
  var tabMap = { mission: "p-mission", trace: "p-trace", tools: "p-tools", integrations: "p-integrations", channels: "p-channels", settings: "p-settings" };

  function activateTab(name) {
    var key = String(name || "mission");
    activeTab = key;
    $$(".nav-tab").forEach(function (b) {
      b.classList.toggle("active", String(b.getAttribute("data-t") || "") === key);
    });
    $$(".page").forEach(function (p) { p.classList.remove("show"); });
    var target = tabMap[key] || tabMap.mission;
    var el = document.getElementById(target);
    if (el) el.classList.add("show");
    if (key === "trace") {
      loadTrace();
    }
  }

  $$(".nav-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      activateTab(btn.getAttribute("data-t"));
    });
  });

  var missionRunBtn = $("#mission-run");
  if (missionRunBtn) missionRunBtn.addEventListener("click", createMission);
  $$(".js-mission-preset").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = $("#mission-input");
      if (input) input.value = btn.getAttribute("data-prompt") || "";
    });
  });
  $$(".js-pack-refresh").forEach(function (btn) {
    btn.addEventListener("click", function () {
      refreshPackOverview(btn.getAttribute("data-pack"));
    });
  });
  $$(".js-pack-mission").forEach(function (btn) {
    btn.addEventListener("click", function () {
      launchPackMission(btn.getAttribute("data-pack"), btn.getAttribute("data-action"));
    });
  });
  bindCopyCommandButtons(document);
  $$(".js-mission-filter").forEach(function (btn) {
    btn.addEventListener("click", function () {
      missionFilter = String(btn.getAttribute("data-filter") || "all");
      updateMissionFilterButtons();
      renderMissionList();
    });
  });
  updateMissionFilterButtons();
  var traceTaskInput = $("#trace-task-id");
  if (traceTaskInput && traceState.taskId) {
    traceTaskInput.value = traceState.taskId;
  }
  var traceLoadBtn = $("#trace-load");
  if (traceLoadBtn) traceLoadBtn.addEventListener("click", function () { loadTrace(traceTaskInput ? traceTaskInput.value : currentTraceTaskId()); });
  if (traceTaskInput) {
    traceTaskInput.addEventListener("keydown", function (evt) {
      if (evt.key === "Enter") {
        evt.preventDefault();
        loadTrace(traceTaskInput.value);
      }
    });
  }
  var traceRefreshBtn = $("#trace-refresh");
  if (traceRefreshBtn) traceRefreshBtn.addEventListener("click", function () { loadTrace(); });
  var packsRefreshBtn = $("#packs-refresh");
  if (packsRefreshBtn) packsRefreshBtn.addEventListener("click", function () { refreshPackOverview("all"); });
  var traceOpenBtn = $("#trace-open-full");
  if (traceOpenBtn) traceOpenBtn.addEventListener("click", function () {
    var taskId = currentTraceTaskId();
    if (taskId) {
      window.open("/trace/" + encodeURIComponent(taskId), "_blank", "noopener");
    }
  });
  var traceCopyBtn = $("#trace-copy-link");
  if (traceCopyBtn) traceCopyBtn.addEventListener("click", function () {
    var taskId = currentTraceTaskId();
    if (!taskId) {
      toast("Trace ID gerekli", "err");
      return;
    }
    copyText(window.location.origin + "/trace/" + encodeURIComponent(taskId), "Trace linki kopyalandı");
  });
  var traceDownloadBtn = $("#trace-download");
  if (traceDownloadBtn) traceDownloadBtn.addEventListener("click", function () { exportCurrentTrace(); });
  var readinessCopyBtn = $("#readiness-copy");
  if (readinessCopyBtn) {
    readinessCopyBtn.addEventListener("click", function () {
      var snapshot = buildInvestorReadiness();
      var status = readinessLabel(snapshot.complete, snapshot.total);
      var text = [
        "Elyan readiness: " + status + " (" + snapshot.complete + "/" + snapshot.total + ")",
        "Providers: " + snapshot.providersReady + "/" + snapshot.providerTotal,
        "Channels: " + snapshot.connectedChannels + "/" + snapshot.enabledChannels,
        "Skills: " + snapshot.skillsEnabled,
        "Integrations: " + snapshot.connectedAccounts,
        "Evidence: " + snapshot.evidenceCount,
        "Autopilot: " + (snapshot.autopilotRunning ? "on" : "off")
      ].join(" • ");
      copyText(text, "Hazırlık durumu kopyalandı");
    });
  }
  var readinessOpenTraceBtn = $("#readiness-open-trace");
  if (readinessOpenTraceBtn) {
    readinessOpenTraceBtn.addEventListener("click", function () {
      var taskId = currentTraceTaskId();
      if (taskId) {
        window.open("/trace/" + encodeURIComponent(taskId), "_blank", "noopener");
        return;
      }
      activateTab("trace");
      toast("Önce bir trace seçin", "info");
    });
  }
  activateTab(activeTab);

  var integrationProviderSelect = $("#integration-provider");
  if (integrationProviderSelect) {
    integrationProviderSelect.addEventListener("change", function () {
      var provider = String(integrationProviderSelect.value || "google");
      integrationState.provider = provider;
      var appInput = $("#integration-app");
      if (appInput && !appInput.value.trim()) {
        var quick = integrationQuickConnectPlan(provider);
        appInput.value = provider === "google" ? "Google" : (provider === "gmail" ? "Gmail" : provider);
        if (quick.scopes && integrationScopesInput) {
          integrationScopesInput.value = quick.scopes;
          integrationScopesInput.dataset.autofill = "1";
        }
      }
      var scopesEl = $("#integration-scopes");
      if (scopesEl) {
        var preset = integrationProviderPresetScopes(provider);
        if (!scopesEl.value.trim() || scopesEl.dataset.autofill === "1") {
          scopesEl.value = preset;
          scopesEl.dataset.autofill = "1";
        }
      }
      loadIntegrationAccounts();
    });
  }
  var integrationScopesInput = $("#integration-scopes");
  if (integrationScopesInput) {
    integrationScopesInput.addEventListener("input", function () {
      integrationScopesInput.dataset.autofill = integrationScopesInput.value.trim() ? "0" : "1";
    });
  }
  if (integrationProviderSelect && integrationScopesInput && !integrationScopesInput.value.trim()) {
    integrationScopesInput.value = integrationProviderPresetScopes(integrationProviderSelect.value || "google");
    integrationScopesInput.dataset.autofill = "1";
  }
  var integrationAppInput = $("#integration-app");
  var integrationQuickPresets = $("#integration-quick-presets");
  if (integrationAppInput && !integrationAppInput.value.trim()) {
    integrationAppInput.value = "Gmail";
  }
  var integrationRefreshBtn = $("#integrations-refresh");
  if (integrationRefreshBtn) integrationRefreshBtn.addEventListener("click", function () { refreshIntegrations(); });
  var integrationConnectBtn = $("#integration-connect");
  if (integrationConnectBtn) integrationConnectBtn.addEventListener("click", function () { connectIntegration(); });
  var integrationRevokeBtn = $("#integration-revoke");
  if (integrationRevokeBtn) {
    integrationRevokeBtn.addEventListener("click", function () {
      var providerEl = $("#integration-provider");
      var aliasEl = $("#integration-account-alias");
      revokeIntegrationAccount(providerEl ? providerEl.value : integrationState.provider, aliasEl ? aliasEl.value.trim() : "default");
    });
  }
  var integrationTraceSearchBtn = $("#integration-trace-search");
  if (integrationTraceSearchBtn) {
    integrationTraceSearchBtn.addEventListener("click", function () {
      loadIntegrationTraces();
    });
  }
  var integrationTraceFilterInput = $("#integration-trace-filter");
  if (integrationTraceFilterInput) {
    integrationTraceFilterInput.addEventListener("keydown", function (evt) {
      if (evt.key === "Enter") {
        evt.preventDefault();
        loadIntegrationTraces(integrationTraceFilterInput.value || "");
      }
    });
  }
  $$(".js-integration-quick").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var appName = btn.getAttribute("data-app") || "";
      var provider = btn.getAttribute("data-provider") || "";
      if (integrationAppInput) integrationAppInput.value = appName;
      if (integrationProviderSelect && provider) integrationProviderSelect.value = provider;
      if (integrationScopesInput) integrationScopesInput.value = integrationQuickConnectPlan(appName).scopes || integrationProviderPresetScopes(provider);
      connectIntegration({ appName: appName, provider: provider });
    });
  });

  var settingsRefreshBtn = $("#settings-refresh");
  if (settingsRefreshBtn) settingsRefreshBtn.addEventListener("click", function () { loadSettings(); });
  var channelsRefreshBtn = $("#channels-refresh");
  if (channelsRefreshBtn) channelsRefreshBtn.addEventListener("click", function () { loadChannels(); });
  var channelsSyncBtn = $("#channels-sync");
  if (channelsSyncBtn) channelsSyncBtn.addEventListener("click", function () { syncChannels(); });
  var channelTypeSelect = $("#channel-type");
  if (channelTypeSelect) {
    channelTypeSelect.addEventListener("change", function () {
      channelState.selectedType = normalizeChannelType(channelTypeSelect.value || "");
      channelState.selectedId = "";
      channelState.isDraft = true;
      renderChannelList();
      renderChannelEditor();
    });
  }
  var channelSaveBtn = $("#channel-save");
  if (channelSaveBtn) channelSaveBtn.addEventListener("click", function () { saveChannel(); });
  var channelTestBtn = $("#channel-test");
  if (channelTestBtn) channelTestBtn.addEventListener("click", function () {
    var current = selectedChannelItem();
    testChannel(current ? (current.id || current.type) : (channelState.selectedType || ""));
  });
  var channelResetBtn = $("#channel-reset");
  if (channelResetBtn) channelResetBtn.addEventListener("click", function () {
    startChannelDraft(channelState.selectedType || (channelState.catalog[0] && channelState.catalog[0].type) || "");
  });

  /* ================================================================
     PROVIDER META
     ================================================================ */
  var META = {
    groq:      { icon: "\uD83D\uDE80", label: "Groq",           note: "Hızlı" },
    google:    { icon: "\uD83D\uDD35", label: "Google Gemini",   note: "Genel" },
    openai:    { icon: "\uD83E\uDD16", label: "OpenAI",          note: "Premium" },
    anthropic: { icon: "\uD83E\uDDE0", label: "Anthropic Claude",note: "Kod" },
    deepseek:  { icon: "\u26A1",       label: "DeepSeek",        note: "Ekonomik" },
    ollama:    { icon: "\uD83C\uDFE0", label: "Ollama",          note: "Yerel" }
  };
  var PROVIDER_ORDER = ["groq", "google", "openai", "anthropic", "deepseek", "ollama"];

  /* ================================================================
     LLM PAGE
     ================================================================ */
  function loadProviders() {
    return GET("/api/llm/setup/status").then(function (data) {
      providers = Array.isArray(data.providers) ? data.providers : [];
      renderLLMKPIs();
      renderLLMGrid();
      renderPrimarySelect();
      updatePill();
    });
  }

  function renderLLMKPIs() {
    var active = 0, configured = 0, total = providers.length;
    providers.forEach(function (p) {
      if (p.reachable) active++;
      if (p.api_key_set || p.configured) configured++;
    });
    var el = $("#llm-kpis");
    if (!el) return;
    el.innerHTML =
      mkKPI("Aktif", active + " / " + total) +
      mkKPI("Ayarli", configured) +
      mkKPI("Toplam", total);
    renderInvestorHero();
  }

  function mkKPI(label, val) {
    return '<div class="kpi-box"><div class="kpi-label">' + esc(label) + '</div><div class="kpi-val">' + esc(String(val)) + '</div></div>';
  }

  function renderLLMGrid() {
    var grid = $("#llm-grid");
    if (!grid) return;
    grid.innerHTML = "";

    var rendered = {};
    PROVIDER_ORDER.forEach(function (pid) {
      var p = null;
      providers.forEach(function (x) { if (x.provider === pid) p = x; });
      if (p) { grid.appendChild(makeLLMCard(p)); rendered[pid] = true; }
    });
    providers.forEach(function (p) {
      if (!rendered[p.provider]) grid.appendChild(makeLLMCard(p));
    });
  }

  function makeLLMCard(p) {
    var m = META[p.provider] || { icon: "\uD83D\uDD17", label: p.name || p.provider, note: "" };
    var ok = !!p.reachable;
    var hasKey = !!p.api_key_set;
    var isOllama = p.provider === "ollama";

    var card = document.createElement("div");
    card.className = "card" + (ok ? "" : " dim");

    var pillClass = ok ? "ok" : (hasKey ? "warn" : "err");
    var pillText = ok ? "Aktif" : (hasKey ? "Key var" : "Kapali");

    var html = '<div class="card-top"><div><h3>' + m.icon + " " + esc(m.label) + "</h3>";
    html += '<div class="card-desc">' + esc(m.note) + "</div></div>";
    html += '<span class="pill ' + pillClass + '"><span class="pdot"></span>' + pillText + "</span></div>";

    html += '<div class="row"><span class="row-k">Model</span><span class="row-v">' + esc(p.model || "-") + "</span></div>";
    html += '<div class="row"><span class="row-k">Gecikme</span><span class="row-v">' + (p.latency_ms ? p.latency_ms + " ms" : "-") + "</span></div>";

    if (!isOllama) {
      html += '<div class="row"><span class="row-k">Key</span><span class="row-v">' + (hasKey ? "\u2022\u2022\u2022\u2022 (" + esc(p.key_source || "?") + ")" : "Yok") + "</span></div>";
    }

    if (p.error) {
      html += '<div class="row"><span class="row-k">Hata</span><span class="row-v" style="color:var(--red);word-break:break-word">' + esc(p.error) + "</span></div>";
    }

    // actions
    if (isOllama) {
      html += '<div class="btn-row"><button class="btn btn-s btn-sm js-test" data-p="' + esc(p.provider) + '">Sina</button></div>';
    } else {
      html += '<div class="key-input"><input type="password" placeholder="API key yapistir" id="ki-' + esc(p.provider) + '">';
      html += '<button class="btn btn-p btn-sm js-save" data-p="' + esc(p.provider) + '">Kaydet</button></div>';
      html += '<div class="btn-row"><button class="btn btn-s btn-sm js-test" data-p="' + esc(p.provider) + '">Sina</button>';
      if (hasKey) {
        html += '<button class="btn btn-d btn-sm js-remove" data-p="' + esc(p.provider) + '">Kaldir</button>';
      }
      html += "</div>";
    }

    card.innerHTML = html;

    // wire events
    card.querySelectorAll(".js-save").forEach(function (b) {
      b.addEventListener("click", function () { saveKey(b.getAttribute("data-p")); });
    });
    card.querySelectorAll(".js-test").forEach(function (b) {
      b.addEventListener("click", function () { testProv(b.getAttribute("data-p"), b); });
    });
    card.querySelectorAll(".js-remove").forEach(function (b) {
      b.addEventListener("click", function () { removeKey(b.getAttribute("data-p")); });
    });

    return card;
  }

  function saveKey(provider) {
    var inp = document.getElementById("ki-" + provider);
    var key = inp ? inp.value.trim() : "";
    if (!key) { toast("API key bos olamaz", "err"); return; }
    POST("/api/llm/setup/save-key", { provider: provider, api_key: key }).then(function (res) {
      if (res.success || res.ok) {
        toast(provider + " kaydedildi", "ok");
        if (inp) inp.value = "";
        loadProviders();
      } else {
        toast(res.error || res.message || "Kaydetme basarisiz", "err");
      }
    });
  }

  function testProv(provider, btn) {
    btn.disabled = true;
    btn.textContent = "...";
    GET("/api/llm/setup/health").then(function (data) {
      var provs = data.providers || [];
      var info = null;
      provs.forEach(function (x) { if (x.provider === provider) info = x; });
      if (info && info.reachable) {
        btn.textContent = "\u2713 " + (info.latency_ms || 0) + "ms";
        btn.style.color = "var(--green)";
        toast(provider + " calisiyor", "ok");
      } else {
        btn.textContent = "\u2717";
        btn.style.color = "var(--red)";
        toast(provider + " baglanti basarisiz", "err");
      }
      setTimeout(function () {
        btn.disabled = false;
        btn.textContent = "Sina";
        btn.style.color = "";
      }, 3000);
    });
  }

  function removeKey(provider) {
    if (!confirm(provider + " API key kaldirilsin mi?")) return;
    POST("/api/llm/setup/remove-key", { provider: provider }).then(function (res) {
      if (res.success || res.ok) {
        toast(provider + " kaldirildi", "ok");
        loadProviders();
      } else {
        toast(res.error || "Kaldirilamadi", "err");
      }
    });
  }

  /* ================================================================
     OLLAMA PAGE
     ================================================================ */
  function loadOllama() {
    return GET("/api/llm/setup/ollama").then(function (data) {
      ollamaData = data || {};
      renderOllama();
    });
  }

  function renderOllama() {
    var running = !!ollamaData.running;
    var bar = $("#oll-bar");
    if (bar) {
      bar.className = "oll-bar " + (running ? "on" : "off");
      bar.textContent = running ? "\u2713 Ollama calisiyor" : "\u2717 Ollama kapali — ollama.ai/download adresinden indirin";
    }

    // installed
    var models = ollamaData.models || [];
    var ig = $("#oll-installed");
    if (ig) {
      if (models.length === 0) {
        ig.innerHTML = '<div class="card dim" style="grid-column:1/-1;text-align:center;padding:24px"><p style="color:var(--tx3)">Yuklu model yok</p></div>';
      } else {
        ig.innerHTML = "";
        models.forEach(function (m) {
          var c = document.createElement("div");
          c.className = "card";
          c.innerHTML =
            '<div class="card-top"><h3>' + esc(m.name) + '</h3><span class="pill ok">Yuklu</span></div>' +
            '<div class="row"><span class="row-k">Boyut</span><span class="row-v">' + esc(m.size || "?") + '</span></div>' +
            '<div class="btn-row"><button class="btn btn-d btn-sm js-oll-del" data-m="' + esc(m.name) + '">Sil</button></div>';
          c.querySelector(".js-oll-del").addEventListener("click", function (e) {
            ollamaDelete(e.currentTarget.getAttribute("data-m"));
          });
          ig.appendChild(c);
        });
      }
    }

    // recommended
    var recs = ollamaData.recommended || [];
    var rg = $("#oll-recommended");
    if (rg) {
      if (recs.length === 0) {
        rg.innerHTML = '<div class="card dim" style="grid-column:1/-1;text-align:center;padding:24px"><p style="color:var(--tx3)">Oneri yok</p></div>';
      } else {
        rg.innerHTML = "";
        recs.forEach(function (r) {
          var c = document.createElement("div");
          c.className = "card" + (r.installed ? "" : " dim");
          var h = '<div class="card-top"><h3>' + esc(r.name) + '</h3><span class="pill ' + (r.installed ? "ok" : "warn") + '">' + (r.installed ? "Yuklu" : "Indirilmemis") + "</span></div>";
          h += '<div class="row"><span class="row-k">Boyut</span><span class="row-v">' + esc(r.size || "?") + "</span></div>";
          if (r.description) h += '<div class="row"><span class="row-k">Aciklama</span><span class="row-v">' + esc(r.description) + "</span></div>";
          if (!r.installed) h += '<div class="btn-row"><button class="btn btn-p btn-sm js-oll-pull" data-m="' + esc(r.name) + '">Indir</button></div>';
          c.innerHTML = h;
          var pb = c.querySelector(".js-oll-pull");
          if (pb) {
            pb.addEventListener("click", function (e) {
              ollamaPull(e.currentTarget.getAttribute("data-m"), e.currentTarget);
            });
          }
          rg.appendChild(c);
        });
      }
    }
  }

  function ollamaPull(model, btn) {
    btn.disabled = true;
    btn.textContent = "Indiriliyor...";
    toast(model + " indiriliyor, bu biraz surebilir...", "info");
    POST("/api/llm/setup/ollama-pull", { model: model }).then(function (res) {
      if (res.success || res.ok) {
        toast(model + " indirildi", "ok");
      } else {
        toast(res.error || "Indirme basarisiz", "err");
      }
      btn.disabled = false;
      btn.textContent = "Indir";
      loadOllama();
    });
  }

  function ollamaDelete(model) {
    if (!confirm(model + " silinsin mi?")) return;
    POST("/api/llm/setup/ollama-delete", { model: model }).then(function (res) {
      if (res.success || res.ok) {
        toast(model + " silindi", "ok");
      } else {
        toast(res.error || "Silme basarisiz", "err");
      }
      loadOllama();
    });
  }

  var ollRefresh = $("#oll-refresh");
  if (ollRefresh) ollRefresh.addEventListener("click", function () { loadOllama(); });

  /* ================================================================
     STATUS PAGE
     ================================================================ */
  function loadHealth() {
    return GET("/api/llm/setup/health").then(function (data) {
      renderHealth(data);
    });
  }

  function renderHealth(data) {
    var kpis = $("#st-kpis");
    if (kpis) {
      kpis.innerHTML =
        mkKPI("Calisan", data.working_count || 0) +
        mkKPI("Ayarli", data.configured_count || 0) +
        mkKPI("Toplam", data.total_providers || 0);
    }

    var provs = data.providers || [];
    var tbl = $("#st-table");
    if (!tbl) return;
    if (provs.length === 0) {
      tbl.innerHTML = '<p style="padding:20px;text-align:center;color:var(--tx3)">Provider bilgisi yok</p>';
      return;
    }
    var h = '<table class="stbl"><thead><tr><th>Provider</th><th>Durum</th><th>Model</th><th>Key</th><th>Gecikme</th><th>Hata</th></tr></thead><tbody>';
    provs.forEach(function (p) {
      var cls = p.reachable ? "ok" : (p.api_key_set ? "warn" : "err");
      var txt = p.reachable ? "Aktif" : (p.api_key_set ? "Key var" : "Kapali");
      h += "<tr>";
      h += "<td><strong>" + esc(p.name || p.provider) + "</strong></td>";
      h += '<td><span class="pill ' + cls + '">' + txt + "</span></td>";
      h += "<td>" + esc(p.model || "-") + "</td>";
      h += "<td>" + (p.api_key_set ? esc(p.key_source || "var") : "-") + "</td>";
      h += "<td>" + (p.latency_ms ? p.latency_ms + "ms" : "-") + "</td>";
      h += '<td style="color:var(--red);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(p.error || "-") + "</td>";
      h += "</tr>";
    });
    h += "</tbody></table>";
    tbl.innerHTML = h;
  }

  /* ================================================================
     SETTINGS
     ================================================================ */
  function renderPrimarySelect() {
    var sel = $("#s-primary");
    if (!sel) return;
    var cur = sel.value;
    sel.innerHTML = '<option value="">Otomatik</option>';
    providers.forEach(function (p) {
      if (p.reachable) {
        sel.innerHTML += '<option value="' + esc(p.provider) + '">' + esc((p.name || p.provider)) + " (" + esc(p.model || "?") + ")</option>";
      }
    });
    sel.value = cur;
  }

  function renderToolPolicy() {
    var allow = $("#s-policy-allow");
    var deny = $("#s-policy-deny");
    var approval = $("#s-policy-approval");
    var defaultDeny = $("#s-default-deny");
    var badge = $("#policy-default-deny");
    if (allow) allow.value = joinCsvList(toolsPolicyState.allow || []);
    if (deny) deny.value = joinCsvList(toolsPolicyState.deny || []);
    if (approval) approval.value = joinCsvList(toolsPolicyState.requireApproval || []);
    if (defaultDeny) defaultDeny.checked = !!toolsPolicyState.defaultDeny;
    if (badge) {
      badge.textContent = toolsPolicyState.defaultDeny ? "default deny" : "default allow";
      badge.className = "pill " + (toolsPolicyState.defaultDeny ? "warn" : "ok");
    }
  }

  function loadSettings() {
    return Promise.all([GET("/api/models"), GET("/api/agent/profile"), GET("/api/tools/policy")]).then(function (rows) {
      var models = rows && rows[0] && rows[0].ok ? rows[0] : {};
      var profile = rows && rows[1] && rows[1].ok ? rows[1].profile || {} : {};
      var policy = rows && rows[2] && rows[2].ok ? rows[2].policy || {} : {};
      var runtime = profile.runtime_policy || {};
      var rawStrategy = String(runtime.dashboard_strategy || "balanced").toLowerCase();
      var normalizedStrategy = rawStrategy;
      if (rawStrategy === "hızlı" || rawStrategy === "hizli") normalizedStrategy = "fast";
      else if (rawStrategy === "kalite") normalizedStrategy = "best";
      else if (rawStrategy === "dengeli") normalizedStrategy = "balanced";
      var userProfile = profile.user_profile || {};
      settingsState = {
        primaryLLM: String(((models.default || {}).provider) || ""),
        strategy: normalizedStrategy || "balanced",
        language: String(profile.language || "tr"),
        localFirst: !!runtime.model_local_first,
        name: String(profile.name || "Elyan"),
        personality: String(profile.personality || "professional"),
        preset: String(runtime.preset || "balanced"),
        responseMode: String(runtime.response_mode || "friendly"),
        responseLengthBias: String(userProfile.response_length_bias || "short"),
        autonomous: !!profile.autonomous,
        defaultRole: String(runtime.default_user_role || "operator"),
        kvkkStrict: !!runtime.kvkk_strict_mode,
        redactCloudPrompts: !!runtime.redact_cloud_prompts,
        allowCloudFallback: !!runtime.allow_cloud_fallback,
        enforceRBAC: !!runtime.enforce_rbac,
        pathGuardEnabled: !!runtime.path_guard_enabled,
        dangerousToolsEnabled: !!runtime.dangerous_tools_enabled,
        requireConfirmationForRisky: !!runtime.require_confirmation_for_risky,
        requireEvidenceForDangerous: !!runtime.require_evidence_for_dangerous,
        shareManifestDefault: !!runtime.share_manifest_default,
        shareAttachmentsDefault: !!runtime.share_attachments_default
      };
      var el = $("#s-primary");
      if (el) el.value = settingsState.primaryLLM || "";
      var elName = $("#s-name");
      if (elName) elName.value = settingsState.name || "";
      var elPersonality = $("#s-personality");
      if (elPersonality) elPersonality.value = settingsState.personality || "professional";
      var elPreset = $("#s-preset");
      if (elPreset) elPreset.value = settingsState.preset || "balanced";
      var el2 = $("#s-strategy");
      if (el2) el2.value = settingsState.strategy || "balanced";
      var elResponseMode = $("#s-response-mode");
      if (elResponseMode) elResponseMode.value = settingsState.responseMode || "friendly";
      var elResponseLength = $("#s-response-length");
      if (elResponseLength) elResponseLength.value = settingsState.responseLengthBias || "short";
      var el3 = $("#s-lang");
      if (el3) el3.value = settingsState.language || "tr";
      var elRole = $("#s-role");
      if (elRole) elRole.value = settingsState.defaultRole || "operator";
      var el4 = $("#s-local");
      if (el4) el4.checked = !!settingsState.localFirst;
      var el5 = $("#s-autonomous");
      if (el5) el5.checked = !!settingsState.autonomous;
      var el6 = $("#s-kvkk");
      if (el6) el6.checked = !!settingsState.kvkkStrict;
      var el7 = $("#s-redact");
      if (el7) el7.checked = !!settingsState.redactCloudPrompts;
      var el8 = $("#s-cloud-fallback");
      if (el8) el8.checked = !!settingsState.allowCloudFallback;
      var el9 = $("#s-rbac");
      if (el9) el9.checked = !!settingsState.enforceRBAC;
      var el10 = $("#s-path-guard");
      if (el10) el10.checked = !!settingsState.pathGuardEnabled;
      var el11 = $("#s-dangerous");
      if (el11) el11.checked = !!settingsState.dangerousToolsEnabled;
      var el12 = $("#s-confirm-risk");
      if (el12) el12.checked = !!settingsState.requireConfirmationForRisky;
      var el13 = $("#s-evidence");
      if (el13) el13.checked = !!settingsState.requireEvidenceForDangerous;
      var el14 = $("#s-share-manifest");
      if (el14) el14.checked = !!settingsState.shareManifestDefault;
      var el15 = $("#s-share-attachments");
      if (el15) el15.checked = !!settingsState.shareAttachmentsDefault;
      toolsPolicyState = {
        allow: Array.isArray(policy.allow) ? policy.allow : [],
        deny: Array.isArray(policy.deny) ? policy.deny : [],
        requireApproval: Array.isArray(policy.requireApproval) ? policy.requireApproval : [],
        defaultDeny: !!policy.defaultDeny,
        defaults: rows && rows[2] && rows[2].defaults ? rows[2].defaults : {}
      };
      renderToolPolicy();
      renderInvestorHero();
    });
  }

  var saveBtn = $("#s-save");
  if (saveBtn) {
    saveBtn.addEventListener("click", function () {
      var s = {
        name: ($("#s-name") || {}).value || "",
        personality: ($("#s-personality") || {}).value || "professional",
        primaryLLM: ($("#s-primary") || {}).value || "",
        preset: ($("#s-preset") || {}).value || "balanced",
        strategy: ($("#s-strategy") || {}).value || "balanced",
        responseMode: ($("#s-response-mode") || {}).value || "friendly",
        responseLengthBias: ($("#s-response-length") || {}).value || "short",
        language: ($("#s-lang") || {}).value || "tr",
        localFirst: !!($("#s-local") || {}).checked,
        autonomous: !!($("#s-autonomous") || {}).checked,
        defaultRole: ($("#s-role") || {}).value || "operator",
        kvkkStrict: !!($("#s-kvkk") || {}).checked,
        redactCloudPrompts: !!($("#s-redact") || {}).checked,
        allowCloudFallback: !!($("#s-cloud-fallback") || {}).checked,
        enforceRBAC: !!($("#s-rbac") || {}).checked,
        pathGuardEnabled: !!($("#s-path-guard") || {}).checked,
        dangerousToolsEnabled: !!($("#s-dangerous") || {}).checked,
        requireConfirmationForRisky: !!($("#s-confirm-risk") || {}).checked,
        requireEvidenceForDangerous: !!($("#s-evidence") || {}).checked,
        shareManifestDefault: !!($("#s-share-manifest") || {}).checked,
        shareAttachmentsDefault: !!($("#s-share-attachments") || {}).checked
      };
      var selectedProvider = s.primaryLLM || settingsState.primaryLLM || "";
      var selectedModel = "";
      providers.forEach(function (p) {
        if (!selectedModel && p && p.provider === selectedProvider) selectedModel = String(p.model || "");
      });
      if (!selectedModel && selectedProvider === "ollama") selectedModel = "llama3.2:3b";
      var runtimePayload = {
        name: s.name,
        personality: s.personality,
        autonomous: s.autonomous,
        language: s.language,
        response_mode: s.responseMode,
        response_length_bias: s.responseLengthBias,
        runtime_policy: {
          preset: s.preset,
          model_local_first: !!s.localFirst,
          dashboard_strategy: s.strategy,
          response_mode: s.responseMode,
          response_friendly: s.responseMode === "friendly",
          share_manifest_default: !!s.shareManifestDefault,
          share_attachments_default: !!s.shareAttachmentsDefault,
          kvkk_strict_mode: !!s.kvkkStrict,
          redact_cloud_prompts: !!s.redactCloudPrompts,
          allow_cloud_fallback: !!s.allowCloudFallback,
          default_user_role: s.defaultRole,
          enforce_rbac: !!s.enforceRBAC,
          path_guard_enabled: !!s.pathGuardEnabled,
          dangerous_tools_enabled: !!s.dangerousToolsEnabled,
          require_confirmation_for_risky: !!s.requireConfirmationForRisky,
          require_evidence_for_dangerous: !!s.requireEvidenceForDangerous
        },
        user_profile: {
          response_length_bias: s.responseLengthBias
        }
      };
      var policyPayload = {
        defaultDeny: !!($("#s-default-deny") || {}).checked,
        allow: parseCsvList(($("#s-policy-allow") || {}).value || ""),
        deny: parseCsvList(($("#s-policy-deny") || {}).value || ""),
        requireApproval: parseCsvList(($("#s-policy-approval") || {}).value || "")
      };
      Promise.all([
        POST("/api/models", selectedProvider ? { provider: selectedProvider, model: selectedModel, sync_roles: true } : {}),
        POST("/api/agent/profile", runtimePayload),
        POST("/api/tools/policy", policyPayload)
      ]).then(function (rows) {
        var failed = (rows || []).some(function (row) { return !row || row.ok === false; });
        if (failed) {
          toast("Ayarlar kaydedilemedi", "err");
          return;
        }
        settingsState = s;
        toolsPolicyState = {
          allow: policyPayload.allow,
          deny: policyPayload.deny,
          requireApproval: policyPayload.requireApproval,
          defaultDeny: !!policyPayload.defaultDeny,
          defaults: toolsPolicyState.defaults || {}
        };
        toast("Ayarlar kaydedildi", "ok");
        return refreshAll();
      });
    });
  }

  /* ================================================================
     STATUS PILL (navbar)
     ================================================================ */
  function updatePill() {
    var dot = $("#g-dot");
    var txt = $("#g-txt");
    if (!dot || !txt) return;
    var working = 0;
    providers.forEach(function (p) { if (p.reachable) working++; });
    if (working > 0) {
      dot.className = "status-dot ok";
      txt.textContent = working + " aktif";
    } else if (providers.some(function (p) { return p.api_key_set || p.configured; })) {
      dot.className = "status-dot";
      txt.textContent = "baglanti yok";
    } else {
      dot.className = "status-dot err";
      txt.textContent = "ayar gerekli";
    }
  }

  /* ================================================================
     WEBSOCKET
     ================================================================ */
  function connectWS() {
    try {
      var proto = location.protocol === "https:" ? "wss:" : "ws:";
      var ws = new WebSocket(proto + "//" + location.host + "/ws/dashboard");
      ws.onmessage = function (e) {
        try {
          var msg = JSON.parse(e.data);
          var payload = msg.data || msg.payload || msg;
          if (msg.event === "llm_update" || msg.event === "provider_change") {
            loadProviders();
          } else if (msg.event === "mission_event" || msg.event === "mission_overview" || msg.event === "mission_list") {
            loadMissionControl();
          } else if (msg.event === "activity" && payload && payload.type && String(payload.type).indexOf("channel_") === 0) {
            loadChannels();
          } else if (msg.event === "autopilot" || msg.event === "autopilot_action" || msg.event === "briefing" || msg.event === "suggestion" || msg.event === "task_review" || msg.event === "intervention" || msg.event === "automation_health" || msg.event === "reconcile") {
            loadAutopilot();
          } else if (msg.event === "activity" && payload && payload.type === "agent_profile") {
            loadSettings();
          } else if (msg.event === "activity" && payload && payload.type === "tools_policy") {
            loadSettings();
          }
          if (activeTab === "trace" && (msg.event === "mission_event" || msg.event === "activity" || msg.event === "tool_event" || msg.event === "telemetry" || msg.event === "history")) {
            appendTraceLive(msg.event || "event", payload);
          }
        } catch (ex) { /* ignore */ }
      };
      ws.onclose = function () { setTimeout(connectWS, 5000); };
      ws.onerror = function () { /* ws.onclose will handle reconnect */ };
    } catch (ex) { /* no WS — rely on polling */ }
  }

  /* ================================================================
     REFRESH & BOOT
     ================================================================ */
  function refreshAll() {
    return Promise.all([
      loadMissionControl(),
      loadPackOverview("all"),
      loadProviders(),
      loadOllama(),
      loadHealth(),
      loadSkillCatalog(),
      loadMarketplace(""),
      refreshIntegrations(),
      loadAutopilot(),
      loadChannels()
    ]).then(function () {
      return loadSettings();
    });
  }

  var refreshBtn = $("#g-refresh");
  if (refreshBtn) refreshBtn.addEventListener("click", function () { refreshAll(); });
  var toolsRefreshBtn = $("#g-refresh-tools");
  if (toolsRefreshBtn) toolsRefreshBtn.addEventListener("click", function () { refreshAll(); });
  var autopilotRefreshBtn = $("#autopilot-refresh");
  if (autopilotRefreshBtn) autopilotRefreshBtn.addEventListener("click", function () { loadAutopilot(); });
  var autopilotStartBtn = $("#autopilot-start");
  if (autopilotStartBtn) autopilotStartBtn.addEventListener("click", function () { startAutopilot(); });
  var autopilotStopBtn = $("#autopilot-stop");
  if (autopilotStopBtn) autopilotStopBtn.addEventListener("click", function () { stopAutopilot(); });
  var autopilotTickBtn = $("#autopilot-tick");
  if (autopilotTickBtn) autopilotTickBtn.addEventListener("click", function () { tickAutopilot(); });
  var skillsRefreshBtn = $("#skills-refresh");
  if (skillsRefreshBtn) skillsRefreshBtn.addEventListener("click", function () { refreshSkillRegistry(); });
  var marketplaceRefreshBtn = $("#marketplace-refresh");
  if (marketplaceRefreshBtn) marketplaceRefreshBtn.addEventListener("click", function () { loadMarketplace(marketplaceState.query || ""); });
  var marketplaceSearchBtn = $("#marketplace-search");
  if (marketplaceSearchBtn) marketplaceSearchBtn.addEventListener("click", function () {
    var input = $("#marketplace-query");
    loadMarketplace(input ? input.value : "");
  });
  var marketplaceQueryInput = $("#marketplace-query");
  if (marketplaceQueryInput) {
    marketplaceQueryInput.addEventListener("keydown", function (evt) {
      if (evt.key === "Enter") {
        evt.preventDefault();
        loadMarketplace(marketplaceQueryInput.value || "");
      }
    });
  }

  // Boot
  refreshAll().then(function () {
    renderInvestorHero();
  });
  connectWS();

  // Auto-refresh
  setInterval(refreshAll, 60000);
});
