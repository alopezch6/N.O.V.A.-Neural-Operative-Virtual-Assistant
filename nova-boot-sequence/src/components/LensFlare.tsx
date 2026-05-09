import React from "react";
import { interpolate, spring } from "remotion";
import { C, CX, CY, W, H, F_LOAD_END, F_IMPACT_END } from "../constants";

interface LensFlareProps {
  frame: number;
  fps:   number;
}

export const LensFlare: React.FC<LensFlareProps> = ({ frame, fps }) => {
  if (frame < F_LOAD_END - 5) return null;

  // Progreso del impacto 0→1 durante la ventana 9s-10s
  const impProg = interpolate(frame, [F_LOAD_END, F_IMPACT_END], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  // Pulso inicial muy rápido (0→1 en los primeros 0.2s del impacto)
  const flashSpring = spring({
    frame: Math.max(0, frame - F_LOAD_END),
    fps,
    config: { damping: 10, mass: 0.6, stiffness: 120 },
    from: 0, to: 1,
  });
  const flashRadius = interpolate(flashSpring, [0, 1], [0, Math.hypot(W, H) * 0.9], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const flashOpacity = interpolate(impProg, [0, 0.12, 0.6, 1], [0, 1, 0.15, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  // Anillos secundarios (halo de lente)
  const haloRings = [
    { delay: 5,  maxR: 280, strokeW: 3, color: C.cyan,         opBase: 0.85 },
    { delay: 12, maxR: 450, strokeW: 2, color: C.violetBright, opBase: 0.65 },
    { delay: 20, maxR: 700, strokeW: 1.5, color: C.pink,       opBase: 0.45 },
    { delay: 35, maxR: 1100, strokeW: 1, color: C.violet,      opBase: 0.30 },
  ];

  // Destellos en forma de estrella (lens streaks)
  const streakLen = interpolate(impProg, [0, 0.3, 1], [0, 800, 400]);
  const streakOp  = interpolate(impProg, [0, 0.1, 0.5, 1], [0, 0.9, 0.5, 0]);

  return (
    <>
      {/* ── Flash central radial ───────────────────────────────────────────── */}
      <circle cx={CX} cy={CY} r={flashRadius}
        fill="url(#grad-flash)"
        opacity={flashOpacity}
        filter="url(#bloom-flash)"
        style={{ mixBlendMode: "overlay" as const }}
      />

      {/* ── Anillos de halo ────────────────────────────────────────────────── */}
      {haloRings.map(({ delay, maxR, strokeW, color, opBase }, i) => {
        const rProg = spring({
          frame: Math.max(0, frame - F_LOAD_END - delay),
          fps,
          config: { damping: 12, mass: 0.8, stiffness: 80 },
          from: 0, to: 1,
        });
        const r  = rProg * maxR;
        const op = interpolate(rProg, [0, 0.2, 0.7, 1], [0, opBase, opBase * 0.5, 0], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        });
        return (
          <circle key={i} cx={CX} cy={CY} r={r}
            fill="none" stroke={color} strokeWidth={strokeW}
            opacity={op} filter="url(#bloom-c)"
            style={{ mixBlendMode: "screen" as const }}
          />
        );
      })}

      {/* ── Destellos en estrella (8 rayos) ────────────────────────────────── */}
      {Array.from({ length: 8 }, (_, i) => {
        const angle = (i / 8) * Math.PI * 2 + Math.PI / 8;
        const x2 = CX + Math.cos(angle) * streakLen;
        const y2 = CY + Math.sin(angle) * streakLen;
        return (
          <line key={i}
            x1={CX} y1={CY} x2={x2} y2={y2}
            stroke={i % 2 === 0 ? C.white : C.cyan}
            strokeWidth={i % 4 === 0 ? 2 : 1}
            opacity={streakOp * (i % 2 === 0 ? 0.9 : 0.6)}
            strokeLinecap="round"
            filter="url(#bloom-flash)"
            style={{ mixBlendMode: "screen" as const }}
          />
        );
      })}

      {/* ── Hexágono de iris (apertura de lente) ───────────────────────────── */}
      <IrisHexagon frame={frame} fps={fps} impProg={impProg} />
    </>
  );
};

// Hexágono de apertura de lente
const IrisHexagon: React.FC<{ frame: number; fps: number; impProg: number }> = ({
  frame, fps, impProg,
}) => {
  const sizeSpring = spring({
    frame: Math.max(0, frame - F_LOAD_END - 8),
    fps,
    config: { damping: 14, mass: 1, stiffness: 60 },
    from: 0, to: 1,
  });
  const size = sizeSpring * 180;
  const opacity = interpolate(impProg, [0, 0.05, 0.55, 1], [0, 0.7, 0.3, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const rot = impProg * 30; // ligera rotación

  const hex = Array.from({ length: 6 }, (_, i) => {
    const a = (i / 6) * Math.PI * 2 - Math.PI / 6 + (rot * Math.PI / 180);
    return [CX + Math.cos(a) * size, CY + Math.sin(a) * size];
  });
  const pts = hex.map(([x, y]) => `${x},${y}`).join(" ");

  return (
    <polygon points={pts}
      fill="none" stroke={C.cyan} strokeWidth={1.5}
      opacity={opacity}
      style={{ mixBlendMode: "screen" as const }}
    />
  );
};
