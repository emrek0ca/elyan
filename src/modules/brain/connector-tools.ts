import type { FastifyInstance } from "fastify";
import { rankSemanticTextCandidates } from "../../core/understanding/intent-semantic.js";
import { getConnectorAccessToken } from "../integrations/service.js";

/**
 * Server-side connector tools. They let the shared brain read (and, with
 * explicit approval, write) a mobile-only user's connected Google integrations
 * (Gmail/Calendar/Drive) directly through Google REST, using the already-stored
 * OAuth token, without a paired desktop.
 *
 * Read tools run inline. Write tools (send mail, create event) are marked
 * `side_effect`: the tool-registry blocks them unless the caller passes
 * `allowSideEffects`, which only the approval flow does after the user confirms
 * the drafted action. A drafted write never reaches Google without that gate.
 */

export type ConnectorToolPermission = "read" | "side_effect";

export type ConnectorToolContract = {
  /** Registry name used in tool_requests. */
  name: string;
  /** Capability the connection must grant. */
  capability: string;
  /** Read runs inline; side_effect requires explicit user approval. */
  permission: ConnectorToolPermission;
  /** Google OAuth scopes required for the underlying REST call. */
  requiredScopes: string[];
  /** Alternative complete scope sets that also authorize the same REST call. */
  alternativeScopeSets?: string[][];
  /** One-line contract advertised to the model. */
  contract: string;
  /** Capability-level multilingual prototypes used by the semantic router. */
  semanticDescriptions?: string[];
  /** False for operations that require a prior tool result (for example an id). */
  semanticRoutable?: boolean;
};

export type ConnectorCapabilityGrant = {
  provider: string;
  capabilities: string[];
  scopes: string[];
};

export type ConnectorReadToolHint = {
  tool: string;
  score: number;
  margin: number;
  source: "transformer";
};

export type ConnectorReadSelectionPolicy = {
  /** Typed understanding/routing already identified an external side effect. */
  sideEffectDetected?: boolean;
};

export const CONNECTOR_TOOL_CONTRACTS: ConnectorToolContract[] = [
  {
    name: "gmail.search",
    capability: "gmail",
    permission: "read",
    requiredScopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    contract:
      'gmail.search {query:string, limit?:1..10} — search the user\'s Gmail (Gmail query syntax, e.g. "from:ali is:unread"); returns message id, from, subject, date, snippet.',
    semanticDescriptions: [
      "Kendi bağlı Gmail hesabımdaki gelen kutusunu kontrol et; bugün gelen, yeni veya okunmamış e-postaları listele; mesajları gönderen, tarih veya konuya göre ara.",
      "Kendi Gmail gelen kutumda okunmamış veya yeni e-posta var mı; bugün hangi mailler geldi; gelen kutumda neler birikti?",
      // Tekil-mail ve gündelik kısa kalıplar da aramayla başlar (id'siz
      // gmail.read çağrılamaz): "son mailimi oku" önce son maili bulmaktır.
      // Bu kalıplar canlıda eşik altında kalıp aracı tamamen düşürüyordu.
      "Son mailimi oku; en son gelen e-postayı bul, aç ve içeriğini söyle; son 10 mailimi listele.",
      "Mailime bak; maillerimi kontrol et; posta kutuma bak; e-postalarımı kontrol eder misin?",
      // Canlıda kıl payı elenen emir kipi kalıplar: "Mailleri oku" 0.860
      // skorla eşiği rahat geçerken margin 0.0117 < 0.012 ile düşüyordu.
      "Mailleri oku; maillerimi oku; gelen kutumu oku; postalarımı göster; e-postalarımı oku.",
      "Read my emails; read my mail; show my inbox; open my mailbox.",
      "Check my connected Gmail inbox and list emails that arrived today, recent or unread messages, or search my mailbox by sender, date, and subject.",
      "Do I have any unread or new email in my inbox; what messages arrived today?",
      "Read my latest email; open the most recent message and tell me what it says; check my mail.",
    ],
  },
  {
    name: "gmail.read",
    capability: "gmail",
    permission: "read",
    requiredScopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    contract:
      "gmail.read {messageId:string} — read one Gmail message by id; returns from, to, subject, date and a plain-text body excerpt.",
    semanticRoutable: false,
    semanticDescriptions: [
      "Kimliği önceki bir araç sonucunda bulunan tek bir e-postayı aç ve tam içeriğini oku; gelen kutusunu listeleme veya arama.",
      "Open and read one specific email body only when its exact message ID is already known; do not list or search the inbox.",
    ],
  },
  {
    name: "calendar.list_events",
    capability: "calendar",
    permission: "read",
    requiredScopes: [
      "https://www.googleapis.com/auth/calendar.events.readonly",
    ],
    alternativeScopeSets: [["https://www.googleapis.com/auth/calendar.readonly"]],
    contract:
      "calendar.list_events {query?:string, days?:1..60, limit?:1..20} — list upcoming primary-calendar events within the next `days` (default 7); returns title, start, end, location.",
    semanticDescriptions: [
      "Kendi bağlı takvimimde bugün, yarın veya gelecek hafta hangi toplantı, randevu ve etkinliklerin olduğunu listele; ajandamı göster.",
      // Gündelik kısa kalıplar (gmail'de eşik altı kalıp dersinin takvim eşi):
      "Takvimime bak; bugün toplantım var mı; yarın neyim var; bu hafta programım nasıl?",
      "List actual meetings, appointments, events, and agenda items from my connected calendar for today, tomorrow, or a requested date range.",
      "Check my calendar; do I have any meetings today; what's on my schedule?",
    ],
  },
  {
    name: "drive.search",
    capability: "drive",
    permission: "read",
    requiredScopes: ["https://www.googleapis.com/auth/drive.readonly"],
    contract:
      "drive.search {query:string, limit?:1..20} — search the user's Google Drive by name/full text; returns file id, name, mimeType, modifiedTime, link.",
    semanticDescriptions: [
      "Kendi bağlı Drive hesabımda dosya, belge, tablo veya sunum ara ve eşleşen gerçek dosyaları listele.",
      // Gündelik kısa kalıplar:
      "Drive'ıma bak; drive'da şu dosyayı bul; son yüklediğim belgeleri göster.",
      "Search my connected Drive for an actual file, document, spreadsheet, or presentation and list matches.",
      "Check my Drive; find that file in my Drive; show my recent documents.",
    ],
  },
  {
    name: "notion.search",
    capability: "notion",
    permission: "read",
    requiredScopes: [],
    contract:
      "notion.search {query?:string, limit?:1..20} — search the user's connected Notion workspace pages and databases by title/text (empty query lists recently edited); returns page title, type, last edited time, link.",
    semanticDescriptions: [
      "Notion'da ara; Notion notlarıma bak; Notion sayfalarımda şunu bul; Notion'daki dokümanlarımı listele; not defterime bak.",
      "Notion çalışma alanımda geçen hafta düzenlediğim sayfalar hangileri; şu konuyla ilgili Notion sayfam var mı?",
      "Search my connected Notion workspace pages and databases; find that note in Notion; list my recently edited Notion pages.",
      "Check my Notion; what pages do I have about this topic?",
    ],
  },
  {
    name: "github.search",
    capability: "github",
    permission: "read",
    requiredScopes: [],
    contract:
      'github.search {query?:string, limit?:1..20} — search GitHub issues/PRs involving the user (GitHub search syntax; empty query means "involves:@me is:open" sorted by update); returns title, repo, state, updated time, link.',
    semanticDescriptions: [
      "GitHub'da işlerime bak; açık PR'larımı listele; issue'larımı göster; bana atanan GitHub işleri neler; pull request durumum ne?",
      "GitHub'da şu konuyla ilgili issue ara; repomdaki açık işleri getir.",
      "List my open GitHub pull requests and issues; what GitHub work involves me; check my assigned issues.",
      "Search GitHub issues and pull requests connected to my account.",
    ],
  },
  {
    name: "gmail.send",
    capability: "gmail",
    permission: "side_effect",
    requiredScopes: ["https://www.googleapis.com/auth/gmail.send"],
    contract:
      "gmail.send {to:string, subject:string, body:string, cc?:string, bcc?:string} — draft an email to send from the user's Gmail. REQUIRES the user to approve the draft first; never sends silently.",
  },
  {
    name: "calendar.create_event",
    capability: "calendar",
    permission: "side_effect",
    requiredScopes: ["https://www.googleapis.com/auth/calendar.events"],
    contract:
      "calendar.create_event {title:string, start:ISO8601, end:ISO8601, description?:string, location?:string, attendees?:string[]} — draft a primary-calendar event. REQUIRES the user to approve the draft first; never creates silently.",
  },
];

const CONNECTOR_TOOL_BY_NAME = new Map<string, ConnectorToolContract>(
  CONNECTOR_TOOL_CONTRACTS.map((entry) => [entry.name, entry]),
);

export function isConnectorTool(name: string): boolean {
  return CONNECTOR_TOOL_BY_NAME.has(name);
}

export function connectorToolContract(name: string): ConnectorToolContract | null {
  return CONNECTOR_TOOL_BY_NAME.get(name) ?? null;
}

/** Which connector tool contracts are available for a user's connected capabilities. */
export function connectorToolsForCapabilities(
  connectedCapabilities: string[],
): ConnectorToolContract[] {
  const connected = new Set(connectedCapabilities);
  return CONNECTOR_TOOL_CONTRACTS.filter((entry) =>
    connected.has(entry.capability) && entry.permission === "read",
  );
}

export function connectorRequiredScopeSets(
  contract: ConnectorToolContract,
): string[][] {
  const scopeSets = [
    contract.requiredScopes,
    ...(contract.alternativeScopeSets ?? []),
  ].filter((scopeSet) => scopeSet.length > 0);
  // Scope kavramı olmayan sağlayıcılar (Notion; GitHub token'ı bağlantıda
  // verilen kapsamla gelir): boş küme "ek scope şartı yok" demektir. Boş
  // listeye indirgemek bu araçları "asla yetkili değil"e çeviriyordu.
  return scopeSets.length > 0 ? scopeSets : [[]];
}

function connectorToolsForCapabilityGrantsByPermission(
  grants: ConnectorCapabilityGrant[],
  permission: ConnectorToolPermission,
  hasRequiredScopes: (
    provider: string,
    grantedScopes: string[],
    requiredScopes: string[],
  ) => boolean,
): ConnectorToolContract[] {
  return CONNECTOR_TOOL_CONTRACTS.filter((entry) => {
    if (entry.permission !== permission) {
      return false;
    }
    return grants.some((grant) => {
      if (!grant.capabilities.includes(entry.capability)) {
        return false;
      }
      return connectorRequiredScopeSets(entry).some((scopeSet) =>
        hasRequiredScopes(grant.provider, grant.scopes, scopeSet),
      );
    });
  });
}

export function connectorToolsForCapabilityGrants(
  grants: ConnectorCapabilityGrant[],
  hasRequiredScopes: (
    provider: string,
    grantedScopes: string[],
    requiredScopes: string[],
  ) => boolean,
): ConnectorToolContract[] {
  return connectorToolsForCapabilityGrantsByPermission(
    grants,
    "read",
    hasRequiredScopes,
  );
}

/**
 * Which side_effect (write) connector contracts — gmail.send,
 * calendar.create_event — are authorized for a user's grants. These are
 * advertised to the model so a "send this email" / "create this event" request
 * can be drafted; the draft never reaches Google without the explicit approval
 * gate (side_effect requests are staged, not executed inline).
 *
 * A write contract needs its own send/write scope (e.g. gmail.send), which is a
 * different scope from the read scope. A user connected read-only will not see
 * the write tool advertised, which correctly surfaces as "reconnect for send
 * permission" instead of a silent failure at execution time.
 */
export function connectorWriteToolsForCapabilityGrants(
  grants: ConnectorCapabilityGrant[],
  hasRequiredScopes: (
    provider: string,
    grantedScopes: string[],
    requiredScopes: string[],
  ) => boolean,
): ConnectorToolContract[] {
  return connectorToolsForCapabilityGrantsByPermission(
    grants,
    "side_effect",
    hasRequiredScopes,
  );
}

const CONNECTOR_SEMANTIC_NEGATIVE_CANDIDATES = [
  {
    id: "negative:explain",
    description:
      "Explain, teach, compare, or describe an email, calendar, cloud storage application, API, SDK, feature, or concept without accessing the user's connected account data.",
  },
  {
    id: "negative:explain",
    description:
      "Gmail API nasıl kullanılır; e-posta, takvim veya Drive uygulaması nasıl çalışır; SDK ve kod örneği ver; kişisel hesaba erişmeden genel teknik açıklama yap.",
  },
  // "notion nedir anlatır mısın" canlıda notion.search hint'i alıyordu:
  // eğitsel "nedir/nasıl çalışır" soruları hesap verisi okumadan yanıtlanır.
  {
    id: "negative:explain",
    description:
      "Notion nedir; GitHub nasıl çalışır; Slack ne işe yarar; bir uygulamanın, servisin veya aracın ne olduğunu hesabımdaki verilere bakmadan anlat ve tanıt.",
  },
  {
    id: "negative:explain",
    description:
      "What is Notion; how does GitHub work; describe what an app, service, or tool does in general without reading my connected account data.",
  },
  {
    id: "negative:compose",
    description:
      "Draft, rewrite, translate, or improve text such as an email or calendar invitation without reading from or acting on a connected account.",
  },
  {
    id: "negative:compose",
    description:
      "Birine gönderilecek e-posta metni yaz, mail taslağı hazırla veya davet metnini düzelt; bağlı hesaptaki verileri okuma.",
  },
  {
    id: "negative:write",
    description:
      "Create, send, delete, modify, or otherwise change connected account data. This is a side effect and must not be routed to a read-only connector tool.",
  },
  {
    id: "negative:write",
    description:
      "E-posta gönder, sil veya taşı; takvime etkinlik ekle; bağlı hesap verisini değiştir ve açık kullanıcı onayı iste.",
  },
  {
    id: "negative:general",
    description:
      "General conversation or a request that can be answered without reading the user's private connected account data.",
  },
  {
    id: "negative:general",
    description:
      "Bağlı özel hesap verilerini okumadan yanıtlanabilen genel sohbet, bilgi, yazma, kodlama veya açıklama isteği.",
  },
] as const;

function advertisedConnectorNames(contracts: string[]): Set<string> {
  return new Set(
    contracts
      .map((contract) => contract.trim().match(/^([a-z0-9_.-]+)/i)?.[1])
      .filter((name): name is string => Boolean(name)),
  );
}

export function connectorContractsForSemanticReadHint(
  advertisedContracts: string[],
  selectedTool: string | null | undefined,
): string[] {
  // İpucu yalnız önceliklendirme sinyalidir. Üretilemediyse (eşik altı skor,
  // worker zaman aşımı, tekil-mail gibi aday listesinde olmayan ifadeler)
  // reklam listesi OLDUĞU GİBİ kalır: burada fail-closed olmak "Son mailimi
  // oku" gibi meşru istekleri araçsız bırakıp "erişimim yok" cevabı üretiyordu.
  // Yürütme zaten advertised-tool + OAuth scope + izin kapılarından geçer.
  if (!selectedTool) return advertisedContracts;
  const filtered = advertisedContracts.filter((contract) => {
    const name = contract.trim().match(/^([a-z0-9_.-]+)/i)?.[1];
    if (name === selectedTool) return true;
    // A read hint prioritizes one read tool, but it must never strip the
    // side_effect (write) contracts from the advertisement: dropping gmail.send
    // here is what left "send this email" with no draftable tool.
    return CONNECTOR_TOOL_BY_NAME.get(name ?? "")?.permission === "side_effect";
  });
  return filtered.length > 0 ? filtered : advertisedContracts;
}

/**
 * Selects a read-only connector operation from the contracts already allowed
 * for this request. The candidates come from the live connector registry, not
 * from user-phrase rules, so new paraphrases do not require new regexes.
 *
 * Only a high-confidence multilingual transformer result is accepted. Hash
 * fallback, meta/explanation prompts, write requests, and ambiguous matches
 * fail closed and produce no hint. This is a prompt hint only: execution still
 * passes through advertised-tool, OAuth-scope, and permission checks.
 */
export async function selectSemanticConnectorReadToolHint(
  prompt: string,
  advertisedContracts: string[],
  policy: ConnectorReadSelectionPolicy = {},
): Promise<ConnectorReadToolHint | null> {
  // Do not let topical similarity turn a send/create/delete request into a
  // read operation. This consumes the existing typed risk decision; it does
  // not reinterpret the user's sentence here.
  if (policy.sideEffectDetected) return null;

  const advertisedNames = advertisedConnectorNames(advertisedContracts);
  const readContracts = CONNECTOR_TOOL_CONTRACTS.filter(
    (entry) =>
      entry.permission === "read" &&
      entry.semanticRoutable !== false &&
      advertisedNames.has(entry.name),
  );
  if (readContracts.length === 0) return null;

  const match = await rankSemanticTextCandidates(
    prompt,
    [
      ...readContracts.flatMap((entry) =>
        (entry.semanticDescriptions?.length
          ? entry.semanticDescriptions
          : [entry.contract]
        ).map((description) => ({
          id: `tool:${entry.name}`,
          description: `${entry.name}: ${description}`,
        })),
      ),
      ...CONNECTOR_SEMANTIC_NEGATIVE_CANDIDATES,
    ],
    {
      transformerMinScore: 0.78,
      // 0.012 canlıda meşru "Mailleri oku" kalıbını 0.0003 farkla eledi
      // (margin 0.0117, ikinci sıra bir negative çapasıydı). Yazma riski
      // zaten sideEffectDetected + negative çapalarla ayrı kapıda; margin
      // burada yalnız araçlar-arası belirsizliği ölçmeli.
      transformerMinMargin: 0.008,
      transformerTimeoutMs: 20_000,
      // Permission-sensitive routing must never be decided by the degraded
      // lexical/hash approximation.
      hashMinScore: 1.1,
      hashMinMargin: 1.1,
    },
  );
  if (!match || match.source !== "transformer") return null;
  if (!match.id.startsWith("tool:")) return null;

  const tool = match.id.slice("tool:".length);
  if (!readContracts.some((entry) => entry.name === tool)) return null;
  return {
    tool,
    score: match.score,
    margin: match.margin,
    source: "transformer",
  };
}

function clip(value: unknown, max = 500): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

async function googleGet(
  accessToken: string,
  url: string,
  timeoutMs = 8_000,
): Promise<Record<string, unknown>> {
  const response = await fetch(url, {
    signal: AbortSignal.timeout(timeoutMs),
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json",
    },
  });
  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    const message =
      typeof (payload.error as { message?: unknown })?.message === "string"
        ? String((payload.error as { message?: unknown }).message)
        : `Google API request failed (${response.status})`;
    throw Object.assign(new Error(message), {
      code: response.status === 401 || response.status === 403
        ? "connector_auth_required"
        : "connector_request_failed",
    });
  }
  return payload;
}

async function googlePost(
  accessToken: string,
  url: string,
  body: Record<string, unknown> | string,
  contentType = "application/json",
  timeoutMs = 10_000,
): Promise<Record<string, unknown>> {
  const response = await fetch(url, {
    method: "POST",
    signal: AbortSignal.timeout(timeoutMs),
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json",
      "Content-Type": contentType,
    },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    const message =
      typeof (payload.error as { message?: unknown })?.message === "string"
        ? String((payload.error as { message?: unknown }).message)
        : `Google API request failed (${response.status})`;
    throw Object.assign(new Error(message), {
      code:
        response.status === 401 || response.status === 403
          ? "connector_auth_required"
          : "connector_request_failed",
    });
  }
  return payload;
}

function headerValue(
  headers: Array<{ name?: unknown; value?: unknown }>,
  name: string,
): string {
  const match = headers.find(
    (header) => String(header.name ?? "").toLowerCase() === name.toLowerCase(),
  );
  return clip(match?.value ?? "", 240);
}

function decodeBase64Url(value: string): string {
  try {
    return Buffer.from(value.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(
      "utf8",
    );
  } catch {
    return "";
  }
}

function extractPlainTextBody(payload: Record<string, unknown>): string {
  const parts = Array.isArray(payload.parts)
    ? (payload.parts as Record<string, unknown>[])
    : [];
  const mimeType = String(payload.mimeType ?? "");
  const body = payload.body as { data?: unknown } | undefined;
  if (mimeType === "text/plain" && typeof body?.data === "string") {
    return decodeBase64Url(body.data);
  }
  for (const part of parts) {
    const nested = extractPlainTextBody(part);
    if (nested) return nested;
  }
  if (mimeType === "text/html" && typeof body?.data === "string") {
    return decodeBase64Url(body.data).replace(/<[^>]+>/g, " ");
  }
  return "";
}

async function resolveToken(
  app: FastifyInstance,
  userId: string,
  contract: ConnectorToolContract,
): Promise<string> {
  try {
    const { accessToken } = await getConnectorAccessToken(app, {
      userId,
      capability: contract.capability,
      requiredScopes: contract.requiredScopes,
      acceptedScopeSets: connectorRequiredScopeSets(contract),
      refreshTimeoutMs: 8_000,
    });
    return accessToken;
  } catch (error) {
    const code =
      error && typeof error === "object" && "code" in error
        ? String((error as { code?: unknown }).code ?? "")
        : "";
    if (code === "not_found" || code === "bad_request" || code === "unauthorized") {
      throw Object.assign(new Error("Connector authorization is required."), {
        code: "connector_auth_required",
      });
    }
    throw error;
  }
}

export async function executeGmailSearch(
  app: FastifyInstance,
  userId: string,
  args: { query: string; limit: number },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(app, userId, CONNECTOR_TOOL_BY_NAME.get("gmail.search")!);
  const listUrl = new URL("https://gmail.googleapis.com/gmail/v1/users/me/messages");
  listUrl.searchParams.set("q", args.query);
  listUrl.searchParams.set("maxResults", String(args.limit));
  const listPayload = await googleGet(token, listUrl.toString());
  const messages = Array.isArray(listPayload.messages)
    ? (listPayload.messages as Record<string, unknown>[]).slice(0, args.limit)
    : [];
  const results = await Promise.all(
    messages.map(async (message) => {
      const id = String(message.id ?? "");
      if (!id) return null;
      const metaUrl = new URL(
        `https://gmail.googleapis.com/gmail/v1/users/me/messages/${encodeURIComponent(id)}`,
      );
      metaUrl.searchParams.set("format", "metadata");
      for (const header of ["From", "Subject", "Date"]) {
        metaUrl.searchParams.append("metadataHeaders", header);
      }
      const meta = await googleGet(token, metaUrl.toString()).catch(() => null);
      if (!meta) return null;
      const headers = Array.isArray((meta.payload as Record<string, unknown>)?.headers)
        ? ((meta.payload as Record<string, unknown>).headers as Array<{
            name?: unknown;
            value?: unknown;
          }>)
        : [];
      return {
        messageId: id,
        from: headerValue(headers, "From"),
        subject: headerValue(headers, "Subject"),
        date: headerValue(headers, "Date"),
        snippet: clip(meta.snippet, 280),
      };
    }),
  );
  const filtered = results.filter(
    (item): item is NonNullable<typeof item> => item != null,
  );
  return { query: args.query, resultCount: filtered.length, results: filtered };
}

export async function executeGmailRead(
  app: FastifyInstance,
  userId: string,
  args: { messageId: string },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(app, userId, CONNECTOR_TOOL_BY_NAME.get("gmail.read")!);
  const url = new URL(
    `https://gmail.googleapis.com/gmail/v1/users/me/messages/${encodeURIComponent(args.messageId)}`,
  );
  url.searchParams.set("format", "full");
  const payload = await googleGet(token, url.toString());
  const messagePayload = (payload.payload as Record<string, unknown>) ?? {};
  const headers = Array.isArray(messagePayload.headers)
    ? (messagePayload.headers as Array<{ name?: unknown; value?: unknown }>)
    : [];
  return {
    messageId: args.messageId,
    from: headerValue(headers, "From"),
    to: headerValue(headers, "To"),
    subject: headerValue(headers, "Subject"),
    date: headerValue(headers, "Date"),
    snippet: clip(payload.snippet, 280),
    body: clip(extractPlainTextBody(messagePayload), 4_000),
  };
}

export async function executeCalendarListEvents(
  app: FastifyInstance,
  userId: string,
  args: { query?: string; days: number; limit: number },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(
    app,
    userId,
    CONNECTOR_TOOL_BY_NAME.get("calendar.list_events")!,
  );
  const now = new Date();
  const timeMax = new Date(now.getTime() + args.days * 24 * 60 * 60 * 1_000);
  const url = new URL(
    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
  );
  url.searchParams.set("timeMin", now.toISOString());
  url.searchParams.set("timeMax", timeMax.toISOString());
  url.searchParams.set("singleEvents", "true");
  url.searchParams.set("orderBy", "startTime");
  url.searchParams.set("maxResults", String(args.limit));
  if (args.query?.trim()) {
    url.searchParams.set("q", args.query.trim());
  }
  const payload = await googleGet(token, url.toString());
  const items = Array.isArray(payload.items)
    ? (payload.items as Record<string, unknown>[]).slice(0, args.limit)
    : [];
  const events = items.map((item) => {
    const start = item.start as { dateTime?: unknown; date?: unknown } | undefined;
    const end = item.end as { dateTime?: unknown; date?: unknown } | undefined;
    return {
      title: clip(item.summary ?? "(başlıksız)", 200),
      start: clip(start?.dateTime ?? start?.date ?? "", 40),
      end: clip(end?.dateTime ?? end?.date ?? "", 40),
      location: clip(item.location ?? "", 200),
    };
  });
  return { days: args.days, resultCount: events.length, results: events };
}

export async function executeDriveSearch(
  app: FastifyInstance,
  userId: string,
  args: { query: string; limit: number },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(app, userId, CONNECTOR_TOOL_BY_NAME.get("drive.search")!);
  const escaped = args.query.replace(/['\\]/g, " ").trim();
  const url = new URL("https://www.googleapis.com/drive/v3/files");
  url.searchParams.set("q", escaped
    ? `(name contains '${escaped}' or fullText contains '${escaped}') and trashed = false`
    : "trashed = false");
  url.searchParams.set("pageSize", String(args.limit));
  url.searchParams.set(
    "fields",
    "files(id,name,mimeType,modifiedTime,webViewLink)",
  );
  url.searchParams.set("orderBy", "modifiedTime desc");
  const payload = await googleGet(token, url.toString());
  const files = Array.isArray(payload.files)
    ? (payload.files as Record<string, unknown>[]).slice(0, args.limit)
    : [];
  const results = files.map((file) => ({
    fileId: String(file.id ?? ""),
    name: clip(file.name ?? "", 240),
    mimeType: String(file.mimeType ?? ""),
    modifiedTime: clip(file.modifiedTime ?? "", 40),
    link: clip(file.webViewLink ?? "", 400),
  }));
  return { query: args.query, resultCount: results.length, results };
}

// ── Write tools (side_effect — reachable only through the approval gate) ──────

function base64Url(value: string): string {
  return Buffer.from(value, "utf8")
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * RFC 2822 header values must stay ASCII. Turkish subjects/names carry
 * non-ASCII, so encode them as a MIME "encoded-word" (RFC 2047) when needed;
 * the body itself is declared UTF-8 and left as-is.
 */
function encodeHeaderValue(value: string): string {
  const normalized = value.replace(/[\r\n]+/g, " ").trim();
  // eslint-disable-next-line no-control-regex
  if (/^[\x00-\x7F]*$/.test(normalized)) {
    return normalized;
  }
  return `=?UTF-8?B?${Buffer.from(normalized, "utf8").toString("base64")}?=`;
}

function buildRfc822Message(args: {
  to: string;
  subject: string;
  body: string;
  cc?: string;
  bcc?: string;
}): string {
  const lines: string[] = [`To: ${encodeHeaderValue(args.to)}`];
  if (args.cc?.trim()) {
    lines.push(`Cc: ${encodeHeaderValue(args.cc)}`);
  }
  if (args.bcc?.trim()) {
    lines.push(`Bcc: ${encodeHeaderValue(args.bcc)}`);
  }
  lines.push(
    `Subject: ${encodeHeaderValue(args.subject)}`,
    "MIME-Version: 1.0",
    'Content-Type: text/plain; charset="UTF-8"',
    "Content-Transfer-Encoding: 8bit",
    "",
    args.body.replace(/\r\n/g, "\n"),
  );
  return lines.join("\r\n");
}

export async function executeGmailSend(
  app: FastifyInstance,
  userId: string,
  args: {
    to: string;
    subject: string;
    body: string;
    cc?: string;
    bcc?: string;
  },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(
    app,
    userId,
    CONNECTOR_TOOL_BY_NAME.get("gmail.send")!,
  );
  const raw = base64Url(buildRfc822Message(args));
  const payload = await googlePost(
    token,
    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
    { raw },
  );
  return {
    messageId: String(payload.id ?? ""),
    threadId: String(payload.threadId ?? ""),
    to: args.to,
    subject: args.subject,
    sent: true,
  };
}

export async function executeCalendarCreateEvent(
  app: FastifyInstance,
  userId: string,
  args: {
    title: string;
    start: string;
    end: string;
    description?: string;
    location?: string;
    attendees?: string[];
  },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(
    app,
    userId,
    CONNECTOR_TOOL_BY_NAME.get("calendar.create_event")!,
  );
  const eventBody: Record<string, unknown> = {
    summary: args.title,
    start: { dateTime: args.start },
    end: { dateTime: args.end },
  };
  if (args.description?.trim()) {
    eventBody.description = args.description.trim();
  }
  if (args.location?.trim()) {
    eventBody.location = args.location.trim();
  }
  const attendees = (args.attendees ?? [])
    .map((email) => email.trim())
    .filter((email) => email.length > 0)
    .slice(0, 25)
    .map((email) => ({ email }));
  if (attendees.length > 0) {
    eventBody.attendees = attendees;
  }
  const payload = await googlePost(
    token,
    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
    eventBody,
  );
  return {
    eventId: String(payload.id ?? ""),
    title: args.title,
    start: args.start,
    end: args.end,
    link: clip(payload.htmlLink ?? "", 400),
    created: true,
  };
}

// ── Approval draft ───────────────────────────────────────────────────────────

export type ConnectorWriteDraft = {
  /** Registry tool that will run on approval. */
  tool: string;
  /** App label for the approval chip (e.g. "Gmail"). */
  appLabel: string;
  /** Short imperative confirm title (e.g. "E-posta gönderilsin mi?"). */
  title: string;
  /** Field lines shown in the draft card, in display order. */
  lines: Array<{ label: string; value: string }>;
};

const CONNECTOR_WRITE_APP_LABELS: Record<string, string> = {
  "gmail.send": "Gmail",
  "calendar.create_event": "Takvim",
};

/**
 * Build the human-facing approval draft for a side_effect connector request.
 * Pure and side-effect free: the canonically staged call runs only after the
 * user approves this exact draft. Returns null for tools that are not
 * approval-drafted writes.
 */
export function describeConnectorWriteDraft(
  tool: string,
  args: Record<string, unknown>,
): ConnectorWriteDraft | null {
  const appLabel = CONNECTOR_WRITE_APP_LABELS[tool];
  if (!appLabel) {
    return null;
  }
  if (tool === "gmail.send") {
    const lines: Array<{ label: string; value: string }> = [
      { label: "Kime", value: clip(args.to, 240) },
      { label: "Konu", value: clip(args.subject, 240) },
      { label: "İçerik", value: clip(args.body, 10_000) },
    ];
    if (clip(args.cc)) {
      lines.splice(1, 0, { label: "Cc", value: clip(args.cc, 240) });
    }
    if (clip(args.bcc)) {
      const ccIndex = lines.findIndex((line) => line.label === "Cc");
      lines.splice(ccIndex >= 0 ? ccIndex + 1 : 1, 0, {
        label: "Bcc",
        value: clip(args.bcc, 240),
      });
    }
    return {
      tool,
      appLabel,
      title: "E-posta gönderilsin mi?",
      lines,
    };
  }
  if (tool === "calendar.create_event") {
    const lines: Array<{ label: string; value: string }> = [
      { label: "Başlık", value: clip(args.title, 240) },
      { label: "Başlangıç", value: clip(args.start, 60) },
      { label: "Bitiş", value: clip(args.end, 60) },
    ];
    if (clip(args.location)) {
      lines.push({ label: "Yer", value: clip(args.location, 240) });
    }
    if (clip(args.description)) {
      lines.push({ label: "Açıklama", value: clip(args.description, 4_000) });
    }
    const attendees = Array.isArray(args.attendees)
      ? (args.attendees as unknown[]).map((value) => clip(value, 240)).filter(Boolean)
      : [];
    if (attendees.length > 0) {
      lines.push({ label: "Katılımcılar", value: attendees.join(", ") });
    }
    return {
      tool,
      appLabel,
      title: "Etkinlik oluşturulsun mu?",
      lines,
    };
  }
  return null;
}

// ── Notion + GitHub read executors ───────────────────────────────────
// Aynı resolveToken/capability-grant kapılarından geçer; salt-okunur.
// integration_connections'ta notion/github "connected" olduğu hâlde katalog
// yalnız Google araçlarını taşıyordu — bağlı hesaplar beyne bağlanmamıştı.

function textOf(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

async function notionRequest(
  accessToken: string,
  url: string,
  body: Record<string, unknown>,
  timeoutMs = 10_000,
): Promise<Record<string, unknown>> {
  const response = await fetch(url, {
    method: "POST",
    signal: AbortSignal.timeout(timeoutMs),
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json",
      "Content-Type": "application/json",
      "Notion-Version": "2022-06-28",
    },
    body: JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    const message =
      typeof payload.message === "string"
        ? payload.message
        : `Notion API request failed (${response.status})`;
    throw Object.assign(new Error(message), {
      code:
        response.status === 401 || response.status === 403
          ? "connector_auth_required"
          : "connector_request_failed",
    });
  }
  return payload;
}

function notionEntryTitle(entry: Record<string, unknown>): string {
  if (entry.object === "database" && Array.isArray(entry.title)) {
    const joined = (entry.title as Array<Record<string, unknown>>)
      .map((part) => textOf(part.plain_text))
      .join("");
    if (joined.trim()) return joined.trim();
  }
  const properties =
    entry.properties && typeof entry.properties === "object" && !Array.isArray(entry.properties)
      ? (entry.properties as Record<string, unknown>)
      : {};
  for (const property of Object.values(properties)) {
    const record =
      property && typeof property === "object" && !Array.isArray(property)
        ? (property as Record<string, unknown>)
        : null;
    if (record?.type === "title" && Array.isArray(record.title)) {
      const joined = (record.title as Array<Record<string, unknown>>)
        .map((part) => textOf(part.plain_text))
        .join("");
      if (joined.trim()) return joined.trim();
    }
  }
  return "(başlıksız)";
}

export async function executeNotionSearch(
  app: FastifyInstance,
  userId: string,
  args: { query: string; limit: number },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(
    app,
    userId,
    CONNECTOR_TOOL_BY_NAME.get("notion.search")!,
  );
  const payload = await notionRequest(token, "https://api.notion.com/v1/search", {
    ...(args.query.trim() ? { query: args.query.trim() } : {}),
    page_size: args.limit,
    sort: { direction: "descending", timestamp: "last_edited_time" },
  });
  const entries = Array.isArray(payload.results)
    ? (payload.results as Record<string, unknown>[]).slice(0, args.limit)
    : [];
  const results = entries.map((entry) => ({
    title: clip(notionEntryTitle(entry), 240),
    kind: entry.object === "database" ? "database" : "page",
    updatedAt: textOf(entry.last_edited_time),
    url: textOf(entry.url),
  }));
  return { query: args.query, resultCount: results.length, results };
}

export async function executeGithubSearch(
  app: FastifyInstance,
  userId: string,
  args: { query: string; limit: number },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(
    app,
    userId,
    CONNECTOR_TOOL_BY_NAME.get("github.search")!,
  );
  const query = args.query.trim() || "involves:@me is:open";
  const url = new URL("https://api.github.com/search/issues");
  url.searchParams.set("q", query);
  url.searchParams.set("per_page", String(args.limit));
  url.searchParams.set("sort", "updated");
  const response = await fetch(url.toString(), {
    signal: AbortSignal.timeout(10_000),
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      // GitHub API, User-Agent başlıksız istekleri 403 ile reddeder.
      "User-Agent": "elyan-backend",
    },
  });
  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    const message =
      typeof payload.message === "string"
        ? payload.message
        : `GitHub API request failed (${response.status})`;
    throw Object.assign(new Error(message), {
      code:
        response.status === 401 || response.status === 403
          ? "connector_auth_required"
          : "connector_request_failed",
    });
  }
  const items = Array.isArray(payload.items)
    ? (payload.items as Record<string, unknown>[]).slice(0, args.limit)
    : [];
  const results = items.map((item) => ({
    title: clip(item.title, 240),
    repo: textOf(item.repository_url).split("/repos/").pop() ?? "",
    state: textOf(item.state),
    kind: item.pull_request ? "pull_request" : "issue",
    updatedAt: textOf(item.updated_at),
    url: textOf(item.html_url),
  }));
  return { query, resultCount: results.length, results };
}
