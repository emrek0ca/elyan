/**
 * Repro: "Son mailimi oku" gibi cümleler için connector semantik ipucu
 * skorlarını gerçek e5 modeliyle ölçer. Çalıştır:
 *   npx tsx scripts/repro-connector-hint.ts
 */
import {
  CONNECTOR_TOOL_CONTRACTS,
  connectorContractsForSemanticReadHint,
  connectorToolsForCapabilityGrants,
  selectSemanticConnectorReadToolHint,
} from "../src/modules/brain/connector-tools.js";

const PROMPTS = [
  "Son mailimi oku",
  "Bugün gelen mailler",
  "Maillerimi kontrol et",
  "Son 10 mailimi listele",
  "mailime bak",
  "gelen kutumda ne var",
];

async function main() {
  const grants = [
    {
      provider: "google",
      capabilities: ["gmail", "calendar", "drive"],
      scopes: [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
      ],
    },
  ];
  const tools = connectorToolsForCapabilityGrants(grants, () => true);
  const contracts = tools.map((entry) => entry.contract);
  console.log(
    "advertised:",
    tools.map((entry) => entry.name ?? entry.contract.slice(0, 20)),
  );
  for (const prompt of PROMPTS) {
    const hint = await selectSemanticConnectorReadToolHint(prompt, contracts);
    // inference.ts:4613'teki çağrının birebir simülasyonu — modele giden liste.
    const advertised = connectorContractsForSemanticReadHint(
      contracts,
      hint?.tool,
    );
    console.log(
      JSON.stringify({
        prompt,
        hint: hint
          ? { tool: hint.tool, score: +hint.score.toFixed(4), margin: +hint.margin.toFixed(4) }
          : null,
        advertisedToModel: advertised.map(
          (contract) => contract.trim().split(" ")[0],
        ),
      }),
    );
  }
}

main().then(
  () => process.exit(0),
  (error) => {
    console.error(error);
    process.exit(1);
  },
);
