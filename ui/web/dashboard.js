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
  var initialMissionId = "";
  try {
    var params = new URLSearchParams(window.location.search || "");
    initialMissionId = params.get("mission_id") || params.get("selected_mission_id") || "";
  } catch (e) {
    initialMissionId = "";
  }
  var requestedMissionId = initialMissionId;
  if (initialMissionId) {
    missionState.selectedMissionId = initialMissionId;
  }
  var missionFilter = "all";
  var REQUEST_TIMEOUT = { timeoutMs: 130000 };
  var timeoutMs = 130000;

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
      .then(function (r) { return r.json(); })
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
      '<div class="btn-row"><button class="btn btn-s btn-sm" id="save-skill-btn">Save as Skill</button></div>';

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
        return loadMissionDetail();
      });
    });
  }

  function createMission() {
    var input = $("#mission-input");
    var modeEl = $("#mission-mode");
    var goal = input ? input.value.trim() : "";
    if (!goal) { toast("Mission hedefi bos olamaz", "err"); return; }
    POST("/api/missions", { goal: goal, mode: (modeEl && modeEl.value) || "Balanced", user_id: "local", channel: "dashboard" }).then(function (res) {
      if (res && res.ok && res.mission) {
        missionState.selectedMissionId = res.mission.mission_id;
        toast("Mission baslatildi", "ok");
        loadMissionControl();
      } else {
        toast(friendlyFailure((res || {}).error || "mission_create_failed"), "err");
      }
    });
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

  /* ================================================================
     TABS
     ================================================================ */
  var tabMap = { mission: "p-mission", tools: "p-tools", settings: "p-settings" };

  $$(".nav-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      $$(".nav-tab").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      var target = tabMap[btn.getAttribute("data-t")];
      $$(".page").forEach(function (p) { p.classList.remove("show"); });
      var el = document.getElementById(target);
      if (el) el.classList.add("show");
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
  $$(".js-mission-filter").forEach(function (btn) {
    btn.addEventListener("click", function () {
      missionFilter = String(btn.getAttribute("data-filter") || "all");
      updateMissionFilterButtons();
      renderMissionList();
    });
  });
  updateMissionFilterButtons();

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

  function loadSettings() {
    return Promise.all([GET("/api/models"), GET("/api/agent/profile")]).then(function (rows) {
      var models = rows && rows[0] && rows[0].ok ? rows[0] : {};
      var profile = rows && rows[1] && rows[1].ok ? rows[1].profile || {} : {};
      var runtime = profile.runtime_policy || {};
      var rawStrategy = String(runtime.dashboard_strategy || "balanced").toLowerCase();
      var normalizedStrategy = rawStrategy;
      if (rawStrategy === "hızlı" || rawStrategy === "hizli") normalizedStrategy = "fast";
      else if (rawStrategy === "kalite") normalizedStrategy = "best";
      else if (rawStrategy === "dengeli") normalizedStrategy = "balanced";
      settingsState = {
        primaryLLM: String(((models.default || {}).provider) || ""),
        strategy: normalizedStrategy || "balanced",
        language: String(profile.language || "tr"),
        localFirst: !!runtime.model_local_first
      };
      var el = $("#s-primary");
      if (el) el.value = settingsState.primaryLLM || "";
      var el2 = $("#s-strategy");
      if (el2) el2.value = settingsState.strategy || "balanced";
      var el3 = $("#s-lang");
      if (el3) el3.value = settingsState.language || "tr";
      var el4 = $("#s-local");
      if (el4) el4.checked = !!settingsState.localFirst;
    });
  }

  var saveBtn = $("#s-save");
  if (saveBtn) {
    saveBtn.addEventListener("click", function () {
      var s = {
        primaryLLM: ($("#s-primary") || {}).value || "",
        strategy: ($("#s-strategy") || {}).value || "balanced",
        language: ($("#s-lang") || {}).value || "tr",
        localFirst: !!($("#s-local") || {}).checked
      };
      var selectedProvider = s.primaryLLM || settingsState.primaryLLM || "";
      var selectedModel = "";
      providers.forEach(function (p) {
        if (!selectedModel && p && p.provider === selectedProvider) selectedModel = String(p.model || "");
      });
      if (!selectedModel && selectedProvider === "ollama") selectedModel = "llama3.2:3b";
      Promise.all([
        POST("/api/models", selectedProvider ? { provider: selectedProvider, model: selectedModel, sync_roles: true } : {}),
        POST("/api/agent/profile", {
          language: s.language,
          runtime_policy: {
            model_local_first: !!s.localFirst,
            dashboard_strategy: s.strategy
          }
        })
      ]).then(function (rows) {
        var failed = (rows || []).some(function (row) { return !row || row.ok === false; });
        if (failed) {
          toast("Ayarlar kaydedilemedi", "err");
          return;
        }
        settingsState = s;
        toast("Ayarlar kaydedildi", "ok");
        refreshAll().then(function () { return loadSettings(); });
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
          if (msg.event === "llm_update" || msg.event === "provider_change") {
            loadProviders();
          } else if (msg.event === "mission_event" || msg.event === "mission_overview" || msg.event === "mission_list") {
            loadMissionControl();
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
    return Promise.all([loadMissionControl(), loadProviders(), loadOllama(), loadHealth(), loadSkillCatalog(), loadMarketplace("")]);
  }

  var refreshBtn = $("#g-refresh");
  if (refreshBtn) refreshBtn.addEventListener("click", function () { refreshAll(); });
  var toolsRefreshBtn = $("#g-refresh-tools");
  if (toolsRefreshBtn) toolsRefreshBtn.addEventListener("click", function () { refreshAll(); });
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
  refreshAll().then(function () { return loadSettings(); });
  connectWS();

  // Auto-refresh
  setInterval(refreshAll, 60000);
});
