import { randomUUID } from 'crypto';
import { generateText } from 'ai';
import { registry } from '@/core/providers';
import { citationEngine } from '@/core/search';
import { runSelectiveWebRetrieval } from '@/core/retrieval';
import { filterContextBlocks } from '@/core/retrieval/context';
import { resolveBrainPreferredModelId } from '@/core/ml/model-routing';
import { buildTeamPlan } from './planner';
import { synthesizeTeamRun } from './synthesizer';
import { teamRunStore, type TeamRunStore } from './store';
import type {
  TeamAgent,
  TeamAgentExecutionInput,
  TeamAgentExecutor,
  TeamArtifact,
  TeamMessage,
  TeamRunInput,
  TeamRunResult,
  TeamTask,
  TeamVerification,
} from './types';

type TeamModelResolver = (input: {
  requestedModelId?: string;
  routingMode: TeamRunResult['teamPlan']['modelRoutingMode'];
  taskIntent: TeamRunInput['sourcePlan']['taskIntent'];
  reasoningDepth: TeamRunInput['sourcePlan']['reasoningDepth'];
}) => Promise<{ modelId: string; providerId: string }>;

function artifactKindForTask(task: TeamTask): TeamArtifact['kind'] {
  if (task.kind === 'analysis') {
    return 'note';
  }

  return task.kind;
}

function isVerificationContentStructured(content: string) {
  return /^(pass|fail)\b/i.test(content.trim());
}

function summarizeVerificationContent(content: string) {
  return content
    .trim()
    .replace(/^(pass|fail)\b[:\s-]*/i, '')
    .trim();
}

function normalizeVerificationResult(args: {
  content?: string;
  artifactId?: string;
  error?: unknown;
}): TeamVerification {
  const rawContent = args.content?.trim() ?? '';

  if (args.error) {
    const errorMessage = args.error instanceof Error ? args.error.message : 'unknown verification failure';
    return {
      passed: false,
      summary: errorMessage || 'Verification task failed.',
      state: 'error',
      artifactId: args.artifactId,
      rawContent: rawContent || undefined,
    };
  }

  if (!rawContent) {
    return {
      passed: false,
      summary: 'Verification task did not produce a structured result.',
      state: 'missing_artifact',
      artifactId: args.artifactId,
    };
  }

  if (!isVerificationContentStructured(rawContent)) {
    return {
      passed: false,
      summary: 'Verification output was not structured.',
      state: 'unstructured',
      artifactId: args.artifactId,
      rawContent,
    };
  }

  const passed = /^pass\b/i.test(rawContent);
  const summary = summarizeVerificationContent(rawContent) || (passed ? 'Verification passed.' : 'Verification failed.');

  return {
    passed,
    summary,
    state: passed ? 'passed' : 'failed',
    artifactId: args.artifactId,
    rawContent,
  };
}

function buildVerificationArtifact(args: {
  runId: string;
  task: TeamTask;
  agent: TeamAgent;
  content?: string;
  error?: unknown;
}) {
  const createdAt = new Date().toISOString();
  const artifactId = randomUUID();
  const verification = normalizeVerificationResult({
    content: args.content,
    artifactId,
    error: args.error,
  });

  const content = verification.passed
    ? `PASS ${verification.summary}`
    : `FAIL ${verification.summary}`;

  const artifact: TeamArtifact = {
    id: artifactId,
    runId: args.runId,
    taskId: args.task.id,
    agentId: args.agent.id,
    kind: 'verification',
    title: args.task.title,
    content,
    metadata: {
      role: args.agent.role,
      verification,
    },
    createdAt,
  };

  return { artifact, verification, createdAt };
}

function getReadyTasks(tasks: TeamTask[], completed: Set<string>, running: Set<string>, failed: Set<string>) {
  return tasks.filter((task) => {
    if (completed.has(task.id) || running.has(task.id) || failed.has(task.id)) {
      return false;
    }

    return task.dependsOn.every((dependency) => completed.has(dependency));
  });
}

function buildTaskPrompt(input: TeamAgentExecutionInput) {
  const previousArtifacts = input.artifacts
    .map((artifact) => `Artifact ${artifact.taskId} / ${artifact.title}:\n${artifact.content}`)
    .join('\n\n');
  const messages = input.messages
    .map((message) => `${message.type} from ${message.fromAgentId}: ${message.content}`)
    .join('\n');
  const context = filterContextBlocks(input.contextBlocks, {
    maxTokens: 1_200,
    maxBlocks: 6,
    minScore: 0.15,
  }).join('\n\n');

  return [
    `User request:\n${input.query}`,
    `Current task:\n${input.task.title}\n${input.task.summary}`,
    `Team policy:\n${input.teamPlan.policy.reasons.join('\n')}`,
    context ? `Memory/context:\n${context}` : '',
    input.sourceContext ? `Retrieved context:\n${input.sourceContext}` : '',
    previousArtifacts ? `Previous artifacts:\n${previousArtifacts}` : '',
    messages ? `Team messages:\n${messages}` : '',
    input.task.kind === 'verification'
      ? 'Return PASS or FAIL first, followed by one concise reason. Fail if claims are unsupported, policy was bypassed, or required work is missing.'
      : 'Return the artifact content only. Be concrete, concise, and avoid unsupported success claims.',
  ].filter(Boolean).join('\n\n---\n\n');
}

async function defaultAgentExecutor(input: TeamAgentExecutionInput): Promise<string> {
  const { model } = registry.resolveModel(input.modelId);
  const result = await generateText({
    model,
    system: input.agent.systemPrompt,
    prompt: buildTaskPrompt(input),
    temperature: input.task.kind === 'verification' ? 0 : 0.15,
    maxOutputTokens: input.maxOutputTokens,
    abortSignal: input.abortSignal,
  });

  return result.text.trim();
}

export class TeamRunner {
  constructor(
    private readonly store: TeamRunStore = teamRunStore,
    private readonly executeAgent: TeamAgentExecutor = defaultAgentExecutor,
    private readonly resolveModel: TeamModelResolver = async (selection) => {
      const brainPreferredModelId = await resolveBrainPreferredModelId();
      const modelId = await registry.resolvePreferredModelId({
        preferredModelId: brainPreferredModelId ?? selection.requestedModelId,
        routingMode: selection.routingMode,
        taskIntent: selection.taskIntent,
        reasoningDepth: selection.reasoningDepth,
      });
      const provider = registry.resolveModel(modelId).provider;
      return {
        modelId,
        providerId: provider.id,
      };
    }
  ) {}

  async run(input: TeamRunInput): Promise<TeamRunResult> {
    const teamPlan = buildTeamPlan(input);
    const startedAt = teamPlan.createdAt;
    const selectedModel = await this.resolveModel({
      requestedModelId: input.requestedModelId,
      routingMode: teamPlan.modelRoutingMode,
      taskIntent: input.sourcePlan.taskIntent,
      reasoningDepth: input.sourcePlan.reasoningDepth,
    });
    const selectedModelId = selectedModel.modelId;
    const artifacts: TeamArtifact[] = [];
    const messages: TeamMessage[] = [];
    const completed = new Set<string>();
    const running = new Set<string>();
    const failed = new Set<string>();
    const sources = await this.collectSources(input);
    const sourceContext = sources.length > 0 ? citationEngine.buildContext(sources) : '';
    const deadlineAt = Date.now() + (input.maxExecutionMs ?? 90_000);
    const assertActive = () => {
      if (input.abortSignal?.aborted) {
        throw input.abortSignal.reason instanceof Error ? input.abortSignal.reason : new Error('Team run aborted by request guard.');
      }

      if (Date.now() > deadlineAt) {
        throw new Error('Team run exceeded the request execution deadline.');
      }
    };

    await this.store.createRun(teamPlan);
    await this.store.appendEvent({
      id: randomUUID(),
      runId: teamPlan.runId,
      type: 'run_started',
      createdAt: startedAt,
      data: {
        modelId: selectedModelId,
        provider: selectedModel.providerId,
      },
    });

    while (completed.size + failed.size < teamPlan.tasks.length) {
      assertActive();
      const ready = getReadyTasks(teamPlan.tasks, completed, running, failed);

      if (ready.length === 0) {
        throw new Error('Team run stalled because no task dependencies can make progress.');
      }

      const batch = ready.slice(0, teamPlan.maxConcurrentAgents);
      await Promise.all(
        batch.map((task) =>
          this.runTask({
            task,
            agent: this.agentForTask(teamPlan.agents, task),
            input,
            teamPlan,
            modelId: selectedModelId,
            modelProvider: selectedModel.providerId,
            sourceContext,
            artifacts,
            messages,
            completed,
            running,
            failed,
          })
        )
      );
      assertActive();

      if (failed.size > 0) {
        break;
      }
    }

    const synthesized = synthesizeTeamRun({
      teamPlan,
      artifacts,
      messages,
      sources,
      modelId: selectedModelId,
      modelProvider: selectedModel.providerId,
      startedAt,
    });

    await this.store.writeArtifacts(teamPlan.runId, artifacts);
    await this.store.writeSummary(synthesized.summary);
    await this.store.appendEvent({
      id: randomUUID(),
      runId: teamPlan.runId,
      type: synthesized.summary.status === 'completed' ? 'run_completed' : 'run_failed',
      createdAt: synthesized.summary.finishedAt,
      data: {
        verifierPassed: synthesized.summary.verifier.passed,
      },
    });

    return {
      text: synthesized.text,
      sources,
      teamPlan,
      summary: synthesized.summary,
      artifacts,
      messages,
      modelId: selectedModelId,
      modelProvider: selectedModel.providerId,
    };
  }

  private async collectSources(input: TeamRunInput) {
    const retrieval = await runSelectiveWebRetrieval({
      query: input.query,
      plan: {
        routingMode: input.sourcePlan.routingMode,
        reasoningDepth: input.sourcePlan.reasoningDepth,
        taskIntent: input.sourcePlan.taskIntent,
        executionPolicy: {
          shouldRetrieve: input.searchEnabled && input.sourcePlan.retrieval.rounds > 0,
        },
        retrieval: input.sourcePlan.retrieval,
      },
      searchEnabled: input.searchEnabled,
    });

    return retrieval.sources;
  }

  private agentForTask(agents: TeamAgent[], task: TeamTask) {
    const agent = agents.find((candidate) => candidate.role === task.assignedRole);
    if (!agent) {
      throw new Error(`No team agent is registered for role ${task.assignedRole}.`);
    }

    return agent;
  }

  private async runTask(args: {
    task: TeamTask;
    agent: TeamAgent;
    input: TeamRunInput;
    teamPlan: ReturnType<typeof buildTeamPlan>;
    modelId: string;
    modelProvider: string;
    sourceContext: string;
    artifacts: TeamArtifact[];
    messages: TeamMessage[];
    completed: Set<string>;
    running: Set<string>;
    failed: Set<string>;
  }) {
    const { task, agent, input, teamPlan, artifacts, messages, completed, running, failed } = args;
    running.add(task.id);
    await this.store.appendEvent({
      id: randomUUID(),
      runId: teamPlan.runId,
      type: 'task_started',
      createdAt: new Date().toISOString(),
      taskId: task.id,
      agentId: agent.id,
      data: {},
    });

    try {
      if (task.requiresConfirmation) {
        throw new Error(`Task ${task.id} requires confirmation before execution.`);
      }

      const content = await this.executeAgent({
        agent,
        task,
        teamPlan,
        query: input.query,
        modelId: args.modelId,
        modelProvider: args.modelProvider,
        sourceContext: args.sourceContext,
        contextBlocks: input.contextAugments ?? [],
        artifacts: [...artifacts],
        messages: [...messages],
        abortSignal: input.abortSignal,
        maxOutputTokens: input.maxOutputTokens,
      });
      const createdAt = new Date().toISOString();
      const verificationArtifact =
        task.kind === 'verification'
          ? buildVerificationArtifact({
              runId: teamPlan.runId,
              task,
              agent,
              content,
            })
          : null;
      const artifact =
        verificationArtifact?.artifact ??
        {
          id: randomUUID(),
          runId: teamPlan.runId,
          taskId: task.id,
          agentId: agent.id,
          kind: artifactKindForTask(task),
          title: task.title,
          content,
          metadata: {
            role: agent.role,
          },
          createdAt,
        };
      const verification = verificationArtifact?.verification ?? null;
      const message: TeamMessage = {
        id: randomUUID(),
        runId: teamPlan.runId,
        fromAgentId: agent.id,
        taskId: task.id,
        type: task.kind === 'verification' ? 'verification' : 'task_result',
        content:
          task.kind === 'verification' && verification
            ? `${verification.passed ? 'PASS' : 'FAIL'} ${verification.summary}`
            : content,
        createdAt,
      };

      artifacts.push(artifact);
      messages.push(message);
      completed.add(task.id);
      await this.store.appendEvent({
        id: randomUUID(),
        runId: teamPlan.runId,
        type: 'artifact_recorded',
        createdAt,
        taskId: task.id,
        agentId: agent.id,
        artifact,
        data: {},
      });
      await this.store.appendEvent({
        id: randomUUID(),
        runId: teamPlan.runId,
        type: 'message_recorded',
        createdAt,
        taskId: task.id,
        agentId: agent.id,
        message,
        data: {},
      });
      await this.store.appendEvent({
        id: randomUUID(),
        runId: teamPlan.runId,
        type: task.kind === 'verification' ? 'verification_completed' : 'task_completed',
        createdAt,
        taskId: task.id,
        agentId: agent.id,
        data: task.kind === 'verification' && verification
          ? {
              verification,
            }
          : {},
      });
    } catch (error) {
      failed.add(task.id);
      if (task.kind === 'verification') {
        const fallback = buildVerificationArtifact({
          runId: teamPlan.runId,
          task,
          agent,
          error,
        });
        artifacts.push(fallback.artifact);
        const message: TeamMessage = {
          id: randomUUID(),
          runId: teamPlan.runId,
          fromAgentId: agent.id,
          taskId: task.id,
          type: 'verification',
          content: `FAIL ${fallback.verification.summary}`,
          createdAt: fallback.createdAt,
        };
        messages.push(message);
        await this.store.appendEvent({
          id: randomUUID(),
          runId: teamPlan.runId,
          type: 'artifact_recorded',
          createdAt: fallback.createdAt,
          taskId: task.id,
          agentId: agent.id,
          artifact: fallback.artifact,
          data: {
            verification: fallback.verification,
          },
        });
        await this.store.appendEvent({
          id: randomUUID(),
          runId: teamPlan.runId,
          type: 'message_recorded',
          createdAt: fallback.createdAt,
          taskId: task.id,
          agentId: agent.id,
          message,
          data: {
            verification: fallback.verification,
          },
        });
        await this.store.appendEvent({
          id: randomUUID(),
          runId: teamPlan.runId,
          type: 'verification_completed',
          createdAt: fallback.createdAt,
          taskId: task.id,
          agentId: agent.id,
          data: {
            verification: fallback.verification,
          },
        });
      }
      await this.store.appendEvent({
        id: randomUUID(),
        runId: teamPlan.runId,
        type: 'task_failed',
        createdAt: new Date().toISOString(),
        taskId: task.id,
        agentId: agent.id,
        data: {
          error: error instanceof Error ? error.message : 'unknown task failure',
        },
      });
    } finally {
      running.delete(task.id);
    }
  }
}

export const teamRunner = new TeamRunner();
