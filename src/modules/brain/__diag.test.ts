import test from "node:test";
import { validateAssistantBlockContract } from "../chat/message-blocks.js";
test("diag", () => {
  const tablo = { type: "table", columns: ["Özellik","A","B"], rows: [["Kafein","Var","Yok"]] };
  for (const policy of ["explicit_only", "forbidden", undefined] as const) {
    const r = validateAssistantBlockContract({
      blocks: [tablo as never], content: "Karşılaştırma aşağıda.",
      mode: "normalize", tablePolicy: policy,
    });
    console.log(`tablePolicy=${policy ?? "(yok)"} -> bloklar=[${r.blocks.map(b=>(b as {type?:string}).type??"?").join(",")||"yok"}]`);
  }
});
