import { ArrowRight, Cable, FolderOpen, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { RobotHero } from "@/features/robot/RobotHero";
import { useUiStore } from "@/stores/ui-store";

const steps = [
  { icon: FolderOpen, title: "Select workspace", detail: "Attach a working root and let Elyan understand your operating context." },
  { icon: Sparkles, title: "Connect models", detail: "Bring in OpenAI, Google, Groq, or local lanes without clutter." },
  { icon: Cable, title: "Attach integrations", detail: "Enable Telegram, GitHub, devices, and automation targets when needed." },
];

export function OnboardingScreen() {
  const navigate = useNavigate();
  const completeOnboarding = useUiStore((state) => state.completeOnboarding);

  return (
    <div className="grid min-h-[calc(100vh-180px)] grid-cols-[1.2fr_0.9fr] gap-6">
      <Surface tone="hero" className="flex items-center justify-center px-12 py-12">
        <RobotHero
          title="Welcome to Elyan"
          subtitle="A premium AI control layer for desktop workflows, agents, models, and secure execution."
        />
      </Surface>

      <Surface tone="card" className="flex flex-col justify-between p-8">
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">First-time setup</div>
          <h2 className="font-display text-[28px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Start with a calm, guided workspace
          </h2>
          <p className="mt-3 max-w-lg text-[14px] leading-6 text-[var(--text-secondary)]">
            Elyan stays automatic by default. The first launch only needs the few decisions that materially change execution, trust, and context.
          </p>
          <div className="mt-8 space-y-3">
            {steps.map((step) => (
              <div key={step.title} className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="mb-2 flex items-center gap-3">
                  <step.icon className="h-4 w-4 text-[var(--accent-primary)]" />
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">{step.title}</div>
                </div>
                <div className="text-[12px] leading-5 text-[var(--text-secondary)]">{step.detail}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-8 flex items-center justify-between gap-3">
          <Button variant="secondary">Review advanced setup</Button>
          <Button
            variant="primary"
            onClick={() => {
              completeOnboarding();
              navigate("/home");
            }}
          >
            Enter Elyan
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </Surface>
    </div>
  );
}

