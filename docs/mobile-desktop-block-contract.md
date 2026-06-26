# Elyan Block Contract Handoff

This is the desktop-side handoff for keeping Mobile, Backend, and Electron Desktop on the same message/block protocol.

## Shared Message Shape

```json
{
  "id": "msg_...",
  "sessionId": "sess_...",
  "role": "user",
  "content": "Legacy fallback text",
  "blocks": [
    {
      "type": "text",
      "markdown": "...",
      "version": 1
    }
  ],
  "status": "completed",
  "createdAt": "2026-06-24T12:00:00Z"
}
```

`content` is legacy fallback text. If `blocks[]` exists, clients must render blocks first and use `content` only when blocks are missing or empty.

## Supported Block Types

Desktop now recognizes:

- `text`
- `code`
- `table`
- `chart`
- `file`
- `task_trace`
- `approval`
- `artifact`
- `terminal`
- `browser`
- `desktop_action`
- `error`

Unknown block types must not crash any client. Render a safe summary from `title`, `summary`, or `mobileFallback`.

## Streaming Events

Desktop accepts these renderer-level events through the `chat-block` subscription channel:

```json
{
  "type": "block_delta",
  "messageId": "msg_...",
  "blockIndex": 0,
  "appendMarkdown": "..."
}
```

```json
{
  "type": "block_replace",
  "messageId": "msg_...",
  "blockIndex": 1,
  "block": { "type": "task_trace", "status": "running" }
}
```

```json
{
  "type": "block_status",
  "messageId": "msg_...",
  "blockIndex": 2,
  "status": "running"
}
```

The event must target one message and one block. Clients should update only that message/block subtree.

## Desktop Runtime Reporting

When backend routes a mobile task to desktop:

1. Backend sends task to desktop runtime.
2. Desktop reports progress as `task_trace`, `terminal`, `desktop_action`, `approval`, `artifact`, or `error` blocks.
3. Backend stores those blocks in the session message.
4. Mobile and desktop render the same saved `blocks[]` payload.

Desktop-only blocks must stay semantic. Example:

```json
{
  "type": "desktop_action",
  "actionId": "act_...",
  "title": "Dosya kaydediliyor",
  "app": "Finder",
  "status": "running",
  "summary": "Seçilen görsel masaüstünde kaydediliyor.",
  "mobileFallback": {
    "type": "text",
    "markdown": "Bu işlem bağlı masaüstü cihazında yürütüldü."
  }
}
```

## Privacy Rules

- Do not expose API keys, tokens, cookies, raw prompts, private file content, or local full paths in blocks.
- Use `file`/`artifact` metadata for large content: id, title/name, mime, size, summary, and preview URL only when safe.
- Terminal/log output must be redacted and bounded before it reaches UI.
- Desktop actions that can affect the local computer must be represented by `approval` before execution.

## Mobile Requirements

Mobile should:

- Render `blocks[]` first and `content` only as fallback.
- Support safe fallback for unknown block types.
- Treat `desktop_action` as informational if it cannot perform the action.
- Read artifacts from backend artifact/session endpoints instead of expecting large content inline in chat.
- Show `task_trace` as a compact timeline with `running`, `completed`, `failed`, `skipped`, and `waiting_approval` states.
