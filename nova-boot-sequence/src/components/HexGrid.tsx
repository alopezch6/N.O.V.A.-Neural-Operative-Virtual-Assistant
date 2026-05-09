import React from "react";
import { interpolate } from "remotion";
import { C, CX, CY, W, H, F_IMPACT_END } from "../constants";

interface HexGridProps { frame: number; fps: number; }

function hexPath(cx: number, cy: number, r: number): string {
  const pts = Array.from({ length: 6 }, (_, i) => {
    const a = (i * Math.PI) / 3 - Math.PI / 6;
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
  });
  return `M${pts.join("L")}Z`;
}

export const HexGrid: React.FC<HexGridProps> = ({ frame, fps }) => {
  if (frame < F_IMPACT_END - 8) return null;

  const t = frame / fps;
  const fadeIn = interpolate(frame, [F_IMPACT_END, F_IMPACT_END + 140], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  if (fadeIn < 0.01) return null;

  const hexR  = 70;
  const hexW  = hexR * Math.sqrt(3);
  const hexH  = hexR * 2;
  const cols  = Math.ceil(W / hexW) + 2;
  const rows  = Math.ceil(H / (hexH * 0.75)) + 2;
  const maxD  = Math.sqrt(W ** 2 + H ** 2) / 2;
  const revD  = fadeIn * maxD * 1.35;

  const staticSegs: string[] = [];
  const pulseHexes: { path: string; op: number }[] = [];

  for (let row = -1; row < rows; row++) {
    for (let col = -1; col < cols; col++) {
      const cx = col * hexW + (row % 2) * (hexW / 2);
      const cy = row * hexH * 0.75;
      const dist = Math.sqrt((cx - CX) ** 2 + (cy - CY) ** 2);
      if (dist > revD) continue;

      const seed = Math.abs((col * 31 + row * 17) % 100);
      const path = hexPath(cx, cy, hexR - 1.5);

      if (seed < 10) {
        const freq = 0.18 + seed * 0.028;
        const op   = 0.055 + 0.11 * Math.abs(Math.sin(t * freq * Math.PI * 2 + seed));
        pulseHexes.push({ path, op });
      } else {
        staticSegs.push(path);
      }
    }
  }

  return (
    <g>
      <path
        d={staticSegs.join(" ")}
        fill="none"
        stroke={C.violet}
        strokeWidth={0.5}
        opacity={0.022 * fadeIn}
      />
      {pulseHexes.map(({ path, op }, i) => (
        <path key={i} d={path}
          fill="none" stroke={C.cyan} strokeWidth={0.8}
          opacity={op * fadeIn}
          filter="url(#bloom-particle)"
        />
      ))}
    </g>
  );
};
