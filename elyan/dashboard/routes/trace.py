from __future__ import annotations

import json
from html import escape
from typing import Any

from elyan.verifier.evidence import build_trace_bundle


def _evidence_card(item: dict) -> str:
    title = str(item.get("label") or item.get("kind") or "Evidence")
    summary = str(item.get("summary") or item.get("display_path") or "")
    url = str(item.get("url") or "")
    kind = str(item.get("media_kind") or "file")
    preview = ""
    if url and kind == "image":
        preview = f'<img src="{escape(url)}" alt="{escape(title)}" class="trace-preview" loading="lazy" />'
    elif url and kind == "video":
        preview = f'<video src="{escape(url)}" controls class="trace-preview"></video>'
    else:
        preview = f'<div class="trace-preview trace-fallback">{escape(kind.upper())}</div>'
    meta = []
    if item.get("node_id"):
        meta.append(f'node:{item.get("node_id")}')
    if item.get("mime_type"):
        meta.append(str(item.get("mime_type")))
    if item.get("size_bytes"):
        meta.append(f'{int(item.get("size_bytes") or 0)} bytes')
    footer = " • ".join(meta)
    link = ""
    if url:
        link = f'<a href="{escape(url)}" target="_blank" rel="noreferrer" class="trace-link">Aç</a>'
    return (
        '<article class="trace-evidence-card">'
        f"{preview}"
        f'<div class="trace-evidence-body"><strong>{escape(title)}</strong>'
        f'<p>{escape(summary)}</p>'
        f'<div class="trace-evidence-meta">{escape(footer)}</div>'
        f"{link}"
        '</div></article>'
    )


def _live_item(item: dict) -> str:
    label = str(item.get("label") or item.get("kind") or item.get("type") or "event")
    status = str(item.get("status") or "")
    detail = item.get("detail")
    detail_text = json.dumps(detail, ensure_ascii=False, indent=2) if isinstance(detail, (dict, list)) else str(detail or "")
    return (
        '<div class="trace-live-item">'
        f'<strong>{escape(label)}</strong>'
        f'<p>{escape(status)}</p>'
        f'<pre>{escape(detail_text[:1000])}</pre>'
        '</div>'
    )


def render_trace_page(task_id: str, *, bundle: dict[str, Any] | None = None) -> str:
    bundle = dict(bundle or build_trace_bundle(task_id))
    history = dict(bundle.get("history") or {})
    evidence = list(bundle.get("evidence") or [])
    live_events = list(history.get("live_events") or [])
    summary = dict(history.get("summary") or {})
    control = dict(history.get("control") or {})
    decision_trace = json.dumps(history.get("decision_trace") or {}, ensure_ascii=False, indent=2)
    live_seed = json.dumps(live_events, ensure_ascii=False)
    evidence_cards = "".join(_evidence_card(item) for item in evidence) or '<div class="trace-empty">Evidence yok.</div>'
    timeline_items = list(history.get("timeline") or [])
    timeline_html = "".join(
        f'<div class="trace-timeline-item"><strong>{escape(str(item.get("label") or item.get("event_type") or item.get("kind") or "event"))}</strong><p>{escape(str(item.get("status") or ""))} • {escape(str(item.get("created_at") or item.get("timestamp") or ""))}</p></div>'
        for item in timeline_items
    ) or '<div class="trace-empty">Timeline yok.</div>'
    approval_items = list(history.get("approvals") or [])
    approvals_html = "".join(
        f'<div class="trace-approval-item"><strong>{escape(str(item.get("title") or item.get("operation") or "approval"))}</strong><p>{escape(str(item.get("status") or ""))}</p></div>'
        for item in approval_items
    ) or '<div class="trace-empty">Approval yok.</div>'
    title = escape(str(history.get("goal") or history.get("skill_name") or task_id or "Task Trace"))
    status = escape(str(history.get("status") or "missing"))
    route_mode = escape(str(history.get("route_mode") or "-"))
    risk_profile = escape(str(history.get("risk_profile") or "-"))
    task_id_value = escape(str(task_id or history.get("task_id") or ""))
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Elyan Trace • {title}</title>
  <style>
    :root{{color-scheme:dark;--bg:#050816;--panel:#0b1224;--panel-2:#11192f;--line:#223153;--text:#eef2ff;--muted:#94a3b8;--accent:#7dd3fc;--good:#34d399;--warn:#fbbf24;--bad:#fb7185;--r:18px;--shadow:0 20px 60px rgba(0,0,0,.35)}}
    *{{box-sizing:border-box}} html,body{{min-height:100%}} body{{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:radial-gradient(circle at top left,rgba(125,211,252,.14),transparent 30%),radial-gradient(circle at top right,rgba(52,211,153,.12),transparent 25%),var(--bg);color:var(--text)}}
    a{{color:inherit}} .shell{{max-width:1400px;margin:0 auto;padding:28px 20px 56px}} .hero{{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;margin-bottom:18px}} .eyebrow{{color:var(--accent);text-transform:uppercase;letter-spacing:.18em;font-size:11px;font-weight:700;margin-bottom:10px}}
    h1{{margin:0;font-size:42px;line-height:1.02;letter-spacing:-.04em}} .sub{{margin-top:10px;color:var(--muted);max-width:920px;font-size:15px;line-height:1.6}}
    .toolbar,.cards,.layout{{display:grid;gap:16px}} .toolbar{{grid-template-columns:1fr auto auto;align-items:center;background:rgba(11,18,36,.72);backdrop-filter:blur(18px);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px;box-shadow:var(--shadow)}}
    .input{{width:100%;padding:13px 14px;border-radius:14px;border:1px solid var(--line);background:var(--panel-2);color:var(--text);font-size:14px}} .input:focus{{outline:none;border-color:rgba(125,211,252,.55);box-shadow:0 0 0 3px rgba(125,211,252,.12)}}
    .btn{{display:inline-flex;align-items:center;justify-content:center;border:none;border-radius:14px;padding:12px 16px;font-weight:700;cursor:pointer;white-space:nowrap}} .btn-primary{{background:linear-gradient(135deg,#38bdf8,#22c55e);color:#04111f}} .btn-secondary{{background:var(--panel-2);color:var(--text);border:1px solid var(--line)}}
    .kpis{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin:18px 0}} .kpi{{background:rgba(11,18,36,.78);border:1px solid var(--line);border-radius:var(--r);padding:16px;box-shadow:var(--shadow)}} .kpi span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.14em}} .kpi strong{{display:block;font-size:24px;margin-top:8px}}
    .layout{{grid-template-columns:minmax(0,1.2fr) minmax(360px,.9fr)}} .panel{{background:rgba(11,18,36,.78);border:1px solid var(--line);border-radius:var(--r);padding:18px;box-shadow:var(--shadow)}} .panel h2{{margin:0 0 14px;font-size:18px}} .panel p.lead{{margin:0 0 12px;color:var(--muted)}}
    pre{{margin:0;white-space:pre-wrap;word-break:break-word;background:#060b18;border:1px solid var(--line);border-radius:14px;padding:16px;font-size:13px;line-height:1.55;color:#dbeafe;max-height:560px;overflow:auto}}
    .trace-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}} .trace-card,.trace-evidence-card,.trace-live-item,.trace-timeline-item,.trace-approval-item{{background:var(--panel-2);border:1px solid var(--line);border-radius:16px;padding:14px}}
    .trace-card span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.14em}} .trace-card strong{{display:block;font-size:20px;margin-top:6px}}
    .trace-evidence-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}} .trace-evidence-card{{padding:0;overflow:hidden}} .trace-preview{{width:100%;aspect-ratio:16/10;object-fit:cover;display:block;background:#030712;border-bottom:1px solid var(--line)}} .trace-fallback{{display:flex;align-items:center;justify-content:center;font-size:18px;color:var(--accent)}}
    .trace-evidence-body{{padding:14px}} .trace-evidence-body strong{{display:block;margin-bottom:6px}} .trace-evidence-body p{{margin:0;color:var(--muted);font-size:13px;line-height:1.5}} .trace-evidence-meta{{margin-top:10px;color:#cbd5e1;font-size:12px}} .trace-link{{display:inline-flex;margin-top:12px;color:var(--accent);text-decoration:none;font-weight:700}}
    .subgrid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}} .trace-live{{display:grid;gap:10px;max-height:420px;overflow:auto}} .trace-live-item strong,.trace-timeline-item strong,.trace-approval-item strong{{display:block;margin-bottom:4px}} .trace-live-item p,.trace-timeline-item p,.trace-approval-item p{{margin:0;color:var(--muted);font-size:13px;line-height:1.5}} .trace-live-item pre{{max-height:none;background:#060b18}}
    .trace-empty{{padding:16px;border:1px dashed var(--line);border-radius:14px;color:var(--muted);text-align:center}}
    .meta-line{{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;color:#cbd5e1;font-size:12px}} .meta-line span{{padding:5px 9px;border-radius:999px;background:rgba(148,163,184,.12)}} .good{{color:var(--good)}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}} .footer{{margin-top:18px;display:flex;justify-content:space-between;gap:14px;align-items:center;color:var(--muted);font-size:12px}}
    @media(max-width:1080px){{.kpis,.layout,.subgrid{{grid-template-columns:1fr}} .toolbar{{grid-template-columns:1fr;align-items:stretch}} .trace-grid{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
  <div class="shell">
    <div class="hero">
      <div>
        <div class="eyebrow">Elyan Trace Viewer</div>
        <h1>{title}</h1>
        <div class="sub">Decision trace, evidence gallery ve canlı operasyon akışı tek sayfada. Task ID: <strong>{task_id_value}</strong>.</div>
      </div>
      <div class="meta-line">
        <span>Status: <strong class="{'good' if status == 'completed' else 'warn' if status in {'queued', 'running', 'waiting_approval'} else 'bad'}">{status}</strong></span>
        <span>Route: {route_mode}</span>
        <span>Risk: {risk_profile}</span>
      </div>
    </div>

    <div class="toolbar">
      <input class="input" id="trace-task-input" value="{task_id_value}" placeholder="Task / mission id" />
      <button class="btn btn-primary" id="trace-load-btn" type="button">Load</button>
      <button class="btn btn-secondary" id="trace-open-btn" type="button">Open full trace</button>
    </div>

    <div class="kpis">
      <div class="kpi"><span>Status</span><strong>{escape(status or '-')}</strong></div>
      <div class="kpi"><span>Evidence</span><strong>{len(evidence)}</strong></div>
      <div class="kpi"><span>Approvals</span><strong>{len(approval_items)}</strong></div>
      <div class="kpi"><span>Timeline</span><strong>{len(timeline_items)}</strong></div>
      <div class="kpi"><span>Controls</span><strong>{int(control.get('node_count', 0) or 0)}</strong></div>
    </div>

    <div class="layout">
      <div class="panel">
        <h2>Decision Trace</h2>
        <p class="lead">Runtime kararları, graph state ve control summary.</p>
        <div class="trace-grid">
          <div class="trace-card"><span>Goal</span><strong>{escape(str(history.get('goal') or '-'))}</strong></div>
          <div class="trace-card"><span>Mode</span><strong>{escape(str(history.get('mode') or '-'))}</strong></div>
          <div class="trace-card"><span>Route</span><strong>{escape(str(history.get('route_mode') or '-'))}</strong></div>
          <div class="trace-card"><span>Progress</span><strong>{escape(str(control.get('progress') or 0))}</strong></div>
        </div>
        <div style="margin-top:14px">
          <pre id="trace-decision">{escape(decision_trace)}</pre>
        </div>
      </div>

      <div class="panel">
        <h2>Evidence Gallery</h2>
        <p class="lead">Kanıt, ekran görüntüsü, video ve artifact'ler.</p>
        <div class="trace-evidence-grid" id="trace-evidence">{evidence_cards}</div>
      </div>
    </div>

    <div class="layout" style="margin-top:16px">
      <div class="panel">
        <h2>Timeline</h2>
        <div class="subgrid">
          <div>
            {timeline_html}
          </div>
          <div>
            {approvals_html}
          </div>
        </div>
      </div>
      <div class="panel">
        <h2>Live Stream</h2>
        <p class="lead">WebSocket dashboard event feed.</p>
        <div class="trace-live" id="trace-live"></div>
      </div>
    </div>

    <div class="footer">
      <div><a href="/dashboard">Back to dashboard</a></div>
      <div>Live stream follows /ws/dashboard</div>
    </div>
  </div>

  <script>
    window.__ELYAN_TRACE_TASK_ID__ = {json.dumps(str(task_id_value))};
    window.__ELYAN_TRACE_LIVE__ = {live_seed};
    (function() {{
      var input = document.getElementById("trace-task-input");
      var loadBtn = document.getElementById("trace-load-btn");
      var openBtn = document.getElementById("trace-open-btn");
      var live = document.getElementById("trace-live");
      var pageTask = window.__ELYAN_TRACE_TASK_ID__ || "";
      function esc(s) {{
        return String(s == null ? "" : s);
      }}
      function renderLive(items) {{
        if (!live) return;
        if (!items || !items.length) {{
          live.innerHTML = '<div class="trace-empty">Live event yok.</div>';
          return;
        }}
        live.innerHTML = items.slice(-20).map(function (item) {{
          return '<div class="trace-live-item"><strong>' + esc(item.label || item.type || "event") + '</strong><p>' + esc(item.status || "") + '</p><pre>' + esc(JSON.stringify(item.detail || item, null, 2).slice(0, 1200)) + '</pre></div>';
        }}).join("");
      }}
      renderLive(window.__ELYAN_TRACE_LIVE__ || []);
      async function reload() {{
        var taskId = (input && input.value || pageTask || "").trim();
        if (!taskId) return;
        var url = "/api/trace/" + encodeURIComponent(taskId);
        try {{
          var res = await fetch(url, {{ credentials: "same-origin" }});
          var data = await res.json();
          if (data && data.ok && data.trace) {{
            pageTask = taskId;
            document.getElementById("trace-decision").textContent = JSON.stringify(data.trace.decision_trace || {{}}, null, 2);
            var evidence = data.trace.evidence || [];
            var root = document.getElementById("trace-evidence");
            if (root) {{
              root.innerHTML = evidence.length ? evidence.map(function (item) {{
                var preview = item.url && item.media_kind === "image"
                  ? '<img src="' + item.url + '" alt="' + esc(item.label || "Evidence") + '" class="trace-preview" loading="lazy" />'
                  : (item.url && item.media_kind === "video"
                    ? '<video src="' + item.url + '" controls class="trace-preview"></video>'
                    : '<div class="trace-preview trace-fallback">' + esc(String(item.media_kind || "FILE").toUpperCase()) + '</div>');
                return '<article class="trace-evidence-card">' + preview + '<div class="trace-evidence-body"><strong>' + esc(item.label || item.kind || "Evidence") + '</strong><p>' + esc(item.summary || item.display_path || "") + '</p></div></article>';
              }}).join("") : '<div class="trace-empty">Evidence yok.</div>';
            }}
            renderLive(data.trace.live_events || []);
          }}
        }} catch (err) {{
          console.error(err);
        }}
      }}
      if (loadBtn) loadBtn.addEventListener("click", reload);
      if (input) input.addEventListener("keydown", function (evt) {{ if (evt.key === "Enter") {{ evt.preventDefault(); reload(); }} }});
      if (openBtn) openBtn.addEventListener("click", function () {{ var taskId = (input && input.value || pageTask || "").trim(); if (taskId) window.open("/trace/" + encodeURIComponent(taskId), "_blank", "noopener"); }});
      try {{
        var proto = location.protocol === "https:" ? "wss:" : "ws:";
        var ws = new WebSocket(proto + "//" + location.host + "/ws/dashboard");
        ws.onmessage = function (e) {{
          try {{
            var msg = JSON.parse(e.data);
            var payload = msg.data || msg.payload || msg;
            if (!payload) return;
            var text = JSON.stringify(payload);
            var current = (input && input.value || pageTask || "").trim();
            if (current && text.indexOf(current) < 0) return;
            var items = window.__ELYAN_TRACE_LIVE__ || [];
            items = items.concat([{{ label: msg.event || "event", status: msg.channel || "", detail: payload }}]);
            window.__ELYAN_TRACE_LIVE__ = items.slice(-40);
            renderLive(window.__ELYAN_TRACE_LIVE__);
          }} catch (err) {{}}
        }};
      }} catch (err) {{}}
      if (pageTask) {{
        setTimeout(reload, 0);
      }}
    }})();
  </script>
</body>
</html>"""


__all__ = ["render_trace_page"]
