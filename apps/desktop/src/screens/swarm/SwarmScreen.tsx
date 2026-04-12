import { Bot, Layers3, RefreshCw, UsersRound, Waypoints } from "@/vendor/lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Surface } from "@/components/primitives/Surface";
import { TaskTreePanel } from "@/features/elyan/TaskTreePanel";
import { useMultiAgentMetrics } from "@/hooks/use-desktop-data";

export function SwarmScreen() {
  const queryClient = useQueryClient();
  const { data, isLoading, error, refetch } = useMultiAgentMetrics();

  async function refreshAll() {
    await Promise.all([
      refetch(),
      queryClient.invalidateQueries({ queryKey: ["multi-agent-metrics"] }),
    ]);
  }

  if (error) {
    return <ErrorState title="Swarm görünümü yüklenemedi" description="Multi-agent metrikleri alınamadı." onRetry={() => void refetch()} />;
  }
  if (isLoading || !data) {
    return <SkeletonBlock className="h-[320px] w-full rounded-[32px]" />;
  }

  const handoffTotal = Number(data.handoffs.total || data.handoffs.count || 0);
  const handoffPending = Number(data.handoffs.pending || 0);
  const semanticCount = Number(data.semanticMemory.total_memories || data.semanticMemory.count || 0);

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-7 py-7">
        <div className="max-w-[780px] space-y-3">
          <div className="flex items-center gap-3">
            <Waypoints className="h-5 w-5 text-[var(--accent-primary)]" />
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Swarm</div>
          </div>
          <h1 className="font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Multi-agent execution
          </h1>
          <div className="text-[14px] text-[var(--text-secondary)]">
            Elyan’ın parallel orchestration yüzeyi. Hangi agent’lar kayıtlı, ne kadar yük altındalar, handoff ve memory trafiği nasıl akıyor burada görünür.
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge tone={data.activeContractCount > 0 ? "info" : "neutral"}>
              {data.activeContractCount} active contracts
            </StatusBadge>
            <StatusBadge tone={data.registeredAgents.length ? "success" : "neutral"}>
              {data.registeredAgents.length} registered agents
            </StatusBadge>
            <StatusBadge tone={handoffPending > 0 ? "warning" : "success"}>
              {handoffPending > 0 ? `${handoffPending} pending handoffs` : "handoffs clear"}
            </StatusBadge>
          </div>
        </div>
      </Surface>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile icon={UsersRound} label="Agents" value={String(data.registeredAgents.length)} meta={`${data.specialists.length} specialists`} />
        <MetricTile icon={Layers3} label="Contracts" value={String(data.activeContractCount)} meta={`${data.worldFactCount} world facts`} />
        <MetricTile icon={Bot} label="Handoffs" value={String(handoffTotal)} meta={handoffPending ? `${handoffPending} pending` : "no queue"} />
        <MetricTile icon={Waypoints} label="Memory" value={String(semanticCount)} meta="semantic items" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Surface tone="card" className="p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Registered agents</div>
              <div className="mt-2 text-[13px] text-[var(--text-secondary)]">Current contract net load and capability map.</div>
            </div>
            <Button variant="ghost" size="sm" onClick={() => void refreshAll()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
          </div>
          <div className="mt-4 space-y-3">
            {data.registeredAgents.map((agent) => (
              <div key={agent.agentId} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-[14px] font-medium text-[var(--text-primary)]">{agent.agentId}</div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                      {agent.capabilities.length ? agent.capabilities.join(", ") : "No explicit capabilities"}
                    </div>
                  </div>
                  <StatusBadge tone={agent.currentLoad > 0 ? "info" : "neutral"}>
                    {agent.currentLoad}/{agent.maxConcurrent}
                  </StatusBadge>
                </div>
                <div className="mt-3 h-2 rounded-full bg-[var(--bg-surface)]">
                  <div
                    className="h-2 rounded-full bg-[var(--accent-primary)]"
                    style={{ width: `${Math.max(8, Math.min(100, Math.round(agent.utilization * 100)))}%` }}
                  />
                </div>
                <div className="mt-2 text-[11px] text-[var(--text-tertiary)]">
                  Utilization {Math.round(agent.utilization * 100)}%
                </div>
              </div>
            ))}
            {!data.registeredAgents.length ? (
              <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[13px] text-[var(--text-secondary)]">
                No registered agents reported by runtime.
              </div>
            ) : null}
          </div>
        </Surface>

        <div className="space-y-6">
          <Surface tone="card" className="p-6">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Swarm state</div>
            <div className="mt-4 grid gap-3">
              <CompactRow label="Specialists" value={data.specialists.length ? data.specialists.join(", ") : "none"} />
              <CompactRow label="Model gateway" value={String(data.modelGateway.mode || data.modelGateway.strategy || "adaptive")} />
              <CompactRow label="Security posture" value={String(data.security.posture || data.security.deployment_scope || "balanced")} />
              <CompactRow label="World facts" value={String(data.worldFactCount)} />
            </div>
          </Surface>

          <TaskTreePanel />
        </div>
      </div>
    </div>
  );
}

function MetricTile({
  icon: Icon,
  label,
  value,
  meta,
}: {
  icon: typeof UsersRound;
  label: string;
  value: string;
  meta: string;
}) {
  return (
    <Surface tone="card" className="p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">{label}</div>
          <div className="mt-2 text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">{value}</div>
          <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{meta}</div>
        </div>
        <Icon className="h-5 w-5 text-[var(--accent-primary)]" />
      </div>
    </Surface>
  );
}

function CompactRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">{label}</div>
      <div className="mt-2 text-[13px] text-[var(--text-primary)]">{value}</div>
    </div>
  );
}
