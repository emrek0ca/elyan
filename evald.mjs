const { warmDesktopCapabilityVectors } = await import("./dist/modules/tasks/desktop-capability-embedding-match.js");
const { embedQueryForStorage } = await import("./dist/modules/brain/semantic-embedder.js");
const { matchDesktopCapabilitiesSemantically } = await import("./dist/modules/tasks/desktop-capability-ontology.js");
const { ROUTING_EVAL_CORPUS, ROUTING_EVAL_HELDOUT } = await import("./dist/modules/tasks/routing-eval-corpus.js");
const vecs = await warmDesktopCapabilityVectors();
const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
const norm=vs=>{const mn=Math.min(...vs),mx=Math.max(...vs),sp=mx-mn;return sp<=1e-9?vs.map(()=>0):vs.map(v=>(v-mn)/sp);};
const cases=[...ROUTING_EVAL_CORPUS,...ROUTING_EVAL_HELDOUT];
const prepared=[];
for (const c of cases) {
  const qv = await embedQueryForStorage(c.utterance, undefined, "desktop_capability_ontology_v2", 5000);
  const lexMap = new Map(matchDesktopCapabilitiesSemantically({query:c.utterance,limit:128,threshold:0}).map(m=>[m.capability,m.score]));
  const sem = vecs.map(v=>{
    const ident = dot(qv, v.positives[0]);
    // Kısa cümleler kısa cümlelerle yarışsın: utterance'lar ile karşı-örnekler
    // aynı uzunluk/biçimde; kimlik metni ayrı ve zayıf bir sinyal.
    const utt = v.positives.length>1 ? Math.max(...v.positives.slice(1).map(p=>dot(qv,p))) : ident;
    const neg = v.negatives.length ? Math.max(...v.negatives.map(p=>dot(qv,p))) : 0;
    return { cap: v.capability, pos: Math.max(ident*0.85, utt), margin: Math.max(0, neg - utt) };
  });
  prepared.push({ c, sem, nSem: norm(sem.map(s=>s.pos)), nLex: norm(sem.map(s=>lexMap.get(s.cap)??0)) });
}
function run(w,pen){ let h1=0,hs=0,m1=0,ms=0,crit=0;
  for (const p of prepared) {
    const ids = p.sem.map((s,i)=>({cap:s.cap,v:w*p.nSem[i]+(1-w)*p.nLex[i]-pen*s.margin})).sort((a,b)=>b.v-a.v).slice(0,3).map(x=>x.cap);
    const ok = new Set([p.c.expected,...(p.c.alsoAcceptable??[])].filter(Boolean));
    const held = p.c.group.startsWith("heldout");
    if (p.c.expected!==null){ if(held){hs++; if(ok.has(ids[0]))h1++;} else {ms++; if(ok.has(ids[0]))m1++;} }
    for (const f of p.c.mustNotMatch??[]) if(ids[0]===f) crit++;
  }
  return {held:h1/hs, main:m1/ms, crit}; }
console.log("marj-tabanlı ceza (yalnız karşı-örnek gerçekten öndeyken devreye girer)");
console.log("ağırlık ceza | tutulan   ana    kritik");
let best=null;
for (const w of [0.6,0.65,0.7,0.75,0.8]) for (const pen of [0,1,2,4,8]) {
  const r=run(w,pen); const obj=r.held+r.main-0.015*r.crit;
  if(!best||obj>best.obj) best={w,pen,obj,...r};
  if (pen>0 || w===0.7) console.log(`  ${w}   ${pen}  | ${(100*r.held).toFixed(1)}%   ${(100*r.main).toFixed(1)}%   ${r.crit}`);
}
console.log(`\nEN İYİ: ağırlık=${best.w} ceza=${best.pen} → tutulan ${(100*best.held).toFixed(1)}%  ana ${(100*best.main).toFixed(1)}%  kritik ${best.crit}`);
process.exit(0);
