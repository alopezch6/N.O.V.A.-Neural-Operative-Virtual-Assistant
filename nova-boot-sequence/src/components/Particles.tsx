import React from "react";
import { interpolate } from "remotion";
import { C, CX, CY, F_ASSEMBLY_END, F_LOAD_END, F_IMPACT_END } from "../constants";

interface ParticlesProps { frame: number; fps: number; }

const N = 90;

function h(n: number): number {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

export const Particles: React.FC<ParticlesProps> = ({ frame, fps }) => {
  if (frame < F_ASSEMBLY_END - 25) return null;

  const t = frame / fps;

  const loadProg = interpolate(frame, [F_ASSEMBLY_END, F_LOAD_END], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const fadeIn = interpolate(frame, [F_ASSEMBLY_END - 25, F_ASSEMBLY_END + 50], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const operFade = interpolate(frame, [F_IMPACT_END, F_IMPACT_END + 90], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  const colors = [C.cyan, C.violet, C.violetBright, C.pink, "#ffffff", C.cyan];

  const pts = Array.from({ length: N }, (_, i) => {
    const h1 = h(i * 7.31);
    const h2 = h(i * 13.71 + 42.3);
    const h3 = h(i * 5.13 + 87.1);
    const h4 = h(i * 17.97 + 23.7);
    const h5 = h(i * 3.33 + 61.9);
    const h6 = h(i * 11.11 + 5.5);

    const baseAngle = h1 * Math.PI * 2;
    const angSpeed  = (0.22 + h3 * 0.65) * (h4 > 0.5 ? 1 : -1);
    const baseR     = 85 + h2 * 340;
    const sz        = 1.3 + h5 * 3.0;
    const color     = colors[Math.floor(h6 * colors.length)];

    if (frame <= F_LOAD_END) {
      const angle = baseAngle + t * angSpeed;
      const r = baseR * (0.22 + loadProg * 0.78);
      const x = CX + Math.cos(angle) * r;
      const y = CY + Math.sin(angle) * r;
      const flicker = 0.3 + 0.7 * Math.abs(Math.sin(t * (2.2 + h3 * 5.5) + i * 0.73));
      const op = fadeIn * loadProg * flicker * 0.7;
      return { x, y, sz, color, op };
    }

    if (frame <= F_IMPACT_END + 35) {
      const dt = (frame - F_LOAD_END) / fps;
      const speed = 170 + h2 * 440;
      const eAngle = baseAngle + (h3 - 0.5) * 0.65;
      const x = CX + Math.cos(eAngle) * (baseR * 0.18 + dt * speed);
      const y = CY + Math.sin(eAngle) * (baseR * 0.18 + dt * speed);
      const op = interpolate(frame, [F_LOAD_END, F_LOAD_END + 55, F_IMPACT_END + 35], [1, 0.55, 0], {
        extrapolateLeft: "clamp", extrapolateRight: "clamp",
      });
      return { x, y, sz: sz * 1.1, color, op };
    }

    // Operational: ambient dust
    const ambAngle = baseAngle + t * angSpeed * 0.22;
    const ambR = 150 + h2 * 520;
    const x = CX + Math.cos(ambAngle) * ambR;
    const y = CY + Math.sin(ambAngle) * ambR;
    const flicker = 0.2 + 0.8 * Math.abs(Math.sin(t * (0.9 + h3 * 2.8) + i * 0.85));
    const op = operFade * 0.2 * flicker;
    return { x, y, sz: sz * 0.65, color, op };
  });

  return (
    <g filter="url(#bloom-particle)">
      {pts.map(({ x, y, sz, color, op }, i) =>
        op > 0.006 ? (
          <circle key={i} cx={x} cy={y} r={sz} fill={color} opacity={op} />
        ) : null
      )}
    </g>
  );
};
