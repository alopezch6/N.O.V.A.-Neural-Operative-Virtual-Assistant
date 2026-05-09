import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont as loadOrbitron     } from "@remotion/google-fonts/Orbitron";
import { loadFont as loadShareTechMono } from "@remotion/google-fonts/ShareTechMono";

import { C } from "./constants";
import { ThreeScene  } from "./three/ThreeScene";
import { Aurora      } from "./components/Aurora";
import { HexScroll   } from "./components/HexScroll";
import { Counter     } from "./components/Counter";
import { NovaLogo    } from "./components/NovaLogo";
import { SidePanels  } from "./components/SidePanels";
import { PostFX      } from "./components/PostFX";

// Carga de fuentes (se llama en módulo-raíz, Remotion espera a que estén listas)
const { fontFamily: orbitron      } = loadOrbitron("normal",      { weights: ["400", "700", "900"] });
const { fontFamily: shareTechMono } = loadShareTechMono("normal", { weights: ["400"] });

// ── Shimmer keyframe (para el logo NOVA) ──────────────────────────────────────
const shimmerStyle = `
  @keyframes shimmer {
    0%   { background-position: 0%   center; }
    100% { background-position: 200% center; }
  }
`;

export const BootSequence: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ background: C.bg, overflow: "hidden", fontFamily: shareTechMono }}>

      {/* ── Keyframes inyectados ───────────────────────────────────────────── */}
      <style>{shimmerStyle}</style>

      {/* ── Aurora atmosférica (detrás del canvas WebGL) ─────────────────── */}
      <Aurora frame={frame} fps={fps} />

      {/* ── Escena Three.js / WebGL ───────────────────────────────────────── */}
      <ThreeScene frame={frame} fps={fps} />

      {/* ── Hex scroll en bordes (fase aceleración 3-5.5s) ───────────────── */}
      <HexScroll frame={frame} fps={fps} />

      {/* ── Overlays HTML ─────────────────────────────────────────────────── */}
      <Counter
        frame={frame} fps={fps}
        orbitron={orbitron} shareTechMono={shareTechMono}
      />

      {/* ── Logo NOVA con aberración cromática (desde el impacto) ─────────── */}
      <NovaLogo frame={frame} fps={fps} orbitron={orbitron} />

      {/* ── Paneles laterales (fase operativa, 10s-20s) ───────────────────── */}
      <SidePanels
        frame={frame} fps={fps}
        orbitron={orbitron} shareTechMono={shareTechMono}
      />

      {/* ════════════════════════════════════════════════════════════════════
          POST-FX (encima de todo)
          ════════════════════════════════════════════════════════════════════ */}
      <PostFX frame={frame} fps={fps} />

    </AbsoluteFill>
  );
};
