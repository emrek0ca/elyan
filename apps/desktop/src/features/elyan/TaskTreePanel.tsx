/**
 * TaskTreePanel — Hierarchical task tree for active Elyan jobs.
 *
 * Visualizes: job → steps (decomposed tasks from TaskDecomposer)
 * Reads from runtime-store elyanActivities (running/done/error).
 */
import { ChevronDown, ChevronRight, Layers } from "@/vendor/lucide-react";
import { useState } from "react";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useRuntimeStore } from "@/stores/runtime-store";
import type { ElyanAgentActivity } from "@/stores/runtime-store";
import { cn } from "@/utils/cn";

// ── Tree node type (derived from flat activities) ────────────────────────────

interface TaskNode {
  id: string;
  agent: string;
  action: string;
  status: ElyanAgentActivity["status"];
  ts: number;
  children: TaskNode[];
}

/**
 * Group flat activities into a pseudo-tree:
 * "running" items become root nodes;
 * "done"/"error" items within the same second are shown as leaves.
 * Simple heuristic — good enough without a full job hierarchy from backend.
 */
function buildTree(activities: ElyanAgentActivity[]): TaskNode[] {
  if (!activities.length) return [];

  const roots: TaskNode[] = [];
  const runningMap = new Map<string, TaskNode>();

  for (const a of activities) {
    const node: TaskNode = { ...a, children: [] };
    if (a.status === "running") {
      roots.push(node);
      runningMap.set(a.agent, node);
    } else {
      // Attach to a running parent by agent name if possible
      const parent = runningMap.get(a.agent);
      if (parent) {
        parent.children.push(node);
      } else {
        roots.push(node);
      }
    }
  }

  return roots;
}

// ── StatusDot ────────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: ElyanAgentActivity["status"] }) {
  return (
    <div
      className={cn(
        "h-2 w-2 shrink-0 rounded-full",
        status === "running" && "animate-pulse bg-[var(--accent-primary)]",
        status === "done" && "bg-emerald-500",
        status === "error" && "bg-red-500",
      )}
    />
  );
}

// ── TaskRow ──────────────────────────────────────────────────────────────────

function TaskRow({
  node,
  depth = 0,
}: {
  node: TaskNode;
  depth?: number;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;

  return (
    <div>
      <div
        className={cn(
          "flex items-center gap-2 rounded-[10px] px-2.5 py-1.5 text-[11px] transition-colors",
          "hover:bg-[var(--glass-elevated)]",
          depth > 0 && "ml-5 border-l border-[var(--glass-border)] pl-3",
        )}
      >
        {/* Expand toggle */}
        <button
          onClick={() => setExpanded((v) => !v)}
          className={cn(
            "shrink-0 text-[var(--text-tertiary)]",
            !hasChildren && "invisible",
          )}
        >
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </button>

        <StatusDot status={node.status} />

        <span className="font-medium text-[var(--accent-primary)]">{node.agent}</span>
        <span className="flex-1 truncate text-[var(--text-secondary)]">{node.action}</span>

        <StatusBadge
          tone={
            node.status === "running" ? "info"
            : node.status === "done" ? "success"
            : "error"
          }
        >
          {node.status}
        </StatusBadge>

        <span className="shrink-0 text-[10px] text-[var(--text-tertiary)]">
          {new Date(node.ts).toLocaleTimeString("tr", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })}
        </span>
      </div>

      {/* Children */}
      {hasChildren && expanded && (
        <div>
          {node.children.map((child) => (
            <TaskRow key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── TaskTreePanel (main) ─────────────────────────────────────────────────────

export function TaskTreePanel() {
  const activities = useRuntimeStore((s) => s.elyanActivities);
  const tree = buildTree(activities);

  const runningCount = activities.filter((a) => a.status === "running").length;
  const errorCount = activities.filter((a) => a.status === "error").length;

  return (
    <Surface tone="card" className="p-5">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-[var(--text-tertiary)]">
          <Layers size={10} />
          Görev Ağacı
        </div>
        <div className="flex items-center gap-1.5">
          {runningCount > 0 && (
            <StatusBadge tone="info">{`${runningCount} aktif`}</StatusBadge>
          )}
          {errorCount > 0 && (
            <StatusBadge tone="error">{`${errorCount} hata`}</StatusBadge>
          )}
        </div>
      </div>

      {/* Tree */}
      {tree.length === 0 ? (
        <div className="flex h-16 items-center justify-center text-[12px] text-[var(--text-tertiary)]">
          Çalışan görev yok
        </div>
      ) : (
        <div className="space-y-0.5">
          {tree.map((node) => (
            <TaskRow key={node.id} node={node} />
          ))}
        </div>
      )}
    </Surface>
  );
}
