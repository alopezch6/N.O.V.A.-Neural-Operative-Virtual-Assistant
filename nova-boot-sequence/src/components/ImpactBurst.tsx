import React from "react";
import { interpolate, spring } from "remotion";
import { C, CX, CY, F_LOAD_END, F_IMPACT_END } from "../constants";

interface ImpactBurstProps { frame: number; fps: number; }

const RAY_N = 36;

export const ImpactBurst: React.FC<ImpactBurstProps> = ({ frame, fps }) => {
  if (frame < F_LOAD_END - 2) return null;

  const since = Math.max(0, frame - F_LOAD_END);

  const burstSpring = spring({
    frame: since,
    fps,
    config: { damping: 10, mass: 0.35, stiffness: 320 },
    from: 0, to: 1,
  });
  const burstProg = Math.min(1, Math.max(0, burstSpring));

  const rayOp = interpolate(
    frame,
    [F_LOAD_END, F_LOAD_END + 12, F_LOAD_END + 50, F_IMPACT_END],
    [0, 1, 0.75, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const waves = [
    { delay: 0,  maxR: 500,  dur: 40, sw: 6,   color: C.cyan         },
    { delay: 7,  maxR: 850,  dur: 52, sw: 3.5, color: C.violetBright },
    { delay: 16, maxR: 1250, dur: 65, sw: 2,   color: C.cyan         },
    { delay: 28, maxR: 1850, dur: 82, sw: 1.5, color: C.violet       },
  ];

  const rays = Array.from({ length: RAY_N }, (_, i) => {
    const angle = (i / RAY_N) * Math.PI * 2;
    const major = i % 4 === 0;
    const med   = i % 2 === 0 && !major;
    const maxLen = major ? 650 + (i % 5) * 95 : med ? 400 + (i % 7) * 65 : 230 + (i % 3) * 55;
    const w      = major ? 3.5 : med ? 2 : 1.2;
    const len    = burstProg * maxLen;
    const x2     = CX + Math.cos(angle) * len;
    const y2     = CY + Math.sin(angle) * len;
    const colorArr = [C.cyan, C.violet, C.pink, "#ffffff", C.violetBright, C.cyan];
    const color  = colorArr[i % colorArr.length];
    return { x2, y2, color, w };
  });

  return (
    <g>
      {waves.map(({ delay, maxR, dur, sw, color }, wi) => {
        const ws = since - delay;
        if (ws < 0) return null;
        const wp = Math.min(1, ws / dur);
        const r  = wp * maxR;
        const wOp = interpolate(wp, [0, 0.12, 1], [0, 0.9, 0], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        });
        return (
          <circle key={wi} cx={CX} cy={CY} r={r}
            fill="none" stroke={color} strokeWidth={sw}
            opacity={wOp} filter="url(#bloom-c)" />
        );
      })}

      {rayOp > 0.01 && (
        <g opacity={rayOp} filter="url(#bloom-burst)">
          {rays.map(({ x2, y2, color, w }, i) => (
            <line key={i}
              x1={CX} y1={CY} x2={x2} y2={y2}
              stroke={color} strokeWidth={w}
              strokeLinecap="round" />
          ))}
        </g>
      )}
    </g>
  );
};
