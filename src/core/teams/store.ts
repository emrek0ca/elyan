import { mkdir, readdir, readFile, rename, writeFile } from 'fs/promises';
import path from 'path';
import { randomUUID } from 'crypto';
import { env } from '@/lib/env';
import {
  teamArtifactSchema,
  teamEventSchema,
  teamPlanSchema,
  teamRunSummarySchema,
  type TeamArtifact,
  type TeamEvent,
  type TeamPlan,
  type TeamRunSummary,
} from './types';

function getTeamRunsRoot() {
  return path.resolve(process.cwd(), env.ELYAN_STORAGE_DIR, 'team-runs');
}

async function writeJsonAtomic(filePath: string, value: unknown) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${randomUUID()}.tmp`;
  await writeFile(tempPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await rename(tempPath, filePath);
}

async function readJsonFile<T>(filePath: string, schema: { parse(value: unknown): T }) {
  const raw = await readFile(filePath, 'utf8');
  return schema.parse(JSON.parse(raw));
}

export class TeamRunStore {
  constructor(private readonly rootDir = getTeamRunsRoot()) {}

  getRunDir(runId: string) {
    return path.join(this.rootDir, runId);
  }

  async createRun(plan: TeamPlan) {
    const parsed = teamPlanSchema.parse(plan);
    const runDir = this.getRunDir(parsed.runId);
    await mkdir(runDir, { recursive: true });
    await writeJsonAtomic(path.join(runDir, 'plan.json'), parsed);
    await writeJsonAtomic(path.join(runDir, 'artifacts.json'), []);
    await this.appendEvent({
      id: randomUUID(),
      runId: parsed.runId,
      type: 'plan_created',
      createdAt: new Date().toISOString(),
      data: {
        taskCount: parsed.tasks.length,
        agentCount: parsed.agents.length,
      },
    });
  }

  async appendEvent(event: TeamEvent) {
    const parsed = teamEventSchema.parse(event);
    const runDir = this.getRunDir(parsed.runId);
    await mkdir(runDir, { recursive: true });
    await writeFile(path.join(runDir, 'events.jsonl'), `${JSON.stringify(parsed)}\n`, {
      encoding: 'utf8',
      flag: 'a',
    });
  }

  async writeArtifacts(runId: string, artifacts: TeamArtifact[]) {
    const parsed = artifacts.map((artifact) => teamArtifactSchema.parse(artifact));
    await writeJsonAtomic(path.join(this.getRunDir(runId), 'artifacts.json'), parsed);
  }

  async writeSummary(summary: TeamRunSummary) {
    const parsed = teamRunSummarySchema.parse(summary);
    await writeJsonAtomic(path.join(this.getRunDir(parsed.runId), 'summary.json'), parsed);
  }

  async readPlan(runId: string) {
    return readJsonFile(path.join(this.getRunDir(runId), 'plan.json'), teamPlanSchema);
  }

  async readSummary(runId: string) {
    return readJsonFile(path.join(this.getRunDir(runId), 'summary.json'), teamRunSummarySchema);
  }

  async listRecentSummaries(limit = 5): Promise<TeamRunSummary[]> {
    let entries: string[];

    try {
      entries = await readdir(this.rootDir);
    } catch {
      return [];
    }

    const summaries = await Promise.allSettled(
      entries.map((entry) => this.readSummary(entry))
    );

    return summaries
      .filter((result): result is PromiseFulfilledResult<TeamRunSummary> => result.status === 'fulfilled')
      .map((result) => result.value)
      .sort((left, right) => right.finishedAt.localeCompare(left.finishedAt))
      .slice(0, limit);
  }
}

export const teamRunStore = new TeamRunStore();

export async function readTeamRuntimeStatus() {
  const recentRuns = await teamRunStore.listRecentSummaries(5);
  const latest = recentRuns[0];

  return {
    configured: true,
    recentRuns,
    summary: {
      recentRunCount: recentRuns.length,
      latestStatus: latest?.status ?? 'none',
      latestRunId: latest?.runId,
      latestVerifierPassed: latest?.verifier.passed,
    },
  };
}
