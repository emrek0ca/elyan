
## Overview

Elyan is a local-first, multi-session, multi-channel digital operator platform.

It is not designed as a single chatbot process.  
It is designed as an operational runtime that can:

- receive requests from multiple channels
- resolve the correct user, session, workspace, and execution context
- plan and execute tasks safely
- use local and remote capabilities
- control files, terminal, apps, and other systems through typed runtimes
- maintain auditable memory
- stream progress and status
- recover from failure
- scale through plugins, nodes, and capability modules

The architecture must prioritize:

- correctness
- safety
- observability
- modularity
- low-latency local execution
- extensibility
- premium user experience

---

## Architecture Goals

The system must support the following strategic goals:

### 1. Stable execution
Elyan must perform real work reliably, not just produce plausible text.

### 2. Safe autonomy
Elyan should be capable of acting, but only within explicit policy, approval, and verification constraints.

### 3. Local-first computer control
Files, terminal, clipboard, screenshots, app control, and other device operations must execute locally through a persistent desktop agent.

### 4. Session integrity
Parallel work must not corrupt state. Each session must have explicit execution lanes and queue policies.

### 5. Auditable memory
Memory must be readable, inspectable, and recoverable. Core memory must not be hidden in opaque systems only.

### 6. Extensible capability model
New features must be added as modules, capabilities, plugins, or node types without destabilizing the core.

### 7. Premium operational UX
The user should be able to see active runs, progress, tool calls, approvals, and results clearly.

---

## System Model

At the highest level, Elyan is a distributed runtime composed of:

- a central Gateway / Orchestrator
- one or more channel adapters
- a Session Engine
- a Context Engine
- a Runtime / Planner / Executor
- a Policy Engine
- a Capability Runtime
- a local Desktop Agent
- optional remote Nodes
- a Memory System
- an Observability layer
- a Command Center UI

---

## Top-Level Architecture

```text
User / Channel
    ->
Channel Adapter
    ->
Gateway / Orchestrator
    ->
Session Engine
    ->
Context Engine
    ->
Planner / Runtime
    ->
Policy Engine
    ->
Capability Router
    ->
Desktop Agent / Remote Node / External Integration
    ->
Verification + Logging + Memory Update
    ->
Response / Streaming / UI Update
Core Architectural Principles
Typed boundaries everywhere

All major interactions must be schema-validated.
Use strongly typed event contracts, tool payloads, and capability results.

Side effects are isolated

Filesystem writes, terminal execution, browser actions, app automation, and external mutations must only happen through controlled runtime adapters.

Session state is explicit

Runs, queued events, approvals, failures, memory writes, and checkpoints must all be represented explicitly.

Policy before execution

The LLM may propose, but the system decides whether and how an action is allowed.

Verification after execution

No side-effectful action should be considered successful until verified.

Local execution for local operations

Computer control must happen through a local agent on the user’s machine.

Memory is hybrid

Use file-based readable memory as source of truth, with optional indexing and retrieval layers on top.

Features are modular

Do not keep adding core hacks. New capabilities should enter through registries, adapters, and plugin contracts.

Major Components
1. Channel Adapters

Channel adapters translate external communication channels into Elyan’s internal event protocol.

Examples:

web chat
CLI
desktop UI
mobile app
Telegram
WhatsApp
API
scheduled automation input

Responsibilities:

receive inbound messages or commands
normalize user input
attach channel metadata
forward internal events to Gateway
receive streamed blocks or final responses
preserve channel-specific UX constraints

Channel adapters must not contain core orchestration logic.

2. Gateway / Orchestrator

The Gateway is the central entrypoint of the platform.

Responsibilities:

receive normalized events from all channels
validate protocol contracts
resolve actor identity
resolve session and workspace
create or continue runs
send work into the Session Engine
emit lifecycle events
coordinate streaming and output delivery
route capability requests to the correct runtime or node

The Gateway must be long-lived and state-aware.
It is the backbone of the system.

Gateway Requirements
persistent runtime
structured logs
event lifecycle tracking
run coordination
failure handling
queue integration
channel-agnostic design
3. Protocol Layer

The Protocol Layer defines the typed contracts used across the system.

It should include schemas for:

incoming messages
session resolution
run lifecycle events
planner outputs
tool requests
approvals
verification results
memory write requests
streaming blocks
node registration
health status events

Preferred implementation:

TypeScript
Zod or equivalent runtime schema validation
Protocol Goals
eliminate ambiguous payloads
keep cross-module contracts stable
make logs, replays, and debugging reliable
support plugin and node interoperability
4. Session Engine

The Session Engine protects state integrity.

A session is the stable operational context for a user interaction stream.

A session may represent:

a conversation
a project thread
a workspace thread
a channel thread
a user + task context

Each session should contain:

session_id
actor_id
workspace_id
lane_status
active_run_id
queued_events
session_summary
session_metadata
approval_state
last_checkpoint
Responsibilities
resolve session identity
maintain queue discipline
ensure per-session execution safety
control interrupt / merge / follow-up behavior
support session summaries and checkpointing
Session Lane Model

Each session has a lane.
By default, only one side-effectful run should actively mutate that session at a time.

Supported queue policies:

followup
interrupt
merge
backlog
summarize
Session Safety Rules
do not allow uncontrolled parallel mutation
do not allow two runs to mutate the same operational state without explicit safe concurrency
preserve run ordering where correctness matters
5. Context Engine

The Context Engine is responsible for assembling the correct execution context for a run.

It must combine:

system rules
safety rules
user request
session summary
recent transcript
pinned project memory
active workspace state
retrieved documents
capability state
previous tool results
token and latency budget constraints
Context Prioritization

Context should be assembled in priority order:

system and policy rules
current intent
active session summary
relevant project memory
recent messages
workspace facts
retrieval results
tool outputs
older memory if necessary
Context Rules
prioritize recency and task relevance
compact aggressively when needed
avoid bloating context with decorative conversation
preserve operational facts
maintain deterministic context assembly where possible
Context Lifecycle

The Context Engine should support:

ingest
assemble
compact
summarize
archive
6. Planner / Runtime / Executor

This layer translates intent into action.

It should support multiple execution roles:

planner
executor
validator
summarizer

These can be model roles or internal runtime stages, but the architecture must keep them conceptually separate.

Responsibilities
decide execution mode
generate task plan
request capabilities or tools
handle approval checkpoints
stream progress
retry when appropriate
produce structured results
pass outputs to verification and memory update
Execution Modes

Elyan should support at least these modes:

direct response
inspect-only
read-only tool usage
safe write execution
approval-gated execution
delegated multi-step execution
scheduled / resumed execution
Planning Rule

The planner may suggest steps.
It does not directly mutate the system.

7. Policy Engine

The Policy Engine decides what is allowed, what requires approval, and what is blocked.

It must sit between planning and execution.

Responsibilities
classify action risk
check permissions
enforce allowed roots
protect sensitive paths
determine approval requirements
apply environment-specific rules
prevent unsafe direct execution
Risk Levels

Suggested risk classes:

read_only
write_safe
write_sensitive
destructive
system_critical
Policy Inputs
user role
workspace permissions
action type
file targets
tool category
environment
session state
prior approvals
sensitivity heuristics
Policy Outputs
allow
allow with logging
require preview
require approval
deny
8. Capability Runtime

The Capability Runtime is the execution layer for real operational actions.

A capability is an operational domain.
An action is a specific operation within that domain.

Core capability domains
filesystem
terminal
applications
browser
clipboard
screen
notifications
scheduler
search/index
network
integrations
Capability Contract

Each action must define:

input schema
result schema
risk class
execution adapter
verification strategy
rollback strategy if applicable
timeout behavior
observability hooks
Example actions
filesystem.list
filesystem.read_text
filesystem.write_text
filesystem.patch_text
filesystem.rename
filesystem.move
filesystem.trash
filesystem.restore
terminal.exec
terminal.cancel
terminal.stream_output
applications.open
applications.close
applications.focus
browser.open_url
browser.extract_page
browser.fill_form
browser.download
Capability Design Rule

Do not expose raw system power directly to the LLM.
Expose typed, policy-aware actions.

9. Desktop Agent

The Desktop Agent is the critical local execution process that allows Elyan to control the user’s machine safely and quickly.

It should run as a long-lived process on the local computer.

Responsibilities
connect persistently to Gateway
register available local capabilities
execute filesystem actions
execute terminal actions
control applications
read/write clipboard
capture screenshots
maintain local file index
enforce allowed roots and sensitive path rules
emit health status and progress events
store local audit logs if necessary
Why the Desktop Agent exists

Low-latency computer control should not depend on remote orchestration only.
The Desktop Agent makes local operations fast, permission-aware, and recoverable.

Desktop Agent Requirements
always-on or daemonized process
reconnect logic
heartbeat / health ping
action acknowledgements
typed command protocol
local policy enforcement
execution cancellation support
bounded resource use
Desktop Agent Safety Rules
no raw arbitrary execution without policy
no uncontrolled access outside allowed roots
no secret exposure in logs
destructive operations require stricter handling
local verification required after side effects
10. Remote Nodes

Elyan may later support multiple execution nodes.

Examples:

desktop node
laptop node
VPS node
browser node
mobile node

Each node should register:

node_id
node_type
capabilities
availability
health
permissions
latency profile
Node Routing Goals

The system should be able to route work based on:

locality
required capability
trust level
latency
cost
availability
11. Memory System

Elyan requires a hybrid memory model.

Memory must be:

useful
structured
auditable
readable
recoverable
scoped
Memory Types
Profile Memory

Long-lived user preferences and stable operating rules.

Project Memory

Persistent project-specific facts and architecture decisions.

Episodic Memory

Recent task summaries and session progress.

Run Logs

Execution-level details of what happened.

Suggested Storage Layout
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
Memory Write Flow
run completes or reaches a checkpoint
candidate memory items are extracted
candidates are scored
sensitive data is filtered or downgraded
accepted memory is written to the appropriate store
memory write event is logged
retrieval indexes are updated if used
Memory Design Rule

Memory must not become a garbage dump.
Only persistent and useful facts should be promoted.

12. Verification Layer

Execution is not complete until verification succeeds.

Verification responsibilities
confirm filesystem changes occurred correctly
confirm file content was written as expected
confirm terminal exit status and expected signals
confirm app state transitions where necessary
confirm output artifacts exist
detect partial failure
Verification outputs
passed
failed
partial
inconclusive
Verification Rule

Never assume side-effect success based only on tool invocation.

13. Observability Layer

Observability is mandatory.

The system must make it possible to answer:

what happened
why it happened
which session it belonged to
which plan step triggered it
which capability executed it
whether policy approved it
whether verification passed
whether memory was updated
whether rollback is possible
Observability data
event logs
run logs
tool/capability logs
errors
retries
approval records
rollback records
node health
performance metrics
cost metrics
Key Metrics

Track at minimum:

task success rate
capability success rate
median latency
queue wait time
approval frequency
retry rate
rollback rate
session recovery rate
memory pollution rate
token cost per successful task
14. Command Center UI

The Command Center is the operator-facing control surface.

It should expose:

active sessions
active runs
pending approvals
progress blocks
tool calls
result previews
memory timeline
node health
cost insights
error history
UI Rule

The UI should visualize the operational state of the system, not hide it.

Execution Flow
Standard Request Flow
1. Channel receives user input
2. Channel Adapter normalizes event
3. Gateway validates event
4. Session Engine resolves session + lane
5. Context Engine assembles context
6. Planner decides execution mode
7. Policy Engine evaluates proposed actions
8. Capability Router selects Desktop Agent / Node / Integration
9. Action executes
10. Verification runs
11. Observability events are recorded
12. Memory write candidates are processed
13. Response streams back to channel/UI
File Operation Flow
User request
  ->
Planner proposes filesystem action
  ->
Policy checks:
  - allowed root
  - sensitive path
  - action risk
  - dry-run requirement
  - approval requirement
  ->
Desktop Agent executes typed filesystem action
  ->
Verification checks result
  ->
Audit log written
  ->
Optional memory summary update
  ->
User receives outcome
Terminal Execution Flow
User request
  ->
Planner proposes terminal action
  ->
Policy checks:
  - working directory
  - command class
  - risk level
  - approval need
  ->
Desktop Agent executes terminal adapter
  ->
Capture stdout / stderr / exit code
  ->
Verification evaluates result
  ->
Logs + response + possible summary update
Streaming Model

Elyan should support progressive visibility into execution.

Streaming may include:

thinking-free status blocks
planner status
approval requests
tool execution progress
partial results
final structured response

Channel-specific delivery can vary:

rich token/block streaming for web/desktop
compact block streaming for messaging apps
status-oriented streaming for automation contexts
Storage Architecture
Persistent stores

Suggested core stores:

relational DB for structured runtime state
local SQLite for desktop indexing and agent state
filesystem for readable memory and logs
object storage if artifacts become large
optional search index for retrieval
Recommended responsibilities
Relational database
sessions
runs
approvals
node registry
action metadata
metrics summaries
Filesystem-based stores
memory markdown
daily summaries
audit JSON logs
snapshots
artifacts
SQLite on local desktop agent
file index
recent action cache
local capability registry
local journal
Security and Safety Model
Trust boundaries

The architecture must recognize these trust boundaries:

user input
model-generated plans
policy-approved actions
local system capabilities
external integrations
stored memory
secrets and credentials
Security rules
never trust raw model output as executable truth
isolate secrets from logs and prompts
require stricter rules for credential-bearing files
use least privilege where possible
protect sensitive paths by default
support manual override only through explicit policy paths
Failure Handling

Failure is expected.
The system must degrade gracefully.

Failure classes
schema failure
session resolution failure
context assembly failure
planner failure
policy denial
capability execution failure
verification failure
node unavailable
timeout
rollback failure
memory write failure
Failure design goals
clear classification
visible status
no silent corruption
partial recovery where possible
retry only when appropriate
safe abort when uncertain
Rollback Strategy

For reversible actions, Elyan should support rollback metadata.

Examples:

file rename -> restore old name
file move -> restore original path
file patch -> restore previous content snapshot
trash -> restore from trash if supported

Rollback is not guaranteed for every action, but the architecture should prefer reversible flows when possible.

Deployment Model
Local-first baseline

The first production-capable architecture should support:

local Desktop Agent on macOS
central Gateway service
admin / command center UI
file and terminal capabilities
memory system
policy and approval system
Later distributed model

The architecture should later support:

multiple nodes
multi-device coordination
remote task routing
background scheduled tasks
organization mode
plugin marketplace or capability packs
Reference Repository Structure
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

data/
  logs/
  journal/
  snapshots/
  index/
Suggested Technology Baseline

This is a practical baseline, not a strict requirement.

Core services
Node.js 22+
TypeScript
Fastify
WebSocket
Zod
Pino
Desktop agent
Node.js + TypeScript for v1
SQLite for local indexing
file watchers for index freshness
controlled terminal execution adapter
macOS app integration layer
Optional v2 performance upgrades
Rust sidecar for indexing or native integrations
message bus if distributed scale demands it
stronger retrieval stack if memory/search grows
Development Priorities
Phase 1: Core runtime
protocol
gateway
session engine
structured logs
run lifecycle
Phase 2: Safe local execution
desktop agent
filesystem capability
terminal capability
policy engine
verification
rollback basics
Phase 3: Memory and context
project memory
episodic summaries
retrieval
compaction
Phase 4: Extensibility
plugin kit
node registry
capability registry
app/browser layers
Phase 5: Premium UX
command center
approvals UI
run inspector
cost and health views
Architectural Rules for Contributors

Any contributor or coding agent working on Elyan must follow these rules:

Do
preserve layer boundaries
keep contracts typed
isolate side effects
log important actions
verify results
prefer local-first execution for machine control
build minimal strong abstractions
keep memory auditable
Do not
bypass policy
write directly to sensitive files without safeguards
merge unrelated concerns into a single module
let UI own business logic
allow uncontrolled parallel session mutation
trust raw model output without runtime checks
Final Architecture Directive

Elyan must be built as operational infrastructure.

That means:

explicit state
explicit execution
explicit policy
explicit verification
explicit memory
explicit observability

The architecture should always move toward:

stronger session integrity
safer autonomy
faster local execution
cleaner modularity
more reliable real-world task handling
better operator visibility
easier long-term extensibility