import React from "react";
import { interpolate } from "remotion";
import { C, CX, CY, R1, R2, R3, F_ASSEMBLY_END, F_LOAD_END } from "../constants";

interface EnergyArcsProps { frame: number; fps: number; }

function lightning(
  x1: number, y1: number,
  x2: number, y2: number,
  segs: number, seed: number,
): string {
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy);
  const nx = -dy / len, ny = dx / len;
  const pts: [number, number][] = [[x1, y1]];

  for (let i = 1; i < segs; i++) {
    const tt = i / segs;
    const mx = x1 + dx * tt;
    const my = y1 + dy * tt;
    const r = Math.sin(seed * (i + 1) * 127.1 + seed * 0.3) * 43758.5453;
    const d = (r - Math.floor(r) - 0.5) * len * 0.34;
    pts.push([mx + nx * d, my + ny * d]);
  }
  pts.push([x2, y2]);
  return "M" + pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L");
}

const ARC_N = 12;

export const EnergyArcs: React.FC<EnergyArcsProps> = ({ frame, fps }) => {
  if (frame < F_ASSEMBLY_END + 8 || frame > F_LOAD_END + 18) return null;

  const loadProg = interpolate(frame, [F_ASSEMBLY_END, F_LOAD_END], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  if (loadProg < 0.07) return null;

  const fadeOut = interpolate(frame, [F_LOAD_END, F_LOAD_END + 18], [1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  const tick = Math.floor(frame / 3);

  const arcs = Array.from({ length: ARC_N }, (_, i) => {
    const angle = (i / ARC_N) * Math.PI * 2 + tick * 0.42 * (i % 2 === 0 ? 1 : -1);
    const radii = [R1 * 0.80, R2 * 0.85, R3 * 0.87];
    const targetR = radii[(i + tick) % 3] + Math.sin(tick * 0.19 + i) * 32;

    const sx = CX + Math.cos(angle + 0.09) * 55;
    const sy = CY + Math.sin(angle + 0.09) * 55;
    const tx = CX + Math.cos(angle) * targetR;
    const ty = CY + Math.sin(angle) * targetR;

    const seed = i * 37.3 + tick * 11.9;
    const path = lightning(sx, sy, tx, ty, 5 + (i % 4), seed);

    const flicker = Math.abs(Math.sin(frame * 0.29 + i * 2.1));
    const op = loadProg * flicker * fadeOut * 0.6 * (0.35 + (i % 3) * 0.25);
    const colorArr = [C.cyan, C.violetBright, C.pink, C.cyan, C.violet, C.cyan];
    const color = colorArr[i % colorArr.length];
    const w = 0.7 + (i % 3) * 0.45;

    return { path, op, color, w };
  });

  return (
    <g filter="url(#bloom-arc)">
      {arcs.map(({ path, op, color, w }, i) => (
        op > 0.01 ? <path key={i} d={path} stroke={color} strokeWidth={w} fill="none" opacity={op} /> : null
      ))}
    </g>
  );
};
