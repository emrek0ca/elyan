import type { DispatchStatusSnapshot, DispatchTask } from './types';
import { summarizeDispatchTask } from './types';

export function buildDispatchStatusSnapshot(tasks: DispatchTask[]): DispatchStatusSnapshot {
  const queued = tasks.filter((task) => task.status === 'queued').length;
  const planning = tasks.filter((task) => task.status === 'planning').length;
  const executing = tasks.filter((task) => task.status === 'executing').length;
  const waitingApproval = tasks.filter((task) => task.status === 'waiting_approval').length;
  const exporting = tasks.filter((task) => task.status === 'exporting').length;
  const completed = tasks.filter((task) => task.status === 'completed').length;
  const failed = tasks.filter((task) => task.status === 'failed').length;
  const latest = tasks[0];

  return {
    status: failed > 0 ? 'degraded' : tasks.length > 0 ? 'healthy' : 'unknown',
    summary:
      tasks.length > 0
        ? `${tasks.length} dispatch task(s) · ${queued + planning + executing + waitingApproval + exporting} active`
        : 'No dispatch tasks recorded yet.',
    tasks: {
      total: tasks.length,
      queued,
      planning,
      executing,
      waitingApproval,
      exporting,
      completed,
      failed,
      latest: latest ? summarizeDispatchTask(latest) : undefined,
    },
  };
}

