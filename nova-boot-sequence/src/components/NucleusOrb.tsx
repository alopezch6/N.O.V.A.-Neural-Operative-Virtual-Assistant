import React from "react";
import { interpolate } from "remotion";
import { C, CX, CY, CORE, F_ASSEMBLY_END, F_LOAD_END, F_IMPACT_END } from "../constants";

interface OrbProps {
  frame: number;
  fps:   number;
}

export const NucleusOrb: React.FC<OrbProps> = ({ frame, fps }) => {
  const t = frame / fps;

  // ── Resplandor exponencial durante la carga (4s→9s) ───────────────────────
  const loadProgress = interpolate(frame, [F_ASSEMBLY_END, F_LOAD_END], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const glowStrength = Math.pow(loadProgress, 1.8) * 65 + 4;

  // ── Vibración del orbe durante carga (amplitud y frecuencia aumentan) ──────
  const vibAmp  = loadProgress * 9;
  const vibFreq = 7 + loadProgress * 18;
  const vx = vibAmp * Math.sin(t * vibFreq * 2 * Math.PI);
  const vy = vibAmp * 0.35 * Math.cos(t * vibFreq * 2 * Math.PI * 1.4);

  // ── Respiración sinusoidal en fase operativa (10s+) ───────────────────────
  const breathPhase   = t * 2 * Math.PI * 0.45;
  const breathScale   = 0.93 + 0.07 * Math.sin(breathPhase);
  const breathOpacity = 0.72 + 0.28 * Math.sin(breathPhase);

  // ── Factor combinado de escala ─────────────────────────────────────────────
  const isOperational = frame >= F_IMPACT_END;
  const scale = isOperational ? breathScale : 1.0;
  const coreOpacity = isOperational ? breathOpacity : 1.0;

  // ── Orbe más brillante durante el impacto ─────────────────────────────────
  const impactBoost = interpolate(frame, [F_LOAD_END, F_LOAD_END + 20, F_IMPACT_END], [0, 1.5, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  const r = CORE * scale;

  return (
    <g transform={`translate(${CX + vx}, ${CY + vy})`} opacity={coreOpacity}>
      {/* ── Aura exterior (gradiente radial amplio) ────────────────────────── */}
      <circle cx={0} cy={0} r={r * 3.2 + glowStrength * 0.4}
        fill="url(#grad-orb)" />

      {/* ── Halo externo bloom (se intensifica con la carga) ──────────────── */}
      <circle cx={0} cy={0} r={r * 1.9}
        fill="none" stroke={C.cyan} strokeWidth={1}
        opacity={0.12 + loadProgress * 0.25}
        filter="url(#bloom-c)" />

      {/* ── Borde principal del núcleo ────────────────────────────────────── */}
      <circle cx={0} cy={0} r={r}
        fill={C.bg} stroke={C.cyan} strokeWidth={2}
        filter="url(#bloom-core)"
        opacity={1 + impactBoost * 0.5} />

      {/* ── Relleno interior semitransparente ────────────────────────────── */}
      <circle cx={0} cy={0} r={r * 0.58}
        fill={C.cyan}
        opacity={0.09 + loadProgress * 0.14 + impactBoost * 0.3} />

      {/* ── Punto central ────────────────────────────────────────────────── */}
      <circle cx={0} cy={0} r={9 + impactBoost * 4}
        fill={C.cyan}
        filter="url(#bloom-core)"
        opacity={0.9 + impactBoost * 0.5} />

      {/* ── Extensiones horizontales ──────────────────────────────────────── */}
      <line x1={-CORE - 8} y1={0} x2={-CORE - 70} y2={0}
        stroke={C.cyan} strokeWidth={1} opacity={0.22} />
      <line x1={ CORE + 8} y1={0} x2={ CORE + 70} y2={0}
        stroke={C.cyan} strokeWidth={1} opacity={0.22} />
      <line x1={-CORE - 40} y1={-8} x2={-CORE - 40} y2={8}
        stroke={C.cyan} strokeWidth={1} opacity={0.18} />
      <line x1={ CORE + 40} y1={-8} x2={ CORE + 40} y2={8}
        stroke={C.cyan} strokeWidth={1} opacity={0.18} />

      {/* ── Pétalos de carga (arc-reactor style, 12 marcas a r=132) ──────── */}
      {loadProgress > 0.01 && Array.from({ length: 12 }, (_, i) => {
        const angle     = (i / 12) * Math.PI * 2;
        const threshold = i / 12;
        const petalProg = Math.max(0, Math.min(1, (loadProgress - threshold) * 12));
        const rp        = 132;
        const x1 = Math.cos(angle - 0.08) * rp;
        const y1 = Math.sin(angle - 0.08) * rp;
        const x2 = Math.cos(angle + 0.08) * rp;
        const y2 = Math.sin(angle + 0.08) * rp;
        const major = i % 3 === 0;
        return (
          <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
            stroke={major ? C.cyan : C.violetBright}
            strokeWidth={major ? 3.5 : 2}
            opacity={petalProg * (major ? 1 : 0.75)}
            filter="url(#bloom-v)"
            strokeLinecap="round" />
        );
      })}

      {/* ── Anillo de carga secundario (se llena con loadProgress) ────────── */}
      {loadProgress > 0.05 && (
        <circle cx={0} cy={0} r={108}
          fill="none" stroke={C.violetBright} strokeWidth={1.2}
          strokeDasharray={`${2 * Math.PI * 108 * loadProgress} ${2 * Math.PI * 108}`}
          strokeDashoffset={2 * Math.PI * 108 * 0.25}
          opacity={loadProgress * 0.55}
          filter="url(#bloom-v)"
          strokeLinecap="round" />
      )}
    </g>
  );
};
