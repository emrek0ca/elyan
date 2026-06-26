import React from "react";
import {DepthBackground} from "../components/DepthBackground";
import {GlassCard} from "../components/GlassCard";
import {MotionTitle} from "../components/MotionTitle";
import {SignalPulse} from "../components/SignalPulse";
import {palette} from "../lib/palette";

export const Scene4Desktop: React.FC = () => {
  return (
    <>
      <DepthBackground mode="light" />
      <MotionTitle text="One focused surface." y={188} size={60} color={palette.ink} align="left" width={620} />
      <GlassCard width={860} height={1080} x={110} y={420} padding={42} radius={48}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif',
            color: palette.shadow,
          }}
        >
          <div style={{fontSize: 23, fontWeight: 430, opacity: 0.5}}>Elyan Desktop</div>
          <div style={{fontSize: 19, fontWeight: 410, opacity: 0.34}}>Executing</div>
        </div>
        <div
          style={{
            marginTop: 42,
            height: 184,
            borderRadius: 28,
            background: "rgba(255,255,255,0.76)",
            border: `1px solid ${palette.line}`,
            padding: 30,
          }}
        >
          <div
            style={{
              fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif',
              fontSize: 36,
              fontWeight: 500,
              letterSpacing: -1.6,
              color: palette.ink,
            }}
          >
            Research the file.
          </div>
          <div style={{marginTop: 18, fontSize: 23, fontWeight: 400, color: "rgba(7,16,21,0.5)"}}>
            One task. One route. One verified result.
          </div>
        </div>
        <div style={{display: "flex", gap: 24, marginTop: 28}}>
          <div
            style={{
              width: 284,
              height: 220,
              borderRadius: 30,
              background: "rgba(255,255,255,0.72)",
              border: `1px solid ${palette.line}`,
              padding: 28,
            }}
          >
            <div style={{fontSize: 20, fontWeight: 410, opacity: 0.4}}>File</div>
            <div
              style={{
                fontSize: 31,
                marginTop: 18,
                fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif',
                fontWeight: 480,
                letterSpacing: -1.2,
              }}
            >
              brief.pdf
            </div>
          </div>
          <div
            style={{
              width: 470,
              height: 220,
              borderRadius: 30,
              background: "rgba(255,255,255,0.72)",
              border: `1px solid ${palette.line}`,
              padding: 28,
            }}
          >
            <div style={{fontSize: 20, fontWeight: 410, opacity: 0.4}}>Action</div>
            <div
              style={{
                fontSize: 31,
                marginTop: 18,
                lineHeight: 1.1,
                fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif',
                fontWeight: 480,
                letterSpacing: -1.3,
                width: 300,
              }}
            >
              Analyze. Summarize. Ship.
            </div>
          </div>
        </div>
        <div
          style={{
            marginTop: 28,
            height: 360,
            borderRadius: 36,
            background: "linear-gradient(180deg, rgba(255,255,255,0.76) 0%, rgba(240,247,247,0.86) 100%)",
            border: `1px solid ${palette.line}`,
            position: "relative",
            padding: 30,
          }}
        >
          <div style={{fontSize: 20, fontWeight: 410, opacity: 0.4}}>Result</div>
          <div
            style={{
              marginTop: 22,
              fontSize: 38,
              lineHeight: 1.12,
              fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif',
              fontWeight: 490,
              letterSpacing: -1.8,
              width: 540,
            }}
          >
            Clear output with room to breathe.
          </div>
          <div style={{marginTop: 24, fontSize: 24, fontWeight: 400, lineHeight: 1.34, color: "rgba(7,16,21,0.48)", width: 600}}>
            Elyan keeps the system calm while the work moves forward.
          </div>
          <SignalPulse x={682} y={256} size={24} />
        </div>
      </GlassCard>
    </>
  );
};
