# Mimari

Elyan, modüler bir bileşen mimarisi üzerine inşa edilmiştir. Her bileşen bağımsız olarak test edilebilir ve değiştirilebilir.

## Genel Bakış

```
┌─────────────────────────────────────────────────────────┐
│                    Giriş Katmanı                        │
│  CLI (elyan)  │  Telegram Bot  │  Gateway HTTP/WS       │
└───────┬───────────────┬──────────────────┬──────────────┘
        │               │                  │
┌───────▼───────────────▼──────────────────▼──────────────┐
│                   Channel Adapter Katmanı                │
│  TelegramAdapter │ DiscordAdapter │ SlackAdapter │ ...   │
│         (core/gateway/adapters/)                        │
└──────────────────────────┬──────────────────────────────┘
                           │  UnifiedMessage
┌──────────────────────────▼──────────────────────────────┐
│                   Gateway Router                         │
│         (core/gateway/server.py)                        │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                   Agent Core                             │
│         (core/agent.py — process() entry point)         │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ Fast Path   │  │ Intent      │  │  Task Engine    │ │
│  │ (cache,     │  │ Parser      │  │  (LLM plan +    │ │
│  │  quick)     │  │             │  │   execute)      │ │
│  └─────────────┘  └─────────────┘  └─────────────────┘ │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                   Araç Katmanı                           │
│  system_tools │ file_tools │ research_tools │ browser   │
│         (tools/)                                        │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                   LLM Katmanı                            │
│  Groq → Gemini → Ollama (öncelik sırası)                │
│         (core/llm_client.py)                            │
└─────────────────────────────────────────────────────────┘
```

## Kritik Dosyalar

| Dosya | Rol |
|-------|-----|
| `core/agent.py` | Ana agent, `process()` giriş noktası |
| `core/task_engine/` | Görev ayrıştırma + çalıştırma |
| `core/intent_parser/` | Rule-based intent tanıma (7 modül) |
| `core/llm_client.py` | LLM API (Groq/Gemini/Ollama) |
| `core/fast_response.py` | Cache + hızlı yanıt (<100ms) |
| `core/quick_intent.py` | Pattern-based hızlı eşleşme |
| `core/gateway/server.py` | HTTP/WebSocket gateway |
| `core/gateway/adapters/` | 10 kanal adapter |
| `config/settings.py` | Tüm ayarlar, Keychain entegrasyonu |
| `security/` | 5 güvenlik modülü |

## Yanıt Akışı

```
User Input
  → [Response Cache]    HIT?  → Anında (<5ms)
  → [Quick Intent]      Basit? → <100ms (saat, hesap, selam)
  → [CHAT Fast Path]    Sohbet? → LLM.chat() (<2s, JSON yok)
  → [Intent Parser]     Rule-based → Tool + Params
  → [Task Engine]       LLM plan → execute → done
  → [Delivery Engine]   Karmaşık proje → state machine
```

## Intent Parser Modülleri (`core/intent_parser/`)

| Modül | Kapsam |
|-------|--------|
| `_system.py` | screenshot, volume, brightness, wifi, power |
| `_apps.py` | open/close app, URL, browser search, YouTube |
| `_files.py` | create_folder, list_files, write_file |
| `_research.py` | web_search, summarize, translate |
| `_documents.py` | Word, Excel, PDF, website, presentation |
| `_media.py` | email, calendar, reminder, music, code_run |

## Task Engine (`core/task_engine/`)

```python
TaskDefinition  →  LLM (tek çağrı)  →  [tool, params]
                →  _execute_tool(tool, params)
                →  TaskResult(success, output)
```

Tek LLM çağrısı, önceki AutonomousPlanner'a göre %60 daha az token.

## Delivery Engine (`core/delivery/`)

Karmaşık projeler (website, kod, doküman) için state machine:

```
IDLE → INTAKE → PLAN → EXECUTE (C1..Cn) → VERIFY → FIXLOOP → DELIVER
```

## LLM Katmanı

```python
# core/llm_client.py
class LLMClient:
    async def complete(prompt: str) -> str: ...  # JSON plan
    async def chat(messages: list) -> str: ...   # Sohbet (JSON yok)
```

Öncelik: Groq → Gemini → Ollama → hata

## Güvenlik Katmanı

Her araç çağrısı öncesinde:

```
RateLimiter → Validator → PrivacyGuard → ToolPolicy → ApprovalGate
```

Daha fazla: [Güvenlik Mimarisi →](../security/architecture.md)
