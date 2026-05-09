import React from "react";
import { interpolate } from "remotion";
import { W, H, F_ASSEMBLY_END, F_LOAD_END } from "../constants";

interface PostFXProps {
  frame: number;
  fps:   number;
}

export const PostFX: React.FC<PostFXProps> = ({ frame, fps }) => {
  // ── Desenfoque global de lente (decrece conforme avanza la carga) ─────────
  const screenBlur = interpolate(frame, [F_ASSEMBLY_END, F_LOAD_END], [6, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <>
      {/* ── Viñeta radial ──────────────────────────────────────────────────── */}
      <div style={{
        position:       "absolute",
        inset:          0,
        background:     "radial-gradient(ellipse at center, transparent 36%, rgba(0,0,0,0.82) 100%)",
        pointerEvents:  "none",
        zIndex:         90,
      }} />

      {/* ── Scanlines horizontales (1px cada 4px) ─────────────────────────── */}
      <div style={{
        position:       "absolute",
        inset:          0,
        backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(168,85,247,0.012) 3px, rgba(168,85,247,0.012) 4px)",
        pointerEvents:  "none",
        zIndex:         91,
      }} />

      {/* ── Film Grain animado (seed cambia cada frame) ───────────────────── */}
      <div style={{
        position:       "absolute",
        inset:          0,
        pointerEvents:  "none",
        zIndex:         92,
        mixBlendMode:   "overlay",
        opacity:        0.038,
      }}>
        <svg width={W} height={H}>
          <filter id={`grain-f`}>
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.78"
              numOctaves="4"
              seed={frame % 220}
              stitchTiles="stitch"
            />
            <feColorMatrix type="saturate" values="0" />
          </filter>
          <rect width={W} height={H} filter="url(#grain-f)" />
        </svg>
      </div>

      {/* ── Aberración cromática periférica (persistente, leve) ──────────── */}
      <div style={{
        position:       "absolute",
        inset:          0,
        background:     "radial-gradient(ellipse at 0% 50%, rgba(168,85,247,0.04) 0%, transparent 55%), radial-gradient(ellipse at 100% 50%, rgba(34,211,238,0.04) 0%, transparent 55%)",
        pointerEvents:  "none",
        zIndex:         93,
      }} />

      {/* ── Desenfoque de lente (solo durante carga) ─────────────────────── */}
      {screenBlur > 0.3 && (
        <div style={{
          position:       "absolute",
          inset:          0,
          backdropFilter: `blur(${screenBlur}px)`,
          WebkitBackdropFilter: `blur(${screenBlur}px)`,
          pointerEvents:  "none",
          zIndex:         89,
        }} />
      )}

      {/* ── Línea de scan animada (sweeps hacia abajo) ────────────────────── */}
      <ScanLine frame={frame} fps={fps} />

      {/* ── Esquinas HUD ──────────────────────────────────────────────────── */}
      <CornerBrackets />
    </>
  );
};

// Línea de scan diagonal
const ScanLine: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const cycle = 9; // segundos por ciclo
  const t  = (frame / fps) % cycle;
  const yp = t / cycle; // 0→1
  const y  = yp * H;
  const op = interpolate(yp, [0, 0.05, 0.95, 1], [0, 0.35, 0.35, 0]);

  return (
    <div style={{
      position:   "absolute",
      left:        0,
      right:       0,
      top:         y,
      height:      1,
      background:  "linear-gradient(90deg, transparent, rgba(168,85,247,0.4), rgba(34,211,238,0.6), rgba(168,85,247,0.4), transparent)",
      boxShadow:   "0 0 20px rgba(34,211,238,0.5)",
      opacity:     op,
      pointerEvents: "none",
      zIndex:      94,
    }} />
  );
};

// Esquinas estilo HUD
const CornerBrackets: React.FC = () => {
  const color = "rgba(168,85,247,0.45)";
  const s = 65;
  const corners: React.CSSProperties[] = [
    { top: 30, left:  30, borderTop: `2.5px solid ${color}`, borderLeft:   `2.5px solid ${color}` },
    { top: 30, right: 30, borderTop: `2.5px solid ${color}`, borderRight:  `2.5px solid ${color}` },
    { bottom: 30, left:  30, borderBottom: `2.5px solid ${color}`, borderLeft:  `2.5px solid ${color}` },
    { bottom: 30, right: 30, borderBottom: `2.5px solid ${color}`, borderRight: `2.5px solid ${color}` },
  ];
  return (
    <>
      {corners.map((st, i) => (
        <div key={i} style={{
          position:      "absolute",
          width:         s,
          height:        s,
          pointerEvents: "none",
          zIndex:        95,
          ...st,
        }} />
      ))}
    </>
  );
};
