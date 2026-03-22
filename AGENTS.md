## Elyan Overview

Elyan is not a simple chatbot.  
Elyan is a local-first, multi-session, multi-channel, tool-using digital operator.

Its job is not only to answer messages, but to:

- understand user intent
- resolve the correct session and workspace
- assemble context safely
- choose the right execution path
- use tools and capabilities
- operate on local and remote systems
- update memory
- stream progress
- recover from errors
- remain stable as new features are added

Elyan must behave like an operator runtime, not a prompt toy.

---

## Product Vision

Elyan should become a reliable digital operator that can:

- manage files and folders
- edit, create, move, rename, and trash files safely
- execute terminal tasks with verification
- coordinate desktop, browser, and remote nodes
- work across sessions without context corruption
- remember projects, user preferences, and recent work
- support approval-first autonomy
- remain modular, observable, and extensible

The core value of Elyan is: **stable execution with real operational capability**.

---

## North Star

When building Elyan, always optimize for:

1. correctness
2. safety
3. observability
4. extensibility
5. low-friction execution
6. clean architecture
7. local-first performance
8. premium user experience

Never optimize for “demo magic” at the cost of stability.

---

## Non-Goals

Do not turn Elyan into:

- a giant prompt file
- a monolithic chatbot app
- a random collection of scripts
- a fragile UI-automation bot
- an agent that directly executes raw model output without policy checks
- a system that mutates files without previews, logs, or rollback

---

## Core Principles

### 1. LLM decides, runtime executes
The model may propose a plan, but the runtime is responsible for what actually happens.

### 2. Core is stable, features are modular
Do not inject new features directly into the core runtime.  
New capabilities must be added through clear modules, registries, or plugins.

### 3. Every session has a lane
A session must not have uncontrolled parallel execution.  
Use per-session serialization or explicit queue policies.

### 4. All side effects must be explicit
Filesystem writes, terminal commands, browser actions, app control, and network changes are side effects.  
They must go through typed actions, policy checks, logging, and verification.

### 5. Preview before destructive change
Any risky or destructive operation must support dry-run, preview, or approval before execution.

### 6. Memory must be auditable
Memory should be readable, structured, and recoverable.  
Do not hide core memory entirely inside opaque vector-only layers.

### 7. Local-first for computer control
Desktop control, filesystem operations, terminal execution, and UI-level capabilities should run on the local machine through a persistent desktop agent.

### 8. Everything important must be observable
If Elyan performs an action, we must be able to answer:
- what happened
- why it happened
- which session triggered it
- which tool executed it
- whether it succeeded
- whether it can be rolled back

---

## High-Level Architecture

Elyan should be developed as a layered system.

### Layer 1: Gateway / Orchestrator
Responsible for:
- receiving events from all channels
- validating incoming payloads
- resolving actor, workspace, and session
- queueing work
- starting runs
- tracking lifecycle events

### Layer 2: Protocol Layer
Responsible for:
- typed schemas
- event definitions
- action payload contracts
- tool result validation
- compatibility across components

Use typed contracts everywhere.  
Preferred stack: TypeScript + Zod or equivalent schema validation.

### Layer 3: Session Engine
Responsible for:
- session resolution
- lane locking
- queue policies
- run state
- interruption rules
- follow-up handling

### Layer 4: Context Engine
Responsible for:
- system rules
- workspace state
- recent transcript
- pinned memory
- project memory
- retrieval results
- tool state
- compaction and token budgeting

### Layer 5: Runtime / Planner / Executor
Responsible for:
- planning
- step execution
- tool routing
- approval checkpoints
- retries
- failure recovery
- structured output production

### Layer 6: Capability Runtime
Responsible for:
- filesystem operations
- terminal commands
- application control
- browser control
- clipboard access
- screenshots
- node-specific actions

### Layer 7: Memory and Persistence
Responsible for:
- profile memory
- project memory
- episodic memory
- run logs
- daily summaries
- audit records

### Layer 8: UI / Command Center
Responsible for:
- active runs
- pending approvals
- live progress
- tool history
- memory timeline
- node health
- cost and usage visibility

---

## Execution Model

Elyan must follow this mental model for every user request:

1. receive input
2. validate input
3. normalize input
4. resolve session
5. resolve workspace
6. assemble context
7. decide execution mode
8. run plan
9. call tools if needed
10. verify results
11. update memory
12. log everything important
13. respond with status and outcome

Never skip validation, policy, verification, or logging for side-effectful work.

---

## Session Model

A session represents a stable operational context.

A session may correspond to:
- a conversation
- a project
- a workspace
- a task thread
- a user + channel pair

Each session must have:

- `session_id`
- `actor_id`
- `workspace_id`
- `lane_state`
- `active_run_id`
- `queued_events`
- `last_context_summary`
- `session_metadata`

### Rules

- Only one side-effectful run should actively mutate a session state at a time unless there is explicit safe concurrency.
- New events must enter a queue.
- Session queues must support policy-based handling.

### Queue Policies

Support these queue policies:

- `followup`: run after current task
- `interrupt`: only for high-priority work
- `merge`: merge into active plan if compatible
- `backlog`: store for later processing
- `summarize`: compress multiple pending items into one summary item

---

## Context Assembly Rules

When building context for a run, include only what is useful and current.

Context priority order:

1. system and safety rules
2. current user intent
3. session summary
4. relevant project memory
5. recent transcript
6. active workspace state
7. retrieved documents
8. tool state and previous outputs
9. optional older memory

### Requirements

- Always prefer current and task-relevant context.
- Compact aggressively when needed.
- Never bloat context with unrelated history.
- Preserve operational facts over decorative chat history.

---

## Memory Model

Elyan should use a hybrid memory model.

### Memory Types

#### 1. Profile Memory
Long-lived user preferences and stable behavior rules.

Examples:
- preferred coding style
- preferred architecture patterns
- product priorities
- recurring workflows

#### 2. Project Memory
Persistent project-specific facts.

Examples:
- Elyan architecture decisions
- roadmap decisions
- repo structure
- active milestones
- capability plans

#### 3. Episodic Memory
Session and recent work summaries.

Examples:
- what was implemented today
- which bug was investigated
- which files were changed
- next pending tasks

#### 4. Run Logs
Execution-level audit history.

Examples:
- which tool was called
- what it attempted
- what it changed
- what failed
- rollback details

### Storage Rules

Memory must be:
- structured
- readable
- easy to audit
- not solely dependent on vector storage
- easy to update safely

### Suggested Layout

```text
memory/
  profile.md
  projects/
    elyan/
      MEMORY.md
      DECISIONS.md
      ROADMAP.md
  daily/
    YYYY-MM-DD.md
  runs/
    <session-id>/
      <run-id>.json
Capability Model

Do not think in terms of random tools only.
Think in terms of capabilities.

A capability is an operational domain.
An action is a specific operation inside that domain.

Core Capabilities
filesystem
terminal
applications
browser
clipboard
screen
notifications
search/index
network
scheduler
Example Actions
filesystem.list
filesystem.read_text
filesystem.write_text
filesystem.patch_text
filesystem.move
filesystem.rename
filesystem.trash
filesystem.restore
terminal.exec
terminal.stream
terminal.cancel
applications.open
applications.close
applications.focus
browser.open_url
browser.extract_page
browser.fill_form
browser.download

Each action must define:

input schema
risk level
approval rules
execution adapter
result schema
verification method
rollback strategy if applicable
Computer Control Architecture

Elyan must use a desktop agent for local machine operations.

Rule

The LLM must not directly control the operating system.

Correct model

User request
-> Orchestrator
-> Policy engine
-> Desktop agent
-> Capability adapter
-> Verification
-> Logging
-> Response

Desktop Agent Responsibilities
persistent connection to gateway
execute local filesystem actions
execute terminal commands
access local applications
access clipboard
capture screenshots
maintain fast local file index
enforce allowed roots and sensitive path restrictions
provide low-latency local execution
Desktop Agent Requirements
always-on process or daemon
typed protocol
reconnect logic
action acknowledgements
progress events
local audit logging
local capability registry
health heartbeat
Filesystem Safety Rules

Elyan must treat filesystem changes as high-importance operations.

Required behavior
Allowed Roots

Only operate inside allowed roots unless explicitly elevated.

Atomic Writes

Never risk partial file corruption.
Use temp-write + verify + rename patterns where appropriate.

Safe Delete

Default delete should mean:

move to trash
log operation
support restore if possible
Dry Run

Bulk rename, delete, move, and patch operations should support dry-run.

Verification

After a write or move:

verify path exists
verify content if relevant
verify target is correct
verify count of affected files
Rollback

For any reversible operation, preserve rollback metadata.

Sensitive Path Protection

Protect paths such as:

.env
private keys
SSH folders
cloud credentials
wallet files
shell profile files
system configuration files
Terminal Execution Rules

Terminal execution is powerful and dangerous.

Requirements
execute through a controlled adapter
validate allowed working directory
sanitize environment exposure
capture stdout, stderr, exit code
support cancellation
classify risk before execution
require approval for destructive commands
Never
run raw arbitrary shell from model output without filtering
expose secrets in logs
assume success without checking exit code and output
Approval and Safety Model

Elyan must support approval-first autonomy.

Risk Levels
read_only
write_safe
write_sensitive
destructive
system_critical
Approval Guidance
Auto-allow examples
read file
list directory
inspect process
search workspace
open a known document
Usually require approval
overwrite important files
bulk rename
bulk delete
terminal commands with system impact
package uninstall
secret-related file access
system config changes
Always high scrutiny
anything touching keys, credentials, wallet files, SSH, environment files, or deployment secrets
Plugin Model

Elyan must be extensible.

A plugin may add:

a new capability
a new tool adapter
a new channel integration
a new model provider
a new node type
a new UI module
Plugin Rules

Plugins must not bypass:

protocol typing
policy checks
logging
verification
lifecycle integration
Plugin Contract

Each plugin should declare:

plugin name
version
capabilities
actions
required permissions
runtime dependencies
health checks
configuration schema
Model Usage Rules

Use models intentionally.

Suggested role separation
planner model: small and fast when possible
executor model: stronger when precision is needed
validator model: deterministic checks when possible
summarizer model: cheap and compact
Rules
do not use the strongest model for everything
keep token cost under control
use retrieval and runtime state before asking the model to infer
prefer deterministic code paths over model creativity for operational actions
Observability Requirements

Every meaningful run should be inspectable.

Minimum observability
event logs
run lifecycle logs
tool call logs
errors
retries
approval waits
rollback records
memory write events
performance metrics
Important metrics

Track at least:

task success rate
tool success rate
average latency
queue delay
approval rate
rollback frequency
retry frequency
token cost per successful task
memory pollution rate
session recovery rate
Code Standards
General
prefer TypeScript for core system code
keep modules small and composable
favor pure functions where possible
separate orchestration from side effects
validate all external input
avoid hidden shared mutable state
Required practices
strong typing
schema validation
structured logs
explicit errors
predictable naming
minimal coupling
Avoid
giant files
magical helper layers with unclear ownership
silent failures
direct filesystem mutation from random app code
business logic inside UI components
undocumented side effects
Repo Structure Guidance

Suggested monorepo structure:

apps/
  gateway/
  desktop-agent/
  admin-web/
  mobile-client/
  cli/

packages/
  protocol/
  session-engine/
  context-engine/
  runtime/
  planner/
  policy-engine/
  memory/
  observability/
  capability-filesystem/
  capability-terminal/
  capability-applications/
  capability-browser/
  capability-screen/
  capability-search/
  plugin-kit/
  shared-types/

plugins/
  telegram/
  whatsapp/
  gmail/
  calendar/
  browser-playwright/
  desktop-macos/

memory/
  profile.md
  projects/
  daily/
  runs/
File Editing Rules for Agents

When changing code:

understand the relevant layer first
avoid cross-layer hacks
keep core contracts stable
preserve backward compatibility where reasonable
update schemas when interfaces change
update docs when architecture changes
preserve auditability
never weaken safety without explicit reason

If a change touches:

protocol
session logic
policy engine
filesystem execution
terminal execution
memory writing

then treat it as a sensitive architectural change.

Development Workflow

When implementing a feature, follow this order:

define the capability or behavior clearly
define the schema and contracts
define safety and approval rules
implement the runtime behavior
add verification
add observability
update memory/docs if architecture changed
expose in UI only after the runtime is stable
Preferred sequence

Do not build UI-first for runtime-heavy features.
Build core runtime first, then UI.

Definition of Done

A feature is not done because it “works once”.

A feature is done only if:

behavior is typed
failure cases are handled
logs exist
output can be verified
destructive behavior is protected
session interaction is considered
docs are updated if architecture changed
the feature fits the existing system instead of bypassing it
Quality Gates

Before merging or accepting a change, check:

Does this break session isolation?
Does this bypass policy?
Does this add side effects without logs?
Does this mutate files unsafely?
Does this make memory less auditable?
Does this increase coupling unnecessarily?
Can the action be verified?
Can failure be recovered?

If the answer is problematic, redesign before merging.

First-Class Priorities

When in doubt, prioritize work in this order:

Priority 1: Stable Core
protocol contracts
gateway lifecycle
session engine
queue model
run lifecycle
observability
Priority 2: Safe Computer Control
filesystem capability
terminal capability
local desktop agent
allowed roots
safe delete
rollback
verification
Priority 3: Context and Memory
project memory
session summaries
retrieval
memory write scoring
context compaction
Priority 4: Extensibility
plugin system
node system
capability registry
model routing
Priority 5: UX
command center
approvals UI
live progress
memory timeline
premium operator workflow
Immediate Build Priorities

If starting from scratch or continuing incomplete work, build in this order:

Phase 1
protocol package
event schemas
gateway
session engine
run state model
structured logging
Phase 2
desktop agent
filesystem capability
terminal capability
policy engine
verification and rollback base
Phase 3
memory system
retrieval
session summaries
project memory
Phase 4
plugin kit
browser/app capabilities
node registry
remote orchestration
Phase 5
admin UI
approvals
live run inspection
command center
Required Event Types

The system should be designed around explicit events such as:

MessageReceived
SessionResolved
WorkspaceResolved
RunQueued
RunStarted
PlanCreated
ToolRequested
ToolApproved
ToolRejected
ToolStarted
ToolSucceeded
ToolFailed
VerificationPassed
VerificationFailed
MemoryWriteRequested
MemoryWritten
RunCompleted
RunFailed
RunCancelled

Do not hide important lifecycle transitions.

Planning Guidance for Agents

When asked to implement something, first decide which category it belongs to:

protocol
session
context
runtime
capability
policy
memory
plugin
UI
observability

Then work within that boundary.

If a request seems simple but affects core runtime, treat it as an architecture change, not a small patch.

Behavior Expectations for All Coding Agents

When working on Elyan, you must:

understand the full architecture before making core changes
preserve stability over speed
build minimal but strong implementations
avoid unnecessary abstraction until the layer is clear
keep code clean, typed, and modular
prefer robust infrastructure over flashy shortcuts
write changes that future agents can understand quickly

You must not:

inject random dependencies without strong justification
create silent destructive behavior
mix UI logic with execution logic
bypass logging or policy layers
write code that “only works on the happy path”
weaken system safety to make demos easier
Final Directive

Elyan is a serious operator system.
Build it like infrastructure, not like a toy.

Every change should move Elyan closer to:

reliable execution
safe autonomy
modular extensibility
local-first power
premium operator UX
auditable memory
production-grade control over real tasks

If you are uncertain, choose the path that is:

simpler
safer
more observable
easier to extend later
less likely to corrupt state