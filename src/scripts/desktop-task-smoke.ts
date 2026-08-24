import { execFileSync } from "node:child_process";
import { buildDesktopWorkOrder } from "../modules/tasks/desktop-work-order.js";
import {
  buildPlanningPrompt,
  normalizeMaterializedSteps,
  readPlanningGatePrompt,
} from "../modules/tasks/materialize-plan.js";
import { pruneUnneededResearchSteps } from "../modules/tasks/plan-shortest-path.js";
import { writerBodyRestatesRequest } from "../modules/tasks/writer-content.js";
import { classifyKnowledgeRecency } from "../core/understanding/knowledge-recency.js";
import { resetSemanticComputeWorkerForTests } from "../modules/brain/semantic-compute-client.js";
import { latestDesktopTaskIdQuery } from "./desktop-task-smoke-queries.js";
import type { CommandRouteDecision } from "../modules/routing-policy/service.js";

/**
 * MASAÜSTÜ GÖREV DUMAN TESTİ.
 *
 * NEDEN VAR: 2026-08-22 gecesi kullanıcıya ÜST ÜSTE DÖRT kırık sürüm gönderdim.
 * Sebep her seferinde aynıydı — zincirin her halkasını ayrı ölçebiliyordum ama
 * tamamını koşamıyordum. Her arıza ancak kullanıcı görevi denedikten sonra,
 * canlı loglarda elle arkeoloji yaparak bulundu.
 *
 * İKİ MOD:
 *   (varsayılan)   yerel zincir — iş emri → tazelik → budama → istem → gövde
 *                  kapıları. Model/ağ/kimlik gerektirmez; sözleşme kaymasını
 *                  yakalar.
 *   --watch [id]   canlı görev yargısı — en son görevi (ya da verilen id'yi)
 *                  çekip tek ekranda karar verir: nereye gitti, kaç adım,
 *                  gövde üretildi mi, biçim doğru mu, artefakt var mı.
 *
 * `--watch` VPS'e ssh ile bağlanır (deploy ile aynı yol). Kimlik bilgisi
 * üretmez, yalnız okur.
 */

const SSH = ["-p", "2222", "-o", "ConnectTimeout=20", "-o", "BatchMode=yes", "root@84.247.172.213"];

/**
 * SSH GEÇİCİ OLARAK REDDEDEBİLİR.
 *
 * Bu araç ardışık çok sayıda bağlantı açıyor; sunucudaki hız sınırlaması
 * (fail2ban) arada "Connection refused" döndürüyor. Ölçüldü: üçüncü denemede
 * geçti. Geçici reddi arıza sanmamak için sınırlı yeniden deneme var.
 */
function psql(sql: string, attempt = 0): string {
  try {
    return execFileSync(
      "ssh",
      [...SSH, `docker exec elyan-backend-postgres-1 psql -U postgres -d elyan_backend -t -A -c ${JSON.stringify(sql)}`],
      { encoding: "utf8", timeout: 60_000 },
    ).trim();
  } catch (error) {
    const text = String((error as { stderr?: string }).stderr ?? error);
    if (attempt < 3 && /Connection refused|Operation timed out/i.test(text)) {
      execFileSync("sleep", ["12"]);
      return psql(sql, attempt + 1);
    }
    throw error;
  }
}

function desktopRoute(): CommandRouteDecision {
  return {
    route: "desktop_runtime",
    capabilities: [],
    taskRoute: { operationalRoute: "desktop_runtime" },
  } as unknown as CommandRouteDecision;
}

function desktopDirectoryQuestionRoute(): CommandRouteDecision {
  return {
    ...desktopRoute(),
    capabilities: ["desktop.runtime", "directory_tree"],
    requiresApproval: false,
    taskRoute: {
      operationalRoute: "desktop_runtime",
      requiredCapabilities: ["desktop.runtime", "directory_tree"],
      semanticDesktopContract: {
        contract: "elyan.semantic_desktop_dispatch.v1",
        route: "desktop_runtime",
        intent: "file_workflow",
        requiredSemanticCapabilities: ["directory_tree"],
        requiredLocalContext: ["filesystem"],
        sideEffectLevel: "read",
        confidence: 0.98,
        evidence: ["private local directory observation"],
      },
    },
  } as unknown as CommandRouteDecision;
}

type LocalCase = {
  message: string;
  expectWriter: string;
  expectResearch: boolean;
  expectFormat?: "pdf";
};

const LOCAL_CASES: LocalCase[] = [
  {
    message: "masaüstüne zürafalar hakkında bir pdf hazırla ve kaydet",
    expectWriter: "document_write",
    expectResearch: false,
    expectFormat: "pdf",
  },
  {
    message: "masaüstüne kediler hakkında bir rapor hazırla ve kaydet",
    expectWriter: "document_write",
    expectResearch: false,
  },
  {
    message: "masaüstüne bu ayki enflasyon rakamları hakkında rapor hazırla",
    expectWriter: "document_write",
    expectResearch: true,
  },
];

async function runLocal(): Promise<number> {
  let failures = 0;
  for (const testCase of LOCAL_CASES) {
    const order = buildDesktopWorkOrder({
      message: testCase.message,
      title: testCase.message,
      routeDecision: desktopRoute(),
      requestedCapabilities: [],
    } as never);
    const problems: string[] = [];

    // 1) Menü hedefle çelişmemeli: yazıcı var mı, gereksiz ekran otomasyonu yok mu?
    if (!order.requiredCapabilities.includes(testCase.expectWriter)) {
      problems.push(`menüde ${testCase.expectWriter} yok: ${order.requiredCapabilities.join(", ")}`);
    }
    if (order.requiredCapabilities.some((c) => c.startsWith("desktop_operator"))) {
      problems.push("bilgi görevinde ekran otomasyonu menüde");
    }

    // 2) Tazelik kararı ve budama
    const recency = await classifyKnowledgeRecency(readPlanningGatePrompt(order as never));
    const needsResearch = recency?.recency === "current_facts";
    if (needsResearch !== testCase.expectResearch) {
      problems.push(
        `tazelik beklenen ${testCase.expectResearch ? "current_facts" : "stable_knowledge"}, gelen ${recency?.recency ?? "karar yok"}`,
      );
    }
    const pruned = pruneUnneededResearchSteps({
      steps: [
        { id: "s1", capability: "web_research", description: "", args: { query: "x" }, dependsOn: [] },
        { id: "s2", capability: "document_write", description: "", args: { prompt: "{{steps.s1.output}}" }, dependsOn: ["s1"] },
      ] as never,
      recency: recency?.recency ?? null,
    });
    const researchSurvived = pruned.steps.some((s) => s.capability === "web_research");
    if (researchSurvived !== testCase.expectResearch) {
      problems.push(
        `budama beklenen ${testCase.expectResearch ? "araştırma kalsın" : "araştırma düşsün"}, sonuç tersi`,
      );
    }

    // 3) İstem üretilebiliyor ve plan sözleşmesi ayrıştırılabiliyor mu?
    const prompt = buildPlanningPrompt(order as never, [testCase.expectWriter, "web_research", "text_analyze"], "", recency?.recency ?? null);
    if (!prompt.includes(testCase.expectWriter)) problems.push("istemde yazıcı sözleşmesi yok");
    const parsed = normalizeMaterializedSteps(
      { plan: [{ id: "s1", capability: testCase.expectWriter, args: { prompt: "x" } }] },
      [testCase.expectWriter],
    );
    if (!parsed || parsed.length !== 1) problems.push("plan zarf toleransı kırık");

    // 4) İçerik kapısı: hedefin kendisi gövde olarak geçmemeli
    const restates = writerBodyRestatesRequest({
      step: { id: "s1", capability: testCase.expectWriter, description: "", args: { prompt: testCase.message }, dependsOn: [] } as never,
      goalSummary: testCase.message,
    });
    if (!restates) problems.push("içerik kapısı hedefin kopyasını gövde sayıyor");

    console.log(`${problems.length === 0 ? "✓" : "✗"} "${testCase.message}"`);
    for (const problem of problems) console.log(`    ${problem}`);
    failures += problems.length > 0 ? 1 : 0;
  }

  // 5) Canlı salt-okuma regresyonu: doğru capability ağır planner'a
  // düşmeden tek, onaysız ve yazma kapsamı olmayan adıma dönüşmeli.
  {
    const message = "Masaüstünde hangi klasörler var?";
    const order = buildDesktopWorkOrder({
      message,
      title: "Masaüstü klasörlerini listele",
      routeDecision: desktopDirectoryQuestionRoute(),
      requestedCapabilities: ["desktop.runtime", "directory_tree"],
    } as never);
    const problems: string[] = [];
    const stepCapabilities = order.planPreview.steps.map(
      (step) => step.capability,
    );
    if (JSON.stringify(stepCapabilities) !== JSON.stringify(["directory_tree"])) {
      problems.push(`tek directory_tree adımı bekleniyordu: ${stepCapabilities.join(", ")}`);
    }
    if (order.planPreview.planSource !== "deterministic_registry") {
      problems.push(`ağır planner yolu açık: ${order.planPreview.planSource ?? "yok"}`);
    }
    if (order.planPreview.planPreparation?.status !== "ready") {
      problems.push(`plan hazır değil: ${order.planPreview.planPreparation?.status ?? "yok"}`);
    }
    const approvalCapabilities = order.approvalCapabilities ?? [];
    if (order.requiresApproval || approvalCapabilities.length > 0) {
      problems.push(`salt-okuma görevi onay istiyor: ${approvalCapabilities.join(", ")}`);
    }
    if ((order.resourceScope?.writeRoots ?? []).length > 0) {
      problems.push(`salt-okuma görevi yazma kapsamı taşıyor: ${order.resourceScope?.writeRoots.join(", ")}`);
    }
    console.log(`${problems.length === 0 ? "✓" : "✗"} "${message}"`);
    for (const problem of problems) console.log(`    ${problem}`);
    failures += problems.length > 0 ? 1 : 0;
  }
  await resetSemanticComputeWorkerForTests();
  return failures;
}

function watch(taskId?: string): number {
  const id =
    taskId ??
    psql(latestDesktopTaskIdQuery()).trim();
  if (!id) {
    console.log("görev bulunamadı");
    return 1;
  }
  const row = psql(
    `select status::text || '|' || coalesce(to_char(created_at,'HH24:MI:SS'),'') || '|' || coalesce(to_char(updated_at,'HH24:MI:SS'),'') || '|' || coalesce(replace(left(payload->>'prompt',80), '|', '/'),'') from tasks where id='${id}'`,
  );
  const [status, created, updated, prompt] = row.split("|");
  const route = psql(
    `select coalesce(payload->'desktopWorkOrder'->'planPreview'->>'planSource','-') || '|' || coalesce(jsonb_array_length(payload->'desktopWorkOrder'->'planPreview'->'steps')::text,'0') || '|' || coalesce(payload->'metadata'->'routeDecision'->'taskRoute'->>'operationalRoute','-') from tasks where id='${id}'`,
  ).split("|");
  const artifact = psql(
    `select coalesce(jsonb_array_length(result->'blocks')::text,'0') || '|' || coalesce(result->'toolEvents'->0->>'output','-') from tasks where id='${id}'`,
  ).split("|");

  const problems: string[] = [];
  if (route[2] !== "desktop_runtime") problems.push(`ROTA: ${route[2]} (masaüstü bekleniyordu)`);
  if (status !== "completed") problems.push(`DURUM: ${status}`);
  const output = artifact[1] ?? "";
  if (/hazirla|kaydet|hakkinda/i.test(output)) {
    problems.push(`DOSYA ADI istek cümlesinden türemiş: ${output}`);
  }
  if (/pdf/i.test(prompt ?? "") && /\.docx/i.test(output)) {
    problems.push("BİÇİM: pdf istendi, docx üretildi");
  }

  // GECİKME GÖRÜNÜR OLSUN.
  //
  // Son canlı görev tek adımlık bir belge için 73 saniye sürdü ve nerede
  // geçtiği ancak logları elle tarayarak anlaşılıyordu. Aşama süreleri artık
  // aynı ekranda.
  let stages = "";
  try {
    stages = execFileSync(
      "ssh",
      [
        ...SSH,
        `docker logs --since 2h elyan-backend-backend-1 2>&1 | grep ${JSON.stringify(id)} | grep 'brain decision' | grep -o '"route":"[^"]*","model":"[^"]*"\\|"duration_ms":[0-9]*' | paste - - 2>/dev/null | tail -8`,
      ],
      { encoding: "utf8", timeout: 60_000 },
    ).trim();
  } catch {
    stages = "";
  }

  console.log(`görev ${id}`);
  console.log(`  istek     : ${prompt}`);
  console.log(`  durum     : ${status}  (${created} → ${updated})`);
  console.log(`  rota      : ${route[2]}   plan: ${route[0]} / ${route[1]} adım`);
  console.log(`  çıktı     : ${output}`);
  console.log(`  blok      : ${artifact[0]}`);
  if (stages) {
    console.log("  aşamalar  :");
    for (const line of stages.split("\n").slice(0, 8)) console.log(`     ${line.replace(/\s+/g, " ")}`);
  }
  console.log(problems.length === 0 ? "\n✓ SORUN GÖRÜLMEDİ" : `\n✗ ${problems.length} SORUN`);
  for (const problem of problems) console.log(`    ${problem}`);
  return problems.length > 0 ? 1 : 0;
}

async function main() {
  const args = process.argv.slice(2);
  const watchIndex = args.indexOf("--watch");
  if (watchIndex > -1) {
    process.exitCode = watch(args[watchIndex + 1]);
    return;
  }
  const failures = await runLocal();
  console.log(failures === 0 ? "\n✓ yerel zincir temiz" : `\n✗ ${failures} vakada sorun`);
  process.exitCode = failures > 0 ? 1 : 0;
}

void main();
