# Elyan Future Expansion Rules

Elyan is aggressively locked to its V1 behavior (Search, Retrieve, Formatted Citations). Future scaling (v1.1+) MUST adhere to these strict abstraction rules to prevent architectural bloat.

## 1. Document Q&A & RAG
If RAG is introduced, it must **never** be injected directly into `src/core/agents/answer-engine.ts`.
- **Extension Point:** Create a dedicated `document-engine.ts`.
- **Interface:** The document engine must share the identical streaming contract `toUIMessageStreamResponse()` to avoid fragmenting the API.
- **Data Safety:** Never assume implicit file system reads. Documents must be explicitly fed via users through proper bounded channels.

## 2. Dynamic Component Widgets
Widgets (e.g. Weather, Stocks, System Control) were purged from V1. If reintroduced:
- **Registry Binding:** Tool execution must occur via the official `ai` server-side registry mapping.
- **Non-Polluting Loading:** Tools must yield immediately to textual responses; UI blocks tracking tools must be self-contained lazy-loaded components within `ChatMessage.tsx`, preventing core bundle bloat.

## 3. Persistent Memory / History
Currently Elyan relies entirely on local UI state for chats. 
- **Extension Point:** If persistence is introduced, it must map strictly over `src/app/api/chat/route.ts` as a middleware layer fetching conversational JSON blobs.
- **Prohibited:** Over-architecting sprawling Prisma/Database models for simple key/value storage. If needed, leverage an embedded DB like `sqlite` or local volume mapping before attempting PostgreSQL layers.

## Modularity Law
If an extension modifies the core `speed` or `research` mode performance by more than `15ms`, or heavily modifies `globals.css` structure, it is structurally flawed and must be rewritten.
