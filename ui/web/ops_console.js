const qs = (selector) => document.querySelector(selector);

const els = {
  syncPill: qs("#sync-pill"),
  refresh: qs("#refresh-btn"),
  lastSync: qs("#last-sync"),
  usersTotal: qs("#users-total"),
  usersActive: qs("#users-active"),
  tasksTotal: qs("#tasks-total"),
  tasksActive: qs("#tasks-active"),
  quotaBlocked: qs("#quota-blocked"),
  failedTotal: qs("#failed-total"),
  plannerActive: qs("#planner-active"),
  plannerCompleted: qs("#planner-completed"),
  userCountNote: qs("#user-count-note"),
  userSearch: qs("#user-search"),
  userList: qs("#user-list"),
  stateFilter: qs("#state-filter"),
  clearSelection: qs("#clear-selection-btn"),
  selectedUser: qs("#selected-user"),
  selectedPlan: qs("#selected-plan"),
  timeline: qs("#timeline-list"),
  artifacts: qs("#artifact-list"),
  subtasks: qs("#subtask-list"),
  cancelTask: qs("#cancel-task-btn"),
  requeueTask: qs("#requeue-task-btn"),
  laneExecution: qs("#lane-execution"),
  laneAttention: qs("#lane-attention"),
  laneDone: qs("#lane-done"),
  laneExecutionCount: qs("#lane-execution-count"),
  laneAttentionCount: qs("#lane-attention-count"),
  laneDoneCount: qs("#lane-done-count"),
  tierButtons: Array.from(document.querySelectorAll(".tier-btn")),
};

const state = {
  users: [],
  plans: [],
  overview: {},
  selectedUserId: "",
  selectedPlanId: "",
};

function h(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtTs(value) {
  const ts = Number(value || 0);
  if (!Number.isFinite(ts) || ts <= 0) return "-";
  return new Date(ts * 1000).toLocaleString("tr-TR");
}

function relativeQuota(quota = {}) {
  const current = Number(quota.daily_messages || 0);
  const limit = Number(quota.daily_limit || 0);
  if (!Number.isFinite(limit) || limit <= 0) return "-";
  return `${current}/${limit}`;
}

function toLaneKey(plan) {
  const value = String(plan?.state || "").toLowerCase();
  if (["completed", "cancelled"].includes(value)) return "done";
  if (["failed", "partial"].includes(value)) return "attention";
  return "execution";
}

function statePillClass(value) {
  const stateValue = String(value || "").toLowerCase();
  if (["completed"].includes(stateValue)) return "pill ok";
  if (["failed", "partial", "cancelled"].includes(stateValue)) return "pill err";
  if (["planning", "verifying", "queued"].includes(stateValue)) return "pill warn";
  return "pill brand";
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
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`HTTP ${response.status} ${body}`.trim());
  }
  return response.json();
}

function filteredUsers() {
  const search = String(els.userSearch.value || "").trim().toLowerCase();
  if (!search) return state.users;
  return state.users.filter((user) => {
    const haystack = [
      user.user_id,
      user.tier,
      ...(Array.isArray(user.channels) ? user.channels : []),
    ].join(" ").toLowerCase();
    return haystack.includes(search);
  });
}

function filteredPlans() {
  const stateFilter = String(els.stateFilter.value || "").trim().toLowerCase();
  return state.plans.filter((plan) => {
    if (state.selectedUserId && String(plan.user_id || "") !== state.selectedUserId) {
      return false;
    }
    if (stateFilter && String(plan.state || "").toLowerCase() !== stateFilter) {
      return false;
    }
    return true;
  });
}

function renderOverview() {
  const overview = state.overview || {};
  els.usersTotal.textContent = String(overview.users_total ?? "-");
  els.usersActive.textContent = `Aktif: ${overview.active_users ?? "-"}`;
  els.tasksTotal.textContent = String(overview.tasks_total ?? "-");
  const active = Number(overview.foreground_active || 0) + Number(overview.background_active || 0);
  els.tasksActive.textContent = `Calisan: ${active}`;
  els.quotaBlocked.textContent = String(overview.quota_blocked_users ?? "-");
  els.failedTotal.textContent = `Riskli plan: ${overview.failed_or_partial ?? "-"}`;
  els.plannerActive.textContent = String(overview?.planner?.active_plans ?? "-");
  els.plannerCompleted.textContent = `Tamamlanan: ${overview?.planner?.completed_plans ?? "-"}`;
}

function renderUsers() {
  const users = filteredUsers();
  els.userCountNote.textContent = `${users.length} kullanici listeleniyor`;
  els.userList.innerHTML = users.length
    ? users.map((user) => {
        const active = state.selectedUserId === user.user_id ? "active" : "";
        const quotaBlocked = user?.quota?.allowed === false;
        const channels = Array.isArray(user.channels) && user.channels.length
          ? user.channels.join(", ")
          : "kanal yok";
        return `
          <article class="user-card ${active}" data-user-id="${h(user.user_id)}">
            <div class="user-card-head">
              <strong>${h(user.user_id)}</strong>
              <span class="${quotaBlocked ? "pill err" : "pill ok"}">${quotaBlocked ? "quota blocked" : h(user.tier || "free")}</span>
            </div>
            <div class="meta-line">Aktif task: ${h(user.active_tasks)} | Toplam: ${h(user.tasks_total)} | Background: ${h(user.background_tasks)}</div>
            <div class="meta-line">Gunluk kullanim: ${h(relativeQuota(user.quota || {}))} | Kanallar: ${h(channels)}</div>
            <div class="meta-line">Son aktivite: ${h(fmtTs(user.last_active_at))}</div>
          </article>
        `;
      }).join("")
    : `<div class="empty-state">Aramaya uyan kullanici yok.</div>`;
}

function planCard(plan) {
  const active = state.selectedPlanId === plan.task_id ? "active" : "";
  const summary = plan.kind === "background" && plan.result_summary
    ? plan.result_summary
    : (plan.summary || plan.objective || "");
  const note = plan.kind === "background"
    ? `retry ${plan.retry_count || 0}/${plan.max_retries || 0}`
    : `${Array.isArray(plan.subtasks) ? plan.subtasks.length : 0} subtask`;
  return `
    <article class="plan-card ${active}" data-plan-id="${h(plan.task_id)}">
      <div class="plan-card-head">
        <strong>${h(plan.task_id)}</strong>
        <span class="${statePillClass(plan.state)}">${h(plan.state)}</span>
      </div>
      <div class="chip-row meta-line">
        <span>${h(plan.user_id || "local")}</span>
        <span>${h(plan.kind || "foreground")}</span>
      </div>
      <div class="plan-title">${h(summary || "Aciklama yok.")}</div>
      <div class="meta-line">Workflow: ${h(plan.workflow_id || "-")} | Domain: ${h(plan.capability_domain || "-")}</div>
      <div class="meta-line">Artifacts: ${h(plan.artifacts_count || 0)} | ${h(note)}</div>
    </article>
  `;
}

function renderBoard() {
  const plans = filteredPlans();
  const lanes = { execution: [], attention: [], done: [] };
  for (const plan of plans) {
    lanes[toLaneKey(plan)].push(plan);
  }
  els.laneExecution.innerHTML = lanes.execution.length
    ? lanes.execution.map(planCard).join("")
    : `<div class="empty-state">Aktif execution plani yok.</div>`;
  els.laneAttention.innerHTML = lanes.attention.length
    ? lanes.attention.map(planCard).join("")
    : `<div class="empty-state">Dikkat isteyen plan yok.</div>`;
  els.laneDone.innerHTML = lanes.done.length
    ? lanes.done.map(planCard).join("")
    : `<div class="empty-state">Tamamlanan plan yok.</div>`;
  els.laneExecutionCount.textContent = String(lanes.execution.length);
  els.laneAttentionCount.textContent = String(lanes.attention.length);
  els.laneDoneCount.textContent = String(lanes.done.length);
}

function renderSelectedUser() {
  const user = state.users.find((row) => row.user_id === state.selectedUserId);
  if (!user) {
    els.selectedUser.innerHTML = `<div class="empty-state">Bir kullanici sec.</div>`;
    return;
  }
  const quota = user.quota || {};
  els.selectedUser.innerHTML = `
    <article class="mini-card detail-card">
      <div class="detail-meta">
        <h4>${h(user.user_id)}</h4>
        <span class="${quota.allowed === false ? "pill err" : "pill ok"}">${h(user.tier || "free")}</span>
      </div>
      <p>Subscription: ${h(user.subscription_status || "none")} | Expiry: ${h(fmtTs(user.expiry_at))}</p>
      <p>Daily usage: ${h(quota.daily_messages || 0)}/${h(quota.daily_limit || 0)} | Monthly tokens: ${h(quota.monthly_tokens || 0)}/${h(quota.monthly_limit || 0)}</p>
      <p>Lifetime messages: ${h(quota.lifetime_messages || 0)} | Failed tasks: ${h(user.failed_tasks || 0)}</p>
    </article>
  `;
}

function renderSelectedPlan() {
  const plan = state.plans.find((row) => row.task_id === state.selectedPlanId);
  if (!plan) {
    els.selectedPlan.innerHTML = `<div class="empty-state">Bir plan sec.</div>`;
    els.timeline.innerHTML = "";
    els.artifacts.innerHTML = `<div class="empty-state">Artifact yok.</div>`;
    els.subtasks.innerHTML = `<div class="empty-state">Subtask yok.</div>`;
    els.cancelTask.disabled = true;
    els.requeueTask.disabled = true;
    return;
  }
  els.selectedPlan.innerHTML = `
    <article class="mini-card detail-card">
      <div class="detail-meta">
        <h4>${h(plan.task_id)}</h4>
        <span class="${statePillClass(plan.state)}">${h(plan.state)}</span>
      </div>
      <p>${h(plan.objective || plan.summary || "Aciklama yok.")}</p>
      <p>User: ${h(plan.user_id || "local")} | Channel: ${h(plan.channel || "-")} | Mode: ${h(plan.mode || "-")}</p>
      <p>Workflow: ${h(plan.workflow_id || "-")} | Domain: ${h(plan.capability_domain || "-")}</p>
      ${plan.error ? `<p>Last error: ${h(plan.error)}</p>` : ""}
    </article>
  `;

  const history = Array.isArray(plan.history) ? plan.history : [];
  els.timeline.innerHTML = history.length
    ? history.map((item) => `
        <li>
          <strong>${h(item.state || "state")}</strong>
          <span>${h(fmtTs(item.ts))}</span>
          ${item.note ? `<span>${h(item.note)}</span>` : ""}
        </li>
      `).join("")
    : `<li><strong>Timeline yok</strong><span>Background task ya da history uretilmemis.</span></li>`;

  const artifacts = Array.isArray(plan.artifacts) ? plan.artifacts : [];
  els.artifacts.innerHTML = artifacts.length
    ? artifacts.map((item) => {
        if (typeof item === "string") {
          return `<article class="stack-item"><strong>Artifact</strong><p>${h(item)}</p></article>`;
        }
        return `<article class="stack-item"><strong>${h(item.type || "artifact")}</strong><p>${h(item.path || JSON.stringify(item))}</p></article>`;
      }).join("")
    : `<div class="empty-state">Artifact yok.</div>`;

  const subtasks = Array.isArray(plan.subtasks) ? plan.subtasks : [];
  els.subtasks.innerHTML = subtasks.length
    ? subtasks.map((item, index) => `
        <article class="stack-item">
          <strong>Subtask ${index + 1}</strong>
          <p>${h(item.title || item.action || item.description || JSON.stringify(item))}</p>
        </article>
      `).join("")
    : `<div class="empty-state">Subtask yok.</div>`;

  const background = String(plan.kind || "") === "background";
  els.cancelTask.disabled = !background;
  els.requeueTask.disabled = !background;
}

function renderAll() {
  renderOverview();
  renderUsers();
  renderBoard();
  renderSelectedUser();
  renderSelectedPlan();
}

function chooseDefaultSelections() {
  if (!state.selectedUserId && state.users.length) {
    state.selectedUserId = state.users[0].user_id;
  }
  const visiblePlans = filteredPlans();
  if (!visiblePlans.some((plan) => plan.task_id === state.selectedPlanId)) {
    state.selectedPlanId = visiblePlans[0]?.task_id || "";
  }
}

async function loadAll() {
  els.refresh.disabled = true;
  els.syncPill.textContent = "Senkronize ediliyor";
  els.syncPill.className = "pill warn";
  try {
    const [overview, users, plans] = await Promise.all([
      api("/api/admin/overview"),
      api("/api/admin/users"),
      api("/api/admin/plans?limit=200"),
    ]);
    state.overview = overview || {};
    state.users = Array.isArray(users?.users) ? users.users : [];
    state.plans = Array.isArray(plans?.plans) ? plans.plans : [];
    chooseDefaultSelections();
    renderAll();
    els.syncPill.textContent = "Ops console online";
    els.syncPill.className = "pill ok";
    els.lastSync.textContent = `Son senkron: ${new Date().toLocaleTimeString("tr-TR")}`;
  } catch (err) {
    console.error(err);
    els.syncPill.textContent = `Hata: ${err.message || err}`;
    els.syncPill.className = "pill err";
    els.lastSync.textContent = "Son senkron: basarisiz";
  } finally {
    els.refresh.disabled = false;
  }
}

async function updateTier(tier) {
  const userId = state.selectedUserId;
  if (!userId || !tier) return;
  els.syncPill.textContent = `${userId} -> ${tier}`;
  els.syncPill.className = "pill warn";
  try {
    await api(`/api/admin/users/${encodeURIComponent(userId)}/subscription`, {
      method: "POST",
      body: JSON.stringify({ tier }),
    });
    await loadAll();
  } catch (err) {
    console.error(err);
    els.syncPill.textContent = `Tier update hatasi: ${err.message || err}`;
    els.syncPill.className = "pill err";
  }
}

async function mutateBackgroundTask(action) {
  const plan = state.plans.find((row) => row.task_id === state.selectedPlanId);
  if (!plan || plan.kind !== "background") return;
  els.syncPill.textContent = `${action}: ${plan.task_id}`;
  els.syncPill.className = "pill warn";
  try {
    await api(`/api/admin/away-tasks/${encodeURIComponent(plan.task_id)}/action`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    await loadAll();
  } catch (err) {
    console.error(err);
    els.syncPill.textContent = `Task action hatasi: ${err.message || err}`;
    els.syncPill.className = "pill err";
  }
}

els.refresh.addEventListener("click", () => loadAll());
els.userSearch.addEventListener("input", () => {
  renderUsers();
});
els.stateFilter.addEventListener("change", () => {
  chooseDefaultSelections();
  renderBoard();
  renderSelectedPlan();
});
els.clearSelection.addEventListener("click", () => {
  state.selectedUserId = "";
  state.selectedPlanId = "";
  chooseDefaultSelections();
  renderAll();
});

els.userList.addEventListener("click", (event) => {
  const card = event.target.closest("[data-user-id]");
  if (!card) return;
  state.selectedUserId = card.dataset.userId || "";
  chooseDefaultSelections();
  renderAll();
});

document.addEventListener("click", (event) => {
  const card = event.target.closest("[data-plan-id]");
  if (!card) return;
  state.selectedPlanId = card.dataset.planId || "";
  const plan = state.plans.find((row) => row.task_id === state.selectedPlanId);
  if (plan?.user_id) {
    state.selectedUserId = String(plan.user_id);
  }
  renderUsers();
  renderBoard();
  renderSelectedUser();
  renderSelectedPlan();
});

for (const button of els.tierButtons) {
  button.addEventListener("click", () => updateTier(button.dataset.tier || ""));
}

els.cancelTask.addEventListener("click", () => mutateBackgroundTask("cancel"));
els.requeueTask.addEventListener("click", () => mutateBackgroundTask("requeue"));

loadAll();
window.setInterval(loadAll, 12000);
