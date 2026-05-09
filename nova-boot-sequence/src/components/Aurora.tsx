import React from "react";
import { interpolate } from "remotion";
import { F_ASSEMBLY_END, F_LOAD_END, F_IMPACT_END } from "../constants";

interface AuroraProps { frame: number; fps: number; }

export const Aurora: React.FC<AuroraProps> = ({ frame, fps }) => {
  const t = frame / fps;

  const loadProg = interpolate(frame, [F_ASSEMBLY_END, F_LOAD_END], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const operFade = interpolate(frame, [F_IMPACT_END, F_IMPACT_END + 120], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  const base = 0.016 + loadProg * 0.045 + operFade * 0.018;

  const x1 = 27 + Math.sin(t * 0.19) * 8;
  const y1 = 21 + Math.cos(t * 0.14) * 7;
  const x2 = 73 + Math.cos(t * 0.23) * 7;
  const y2 = 79 + Math.sin(t * 0.18) * 6;
  const x3 = 50 + Math.sin(t * 0.33) * 5;
  const y3 = 48 + Math.cos(t * 0.28) * 4;
  const x4 = 14 + Math.cos(t * 0.15) * 6;
  const y4 = 67 + Math.sin(t * 0.21) * 7;
  const x5 = 88 + Math.sin(t * 0.12) * 5;
  const y5 = 28 + Math.cos(t * 0.16) * 6;

  const p1 = 0.55 + 0.45 * Math.sin(t * 0.53);
  const p2 = 0.65 + 0.35 * Math.sin(t * 0.41 + 1.2);
  const p3 = 0.50 + 0.50 * Math.sin(t * 0.67 + 2.4);
  const p4 = 0.70 + 0.30 * Math.sin(t * 0.38 + 0.8);
  const p5 = 0.60 + 0.40 * Math.sin(t * 0.59 + 3.1);

  const f = (v: number) => v.toFixed(4);

  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 1 }}>
      <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(ellipse 60% 44% at ${x1}% ${y1}%, rgba(168,85,247,${f(base * p1)}) 0%, transparent 72%)`,
      }} />
      <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(ellipse 54% 50% at ${x2}% ${y2}%, rgba(34,211,238,${f(base * 0.8 * p2)}) 0%, transparent 72%)`,
      }} />
      <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(ellipse 34% 34% at ${x3}% ${y3}%, rgba(168,85,247,${f(base * 0.55 * p3)}) 0%, transparent 62%)`,
      }} />
      <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(ellipse 38% 32% at ${x4}% ${y4}%, rgba(232,121,249,${f(base * 0.4 * p4)}) 0%, transparent 66%)`,
      }} />
      <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(ellipse 36% 38% at ${x5}% ${y5}%, rgba(34,211,238,${f(base * 0.45 * p5)}) 0%, transparent 66%)`,
      }} />
      <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(ellipse 68% 52% at 50% 50%, rgba(168,85,247,${f(base * 0.28)}) 0%, transparent 62%)`,
      }} />
    </div>
  );
};
