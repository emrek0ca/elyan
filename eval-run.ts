import { runRoutingEval, formatRoutingEvalReport } from "./src/modules/tasks/routing-eval.js";
import { ROUTING_EVAL_CORPUS, ROUTING_EVAL_HELDOUT, type RoutingEvalCase } from "./src/modules/tasks/routing-eval-corpus.js";
import { matchDesktopCapabilitiesWithEmbeddings, isDesktopCapabilityVectorCacheReady, warmDesktopCapabilityVectors } from "./src/modules/tasks/desktop-capability-embedding-match.js";

const t0 = Date.now();
const warm = await warmDesktopCapabilityVectors();
console.log(`embedder ısınma: ${warm ? "TAMAM" : "BAŞARISIZ"} (${Date.now() - t0}ms), hazır=${isDesktopCapabilityVectorCacheReady()}`);
if (!warm) { console.log("embedder yok — hibrit ölçüm atlanıyor"); process.exit(0); }

async function evalHybrid(corpus: RoutingEvalCase[], label: string) {
  let top1 = 0, scored = 0, critical = 0, top3 = 0;
  const misses: string[] = [];
  for (const c of corpus) {
    const m = await matchDesktopCapabilitiesWithEmbeddings({ query: c.utterance, intent: c.intent ?? null, sideEffectLevel: c.sideEffectLevel ?? null, limit: 3 });
    const ids = m.map((x) => x.capability);
    const ok = new Set([c.expected, ...(c.alsoAcceptable ?? [])].filter(Boolean) as string[]);
    if (c.expected !== null) {
      scored++;
      if (ids[0] && ok.has(ids[0])) top1++; else misses.push(`  "${c.utterance}" → ${c.expected} bekleniyordu, ${ids.slice(0,3).join(", ")} geldi`);
      if (ids.slice(0,3).some((i) => ok.has(i))) top3++;
    }
    for (const f of c.mustNotMatch ?? []) if (ids[0] === f) critical++;
  }
  console.log(`\n=== ${label} (HİBRİT: e5 + sözcüksel) ===`);
  console.log(`top-1 ${top1}/${scored} (${(100*top1/scored).toFixed(1)}%) | top-3 ${(100*top3/scored).toFixed(1)}% | KRİTİK ihlal ${critical}`);
  if (misses.length) console.log(misses.slice(0, 12).join("\n"));
}
await evalHybrid(ROUTING_EVAL_HELDOUT, "TUTULAN KÜME");
await evalHybrid(ROUTING_EVAL_CORPUS, "ANA KORPUS");
