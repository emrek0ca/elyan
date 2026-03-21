from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_MARKERS = ("wrangler.jsonc", "wrangler.toml")
SOURCE_MARKERS = ("src/server.ts", "src/client.tsx", "src/chat.ts", "src/workflows.ts", "src/mcp.ts")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _normalize_root(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


def _slugify(name: str) -> str:
    text = str(name or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "cloudflare-agents-starter"


def _safe_name(value: str) -> str:
    text = str(value or "").strip()
    return text or "Cloudflare Agents Starter"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _strip_jsonc_comments(text: str) -> str:
    lines = []
    for raw in str(text or "").splitlines():
        line = raw
        if "//" in line:
            idx = line.find("//")
            if idx >= 0:
                line = line[:idx]
        lines.append(line)
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_jsonc(path: Path) -> dict[str, Any]:
    try:
        return json.loads(_strip_jsonc_comments(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _dependency_names(payload: dict[str, Any]) -> set[str]:
    deps: set[str] = set()
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        raw = payload.get(section)
        if isinstance(raw, dict):
            deps.update(str(key).strip() for key in raw.keys() if str(key).strip())
    return deps


def _looks_like_cloudflare_agents_project(root: Path) -> bool:
    if any((root / marker).exists() for marker in PROJECT_MARKERS):
        return True
    if any((root / marker).exists() for marker in SOURCE_MARKERS):
        return True
    package_path = root / "package.json"
    if not package_path.exists():
        return False
    package = _read_json(package_path)
    deps = _dependency_names(package)
    scripts = package.get("scripts") if isinstance(package, dict) else {}
    script_text = " ".join(str(value) for value in scripts.values()) if isinstance(scripts, dict) else ""
    if "agents" in deps or "@cloudflare/ai-chat" in deps or "wrangler" in deps:
        return True
    if any(marker in script_text.lower() for marker in ("wrangler dev", "wrangler deploy")):
        return True
    name = str(package.get("name") or "").lower()
    return "cloudflare" in name and "agent" in name


def detect_project_root(start: str | Path | None = None) -> Path | None:
    candidate = _normalize_root(start) or Path.cwd().resolve()
    search = [candidate]
    search.extend(candidate.parents)
    for root in search:
        if _looks_like_cloudflare_agents_project(root):
            return root
    return None


def resolve_project_root(path: str | Path | None = None) -> Path | None:
    root = _normalize_root(path)
    if root and root.exists():
        return detect_project_root(root)
    return detect_project_root(path)


def summarize_project(root: str | Path) -> dict[str, Any]:
    root_path = _normalize_root(root)
    if root_path is None:
        return {}

    package_path = root_path / "package.json"
    wrangler_path = root_path / "wrangler.jsonc"
    server_path = root_path / "src" / "server.ts"
    client_path = root_path / "src" / "client.tsx"
    chat_path = root_path / "src" / "chat.ts"
    workflows_path = root_path / "src" / "workflows.ts"
    mcp_path = root_path / "src" / "mcp.ts"

    package = _read_json(package_path) if package_path.exists() else {}
    wrangler = _read_jsonc(wrangler_path) if wrangler_path.exists() else {}
    package_name = str(package.get("name") or wrangler.get("name") or root_path.name or "cloudflare-agents-starter")
    deps = _dependency_names(package)
    server_text = _read_text(server_path)
    client_text = _read_text(client_path)
    chat_text = _read_text(chat_path)
    workflows_text = _read_text(workflows_path)
    mcp_text = _read_text(mcp_path)
    readme_text = _read_text(root_path / "README.md")

    features: list[str] = []
    if "agents" in deps or "routeAgentRequest" in server_text:
        features.append("persistent_state")
    if "routeAgentRequest" in server_text:
        features.append("agent_routing")
    if "useAgent" in client_text:
        features.append("react_sync")
    if "useAgentChat" in client_text or "AIChatAgent" in chat_text:
        features.append("chat_ui")
    if "unstable_callable" in server_text or "callable" in server_text:
        features.append("callable_methods")
    if "this.schedule" in server_text or "workflow" in workflows_text.lower():
        features.append("workflows")
    if "this.sql" in server_text:
        features.append("sqlite_queries")
    if wrangler_path.exists():
        features.append("wrangler_config")
    if "new_sqlite_classes" in _read_text(wrangler_path):
        features.append("durable_object_sqlite")
    if chat_text or "useAgentChat" in readme_text:
        features.append("ai_chat")
    if mcp_path.exists() or "MCP" in mcp_text:
        features.append("mcp_notes")

    required = {"persistent_state", "agent_routing", "react_sync", "wrangler_config"}
    ready = required.issubset(set(features))

    return {
        "root": str(root_path),
        "name": package_name,
        "slug": _slugify(package_name),
        "status": "ready" if ready else "scaffolded",
        "ready": ready,
        "features": sorted(set(features)),
        "package_json_path": str(package_path),
        "wrangler_path": str(wrangler_path),
        "server_path": str(server_path),
        "client_path": str(client_path),
        "chat_path": str(chat_path),
        "workflows_path": str(workflows_path),
        "mcp_path": str(mcp_path),
        "package_dependencies": sorted(deps),
        "has_package_json": package_path.exists(),
        "has_wrangler": wrangler_path.exists(),
        "has_server": server_path.exists(),
        "has_client": client_path.exists(),
        "has_chat": chat_path.exists(),
        "has_workflows": workflows_path.exists(),
        "has_mcp": mcp_path.exists(),
        "compatibility_date": str(wrangler.get("compatibility_date") or ""),
        "updated_at": _now_iso(),
    }


def build_cloudflare_agents_prompt(
    action: str,
    *,
    project: dict[str, Any],
    goal: str = "",
    target: str = "",
    backend: str = "auto",
) -> str:
    root = str(project.get("root") or "").strip()
    name = str(project.get("name") or project.get("slug") or "Cloudflare Agents starter").strip()
    action_text = str(action or "starter").strip().lower() or "starter"
    lines = [
        "You are Elyan's Cloudflare Agents operator.",
        f"Project: {name}",
        f"Project root: {root}",
        f"Task: {action_text}",
        f"Backend: {backend}",
        "Use Cloudflare Agents patterns: Agent, routeAgentRequest, useAgent, useAgentChat, workflows, and MCP.",
        "Use Durable Object state, SQLite-backed persistence, and real-time sync through WebSockets.",
        "Prefer @unstable_callable for RPC methods and keep human-in-the-loop gates before destructive actions.",
        "Use this.schedule for follow-up tasks and this.sql for queryable state when the workflow needs durable history.",
    ]
    if goal:
        lines.append(f"Goal: {goal}")
    if target:
        lines.append(f"Target: {target}")
    lines.extend(
        [
            "Keep the starter small, explicit, and deployable on Cloudflare Workers.",
            "Return a compact plan, generated files, and the next deployment step.",
        ]
    )
    return "\n".join(lines)


def build_cloudflare_agents_bundle(
    action: str,
    *,
    project: dict[str, Any],
    goal: str = "",
    target: str = "",
    backend: str = "auto",
) -> dict[str, Any]:
    root = str(project.get("root") or "").strip()
    bundle_id = f"cloudflare_agents_{str(action or 'starter').strip().lower() or 'starter'}"
    prompt = build_cloudflare_agents_prompt(action, project=project, goal=goal, target=target, backend=backend)
    steps = [
        {
            "id": "inspect_workspace",
            "action": "cloudflare_agents_project",
            "params": {"action": "status", "path": root},
        },
        {
            "id": "scaffold_agents_app",
            "action": "cloudflare_agents_scaffold",
            "params": {"path": root, "name": project.get("name") or ""},
        },
        {
            "id": "review_bundle",
            "action": "cloudflare_agents_workflow",
            "params": {"action": str(action or "starter"), "path": root, "goal": goal, "target": target, "backend": backend},
        },
    ]
    return {
        "id": bundle_id,
        "name": "Cloudflare Agents Starter",
        "category": "cloud",
        "required_skills": ["cloudflare_agents", "code", "research"],
        "required_tools": ["cloudflare_agents_status", "cloudflare_agents_project", "cloudflare_agents_scaffold", "cloudflare_agents_workflow"],
        "steps": steps,
        "trigger_markers": [
            "cloudflare agents",
            "agents starter",
            "routeAgentRequest",
            "useAgent",
            "useAgentChat",
            "durable objects",
            "wrangler",
            "mcp",
            "workflow",
            "human in the loop",
        ],
        "objective": "scaffold_cloudflare_agents_app",
        "prompt": prompt,
        "command": "npm create cloudflare@latest -- --template cloudflare/agents-starter",
        "project_root": root,
        "project_name": str(project.get("name") or ""),
        "output_artifacts": ["wrangler_jsonc", "server_ts", "client_tsx", "chat_ts", "workflow_notes", "mcp_notes"],
        "quality_checklist": [
            "persistent_state",
            "agent_routing",
            "realtime_sync",
            "callable_methods",
            "workflow_hooks",
            "mcp_ready",
            "deploy_readiness",
        ],
        "auto_intent": True,
    }


def _render_package_json(name: str, include_chat: bool) -> str:
    dependencies = {
        "agents": "latest",
        "react": "latest",
        "react-dom": "latest",
    }
    if include_chat:
        dependencies["@cloudflare/ai-chat"] = "latest"
    dev_dependencies = {
        "@cloudflare/workers-types": "latest",
        "@types/react": "latest",
        "@types/react-dom": "latest",
        "typescript": "latest",
        "wrangler": "latest",
    }
    payload = {
        "name": _slugify(name),
        "private": True,
        "type": "module",
        "scripts": {
            "dev": "wrangler dev",
            "deploy": "wrangler deploy",
            "check": "tsc --noEmit",
        },
        "dependencies": dependencies,
        "devDependencies": dev_dependencies,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _render_wrangler_jsonc(name: str, include_chat: bool) -> str:
    classes = ["CloudflareAgent"]
    if include_chat:
        classes.append("ChatAgent")
    payload = {
        "$schema": "./node_modules/wrangler/config-schema.json",
        "name": _slugify(name),
        "main": "src/server.ts",
        "compatibility_date": _today(),
        "compatibility_flags": ["nodejs_compat"],
        "durable_objects": {
            "bindings": [
                {"name": "CF_AGENT", "class_name": "CloudflareAgent"},
            ]
        },
        "migrations": [
            {
                "tag": "v1",
                "new_sqlite_classes": classes,
            }
        ],
        "vars": {
            "APP_NAME": _safe_name(name),
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _render_server_ts(name: str) -> str:
    app_name = _safe_name(name)
    return f'''import {{ Agent, type AgentNamespace, routeAgentRequest, unstable_callable }} from "agents";

export interface Env {{
  CF_AGENT: AgentNamespace<CloudflareAgent>;
}}

export interface CloudflareAgentState {{
  title: string;
  status: "idle" | "online" | "busy";
  messages: Array<{{ role: string; content: string; createdAt: string }}>;
  lastUpdated: string;
}}

export class CloudflareAgent extends Agent<Env, CloudflareAgentState> {{
  initialState: CloudflareAgentState = {{
    title: "{app_name}",
    status: "idle",
    messages: [],
    lastUpdated: new Date().toISOString(),
  }};

  @unstable_callable({{ description: "Rename the agent workspace" }})
  async rename(title: string) {{
    const next = {{ ...this.state, title: String(title || "").trim() || this.state.title, lastUpdated: new Date().toISOString() }};
    this.setState(next);
    return next;
  }}

  @unstable_callable({{ description: "Append a chat message to the agent state" }})
  async appendMessage(content: string) {{
    const next = {{
      ...this.state,
      status: "busy",
      messages: [
        ...this.state.messages,
        {{ role: "user", content: String(content || "").trim(), createdAt: new Date().toISOString() }},
      ],
      lastUpdated: new Date().toISOString(),
    }};
    this.setState(next);
    return next;
  }}

  @unstable_callable({{ description: "Return a snapshot of the current state" }})
  async snapshot() {{
    return this.state;
  }}

  @unstable_callable({{ description: "Schedule a short follow-up check" }})
  async scheduleFollowUp() {{
    await this.schedule("*/5 * * * *", "refreshState", {{ source: "elyan" }});
    return {{ success: true, scheduled: true }};
  }}

  @unstable_callable({{ description: "Read recent activity from SQLite" }})
  async recentActivity() {{
    return this.sql`SELECT * FROM activity ORDER BY created_at DESC LIMIT 10`;
  }}

  async onConnect() {{
    this.setState({{ ...this.state, status: "online", lastUpdated: new Date().toISOString() }});
  }}

  async onMessage(message: string) {{
    this.setState({{
      ...this.state,
      messages: [...this.state.messages, {{ role: "assistant", content: String(message || ""), createdAt: new Date().toISOString() }}],
      lastUpdated: new Date().toISOString(),
    }});
  }}
}}

export default {{
  async fetch(request: Request, env: Env, ctx: ExecutionContext) {{
    return (await routeAgentRequest(request, env, {{ cors: true }})) || new Response("Not found", {{ status: 404 }});
  }},
}} satisfies ExportedHandler<Env>;
'''


def _render_chat_ts(name: str) -> str:
    app_name = _safe_name(name)
    return f'''import {{ AIChatAgent }} from "@cloudflare/ai-chat";
import type {{ Env }} from "./server";

export class ChatAgent extends AIChatAgent<Env> {{
  initialState = {{
    title: "{app_name} Chat",
  }};

  // Add tools, HITL gates, and model configuration here.
}}
'''


def _render_client_tsx(name: str) -> str:
    app_name = _safe_name(name)
    return f'''import {{ useAgent }} from "agents/react";
import {{ useAgentChat }} from "agents/ai-react";
import {{ useState }} from "react";
import type {{ CloudflareAgentState }} from "./server";

export default function App() {{
  const [state, setState] = useState<CloudflareAgentState>({{
    title: "{app_name}",
    status: "idle",
    messages: [],
    lastUpdated: new Date().toISOString(),
  }});

  const agent = useAgent({{
    agent: "CloudflareAgent",
    name: "main",
    onStateUpdate: setState,
  }});

  const chat = useAgentChat({{
    agent: useAgent({{
      agent: "ChatAgent",
      name: "main",
    }}),
    experimental_automaticToolResolution: true,
  }});

  const messages = Array.isArray(chat.messages) ? chat.messages : [];

  return (
    <main style={{{{ fontFamily: "Inter, system-ui, sans-serif", padding: "32px" }}}}>
      <section>
        <h1>{{state.title}}</h1>
        <p>Status: {{state.status}}</p>
        <button onClick={{() => agent.stub.rename?.("{app_name} Live")}}>Rename</button>
        <button onClick={{() => agent.stub.appendMessage?.("Hello from Elyan")}}>Append message</button>
      </section>
      <section style={{{{ marginTop: 24 }}}}>
        <h2>Chat</h2>
        <button
          onClick={{() =>
            chat.sendMessage({{
              role: "user",
              parts: [{{ type: "text", text: "Hello from Cloudflare Agents" }}],
            }})
          }}
        >
          Send greeting
        </button>
        <pre>{{JSON.stringify(messages, null, 2)}}</pre>
      </section>
    </main>
  );
}}
'''


def _render_workflows_ts(name: str) -> str:
    app_name = _safe_name(name)
    return f'''export const workflowNotes = {{
  app: "{app_name}",
  scheduler: "Use this.schedule for delayed follow-ups, maintenance, or approvals.",
  humanInTheLoop: "Pause before destructive actions and resume after approval.",
  durableState: "Prefer the agent's SQLite-backed state for durable history.",
}};
'''


def _render_mcp_ts(name: str) -> str:
    app_name = _safe_name(name)
    return f'''export const mcpNotes = {{
  app: "{app_name}",
  server: "Cloudflare Agents can act as an MCP server.",
  client: "Cloudflare Agents can also connect as an MCP client.",
  nextStep: "Add the MCP transport and tool registry that fits your deployment model.",
}};
'''


def _render_readme(name: str, include_chat: bool, include_workflows: bool, include_mcp: bool) -> str:
    lines = [
        f"# {_safe_name(name)}",
        "",
        "Cloudflare Agents starter generated by Elyan.",
        "",
        "## What is included",
        "",
        "- `Agent` + `routeAgentRequest` for persistent, stateful runtime handling.",
        "- `useAgent` for real-time React state sync.",
    ]
    if include_chat:
        lines.append("- `AIChatAgent` + `useAgentChat` for persistent chat.")
    if include_workflows:
        lines.append("- Workflow notes for scheduling and human-in-the-loop approval.")
    if include_mcp:
        lines.append("- MCP notes for server/client integration.")
    lines.extend(
        [
            "",
            "## Quick start",
            "",
            "```sh",
            "npm install",
            "npm run dev",
            "npm run deploy",
            "```",
            "",
            "## Notes",
            "",
            "- `wrangler.jsonc` uses `new_sqlite_classes` for Durable Object state.",
            "- Use `@unstable_callable` for direct client RPC methods.",
            "- Use `this.schedule` for follow-ups and `this.sql` for durable history queries.",
        ]
    )
    return "\n".join(lines) + "\n"


def scaffold_project(
    root: str | Path,
    *,
    name: str = "",
    include_chat: bool = True,
    include_workflows: bool = True,
    include_mcp: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root_path = _normalize_root(root)
    if root_path is None:
        raise ValueError("project root is required")

    root_path.mkdir(parents=True, exist_ok=True)
    src_dir = root_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "package.json": _render_package_json(name or root_path.name, include_chat),
        "wrangler.jsonc": _render_wrangler_jsonc(name or root_path.name, include_chat),
        "src/server.ts": _render_server_ts(name or root_path.name),
        "src/client.tsx": _render_client_tsx(name or root_path.name),
        "README.md": _render_readme(name or root_path.name, include_chat, include_workflows, include_mcp),
        "tsconfig.json": json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "ESNext",
                    "moduleResolution": "Bundler",
                    "jsx": "react-jsx",
                    "strict": True,
                    "allowJs": False,
                    "types": ["@cloudflare/workers-types"],
                },
                "include": ["src/**/*.ts", "src/**/*.tsx"],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    }
    if include_chat:
        files["src/chat.ts"] = _render_chat_ts(name or root_path.name)
    if include_workflows:
        files["src/workflows.ts"] = _render_workflows_ts(name or root_path.name)
    if include_mcp:
        files["src/mcp.ts"] = _render_mcp_ts(name or root_path.name)

    writes: list[dict[str, Any]] = []
    for rel_path, content in files.items():
        target = root_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        if dry_run:
            writes.append({"path": str(target), "status": "planned", "existed": existed})
            continue
        if existed and not force:
            writes.append({"path": str(target), "status": "skipped", "existed": True})
            continue
        target.write_text(content, encoding="utf-8")
        writes.append({"path": str(target), "status": "updated" if existed else "created", "existed": existed})

    project = summarize_project(root_path)
    command = "npm install && npm run dev"
    if include_chat:
        command = "npm install && npm run dev"
    return {
        "success": True,
        "status": "partial" if dry_run else "success",
        "project": project,
        "files": writes,
        "command": command,
        "next_steps": [
            "Install dependencies and start the local Workers dev server.",
            "Use the stateful agent for real-time UI sync.",
            "If you need chat, extend ChatAgent with tools and add your model binding.",
        ],
        "generated_at": _now_iso(),
    }
