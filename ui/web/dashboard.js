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
    return fetch(url, opts || {})
      .then(function (r) { return r.json(); })
      .catch(function (e) { console.error("api", url, e); return { ok: false, error: e.message }; });
  }
  function GET(url) { return api(url); }
  function POST(url, body) {
    return api(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }

  /* ================================================================
     TABS
     ================================================================ */
  var tabMap = { llms: "p-llms", ollama: "p-ollama", status: "p-status", settings: "p-settings" };

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

  /* ================================================================
     PROVIDER META
     ================================================================ */
  var META = {
    groq:      { icon: "\uD83D\uDE80", label: "Groq",           note: "Ucretsiz, ultra hizli" },
    google:    { icon: "\uD83D\uDD35", label: "Google Gemini",   note: "Ucretsiz tier mevcut" },
    openai:    { icon: "\uD83E\uDD16", label: "OpenAI",          note: "GPT-4o, premium kalite" },
    anthropic: { icon: "\uD83E\uDDE0", label: "Anthropic Claude",note: "Reasoning ve kod" },
    deepseek:  { icon: "\u26A1",       label: "DeepSeek",        note: "Dusuk maliyet" },
    ollama:    { icon: "\uD83C\uDFE0", label: "Ollama",          note: "Yerel, gizlilik oncelikli" }
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
    html += '<div class="card-desc">' + esc(m.note) + (p.free ? " &middot; ucretsiz" : "") + "</div></div>";
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
    try {
      var s = JSON.parse(localStorage.getItem("elyan_settings") || "{}");
      if (s.primaryLLM) { var el = $("#s-primary"); if (el) el.value = s.primaryLLM; }
      if (s.strategy) { var el2 = $("#s-strategy"); if (el2) el2.value = s.strategy; }
      if (s.language) { var el3 = $("#s-lang"); if (el3) el3.value = s.language; }
      if (s.localFirst) { var el4 = $("#s-local"); if (el4) el4.checked = true; }
    } catch (e) { /* ignore */ }
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
      localStorage.setItem("elyan_settings", JSON.stringify(s));
      toast("Ayarlar kaydedildi", "ok");
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
    return Promise.all([loadProviders(), loadOllama(), loadHealth()]);
  }

  var refreshBtn = $("#g-refresh");
  if (refreshBtn) refreshBtn.addEventListener("click", function () { refreshAll(); });

  // Boot
  refreshAll().then(function () { loadSettings(); });
  connectWS();

  // Auto-refresh
  setInterval(refreshAll, 60000);
});
