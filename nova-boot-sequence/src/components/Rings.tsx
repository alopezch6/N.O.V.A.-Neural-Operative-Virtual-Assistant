import React from "react";
import { interpolate, spring } from "remotion";
import { C, CX, CY, R1, R2, R3, R4, R5, F_ASSEMBLY_END, F_LOAD_END, F_IMPACT_END } from "../constants";

interface RingsProps {
  frame: number;
  fps:   number;
}

// Copia fantasma para simular motion blur direccional
function Ghost({ cx, cy, r, angle, stroke, strokeDash, w = 1.5, alpha }: {
  cx: number; cy: number; r: number; angle: number;
  stroke: string; strokeDash?: string; w?: number; alpha: number;
}) {
  return (
    <g transform={`rotate(${angle}, ${cx}, ${cy})`}>
      <circle cx={cx} cy={cy} r={r} fill="none"
        stroke={stroke} strokeWidth={w}
        strokeDasharray={strokeDash ?? undefined}
        opacity={alpha} />
    </g>
  );
}

export const Rings: React.FC<RingsProps> = ({ frame, fps }) => {
  const C1 = 2 * Math.PI * R1;
  const C2 = 2 * Math.PI * R2;
  const C3 = 2 * Math.PI * R3;
  const C4 = 2 * Math.PI * R4;
  const C5 = 2 * Math.PI * R5;

  // ── Spring con inercia (overshoot): damping bajo = rebote visible ──────────
  const springCfg = { damping: 5, mass: 1.6, stiffness: 38 };

  const raw1 = spring({ frame: Math.max(0, frame - 30),  fps, config: springCfg, from: 0, to: 1 });
  const raw2 = spring({ frame: Math.max(0, frame - 120), fps, config: springCfg, from: 0, to: 1 });
  const raw3 = spring({ frame: Math.max(0, frame - 210), fps, config: springCfg, from: 0, to: 1 });

  const outerCfg = { damping: 9, mass: 2.2, stiffness: 28 };
  const raw4 = spring({ frame: Math.max(0, frame - 290), fps, config: outerCfg, from: 0, to: 1 });
  const raw5 = spring({ frame: Math.max(0, frame - 380), fps, config: outerCfg, from: 0, to: 1 });
  const p4   = Math.min(1, Math.max(0, raw4));
  const p5   = Math.min(1, Math.max(0, raw5));

  // Para dashoffset clampeamos [0,1]; el overshoot lo usamos solo en opacidad/escala
  const p1 = Math.min(1, Math.max(0, raw1));
  const p2 = Math.min(1, Math.max(0, raw2));
  const p3 = Math.min(1, Math.max(0, raw3));

  // Ligero overshoot en escala del anillo (escala >1 al rebotar)
  const s1 = 0.97 + 0.06 * Math.max(0, raw1 - 1);
  const s2 = 0.97 + 0.06 * Math.max(0, raw2 - 1);
  const s3 = 0.97 + 0.06 * Math.max(0, raw3 - 1);

  // ── Rotación diferencial (empieza lentamente en fase load) ─────────────────
  const rotMult = interpolate(
    frame,
    [F_ASSEMBLY_END, F_LOAD_END, F_IMPACT_END],
    [0, 0.55, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const elapsed = Math.max(0, frame - F_ASSEMBLY_END) / fps;
  const ang1 =  elapsed * 58  * rotMult;
  const ang2 = -elapsed * 42  * rotMult;
  const ang3 =  elapsed * 24  * rotMult;
  const ang4 = -elapsed * 14  * rotMult;
  const ang5 =  elapsed * 7   * rotMult;

  // ── Intensidad de motion blur según velocidad ──────────────────────────────
  const blurAmt = interpolate(rotMult, [0, 0.4, 1], [0, 0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const gs = 2.8; // grados entre copias fantasma

  return (
    <>
      {/* ── Ejes X/Y finos (aparecen primero) ─────────────────────────────── */}
      <Axes frame={frame} fps={fps} />

      {/* ══════════════════════════════════════════════════════════════════════
          RING 1 — sólido cian con marcas de grado
          ══════════════════════════════════════════════════════════════════════ */}
      {blurAmt > 0.1 && (
        <>
          <Ghost cx={CX} cy={CY} r={R1} angle={ang1 - gs * 3} stroke={C.cyan}   alpha={blurAmt * 0.06} />
          <Ghost cx={CX} cy={CY} r={R1} angle={ang1 - gs * 2} stroke={C.cyan}   alpha={blurAmt * 0.11} />
          <Ghost cx={CX} cy={CY} r={R1} angle={ang1 - gs}     stroke={C.cyan}   alpha={blurAmt * 0.18} />
        </>
      )}
      <g
        transform={`rotate(${ang1}, ${CX}, ${CY}) scale(${s1})`}
        style={{ transformOrigin: `${CX}px ${CY}px` }}
        opacity={Math.min(1, p1 * 1.2)}
      >
        <circle cx={CX} cy={CY} r={R1} fill="none" stroke={C.cyan}
          strokeWidth={1.6}
          strokeDasharray={`${C1} ${C1}`}
          strokeDashoffset={C1 * (1 - p1)}
          filter="url(#bloom-c)" />
        {/* Marcas de grado — aparecen al terminar de dibujarse */}
        {p1 > 0.82 && Array.from({ length: 36 }, (_, i) => {
          const a   = (i / 36) * 2 * Math.PI;
          const maj = i % 9 === 0;
          const rIn  = R1 - (maj ? 14 : 6);
          const rOut = R1 + (maj ? 14 : 6);
          const fade = Math.min(1, (p1 - 0.82) * 5.5);
          return (
            <line key={i}
              x1={CX + Math.cos(a) * rIn}  y1={CY + Math.sin(a) * rIn}
              x2={CX + Math.cos(a) * rOut} y2={CY + Math.sin(a) * rOut}
              stroke={C.cyan} strokeWidth={maj ? 2 : 0.8}
              opacity={fade * (maj ? 0.85 : 0.28)}
            />
          );
        })}
      </g>

      {/* ══════════════════════════════════════════════════════════════════════
          RING 2 — discontinuo violeta, rotación inversa
          ══════════════════════════════════════════════════════════════════════ */}
      {blurAmt > 0.1 && (
        <>
          <Ghost cx={CX} cy={CY} r={R2} angle={ang2 + gs * 3} stroke={C.violetBright} strokeDash="18 10" alpha={blurAmt * 0.05} />
          <Ghost cx={CX} cy={CY} r={R2} angle={ang2 + gs * 2} stroke={C.violetBright} strokeDash="18 10" alpha={blurAmt * 0.10} />
          <Ghost cx={CX} cy={CY} r={R2} angle={ang2 + gs}     stroke={C.violetBright} strokeDash="18 10" alpha={blurAmt * 0.16} />
        </>
      )}
      <g
        transform={`rotate(${ang2}, ${CX}, ${CY}) scale(${s2})`}
        style={{ transformOrigin: `${CX}px ${CY}px` }}
        opacity={Math.min(1, p2 * 1.2)}
      >
        <circle cx={CX} cy={CY} r={R2} fill="none"
          stroke={C.violetBright} strokeWidth={1.5}
          strokeDasharray="18 10"
          strokeDashoffset={-C2 * (1 - p2)}
          filter="url(#bloom-v)" />
        {/* Dash interior rosa */}
        <circle cx={CX} cy={CY} r={R2 - 13} fill="none"
          stroke={C.pink} strokeWidth={0.7}
          strokeDasharray="4 24" opacity={p2 * 0.32} />
      </g>

      {/* ══════════════════════════════════════════════════════════════════════
          RING 3 — arco gradiente, rotación lenta
          ══════════════════════════════════════════════════════════════════════ */}
      {blurAmt > 0.1 && (
        <>
          <Ghost cx={CX} cy={CY} r={R3} angle={ang3 - gs * 2} stroke={C.cyan}   alpha={blurAmt * 0.07} />
          <Ghost cx={CX} cy={CY} r={R3} angle={ang3 - gs}     stroke={C.violet} alpha={blurAmt * 0.13} />
        </>
      )}
      <g
        transform={`rotate(${ang3}, ${CX}, ${CY}) scale(${s3})`}
        style={{ transformOrigin: `${CX}px ${CY}px` }}
        opacity={Math.min(1, p3 * 1.2)}
      >
        {/* Pista de fondo */}
        <circle cx={CX} cy={CY} r={R3} fill="none"
          stroke={C.violet} strokeWidth={1.5} opacity={0.14} />
        {/* Arco gradiente (sale desde las 12h gracias al rotate -90) */}
        <g transform={`rotate(-90, ${CX}, ${CY})`}>
          <circle cx={CX} cy={CY} r={R3} fill="none"
            stroke="url(#grad-ring3-arc)" strokeWidth={3}
            strokeLinecap="round"
            strokeDasharray={`${C3} ${C3}`}
            strokeDashoffset={C3 * (1 - p3)}
            filter="url(#bloom-c)" />
        </g>
      </g>

      {/* ══════════════════════════════════════════════════════════════════════
          RING 4 — órbita exterior violet, muy tenue, rotación lenta CCW
          ══════════════════════════════════════════════════════════════════════ */}
      {p4 > 0.01 && (
        <g transform={`rotate(${ang4}, ${CX}, ${CY})`} opacity={Math.min(1, p4 * 1.1)}>
          {/* Pista base ultra-tenue */}
          <circle cx={CX} cy={CY} r={R4} fill="none"
            stroke={C.violet} strokeWidth={0.7} opacity={0.06} />
          {/* Segmentos dispersos con bloom */}
          <circle cx={CX} cy={CY} r={R4} fill="none"
            stroke={C.violetBright} strokeWidth={1}
            strokeDasharray="6 38"
            strokeDashoffset={-C4 * (1 - p4)}
            opacity={0.38}
            filter="url(#bloom-v)" />
          {/* Micro-arco brillante (30°) */}
          <g transform={`rotate(-90, ${CX}, ${CY})`}>
            <circle cx={CX} cy={CY} r={R4} fill="none"
              stroke={C.cyan} strokeWidth={2}
              strokeLinecap="round"
              strokeDasharray={`${C4 * 0.085} ${C4}`}
              opacity={0.55 * p4}
              filter="url(#bloom-c)" />
          </g>
        </g>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          RING 5 — órbita más exterior cyan, ultra-tenue, rotación CW mínima
          ══════════════════════════════════════════════════════════════════════ */}
      {p5 > 0.01 && (
        <g transform={`rotate(${ang5}, ${CX}, ${CY})`} opacity={Math.min(1, p5 * 1.0)}>
          <circle cx={CX} cy={CY} r={R5} fill="none"
            stroke={C.cyan} strokeWidth={0.6} opacity={0.05} />
          <circle cx={CX} cy={CY} r={R5} fill="none"
            stroke={C.cyan} strokeWidth={0.8}
            strokeDasharray="2 55"
            strokeDashoffset={C5 * (1 - p5)}
            opacity={0.28}
            filter="url(#bloom-c)" />
          {/* Arco corto brillante (20°) */}
          <g transform={`rotate(45, ${CX}, ${CY})`}>
            <circle cx={CX} cy={CY} r={R5} fill="none"
              stroke={C.violet} strokeWidth={1.5}
              strokeLinecap="round"
              strokeDasharray={`${C5 * 0.056} ${C5}`}
              opacity={0.45 * p5}
              filter="url(#bloom-v)" />
          </g>
        </g>
      )}
    </>
  );
};

// ── Ejes cruzados ──────────────────────────────────────────────────────────────
import { W, H } from "../constants";

const Axes: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const raw = spring({
    frame, fps,
    config: { damping: 14, mass: 0.9, stiffness: 75 },
    from: 0, to: 1,
  });
  const p = Math.min(1, Math.max(0, raw));

  return (
    <>
      <line x1={CX - (W / 2) * p} y1={CY} x2={CX + (W / 2) * p} y2={CY}
        stroke={C.cyan} strokeWidth={0.5} opacity={0.22} />
      <line x1={CX} y1={CY - (H / 2) * p} x2={CX} y2={CY + (H / 2) * p}
        stroke={C.cyan} strokeWidth={0.5} opacity={0.22} />
      {p > 0.25 && (
        <>
          <line x1={CX - 22} y1={CY} x2={CX + 22} y2={CY}
            stroke={C.cyan} strokeWidth={2} opacity={Math.min(1, (p - 0.25) * 4)} />
          <line x1={CX} y1={CY - 22} x2={CX} y2={CY + 22}
            stroke={C.cyan} strokeWidth={2} opacity={Math.min(1, (p - 0.25) * 4)} />
        </>
      )}
    </>
  );
};
