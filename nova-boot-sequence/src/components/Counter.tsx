import React from "react";
import { interpolate } from "remotion";
import { C, CX, CY, F_ASSEMBLY_END, F_LOAD_END, F_IMPACT_END } from "../constants";

// Familia de fuentes se carga en BootSequence y se pasa como prop
interface CounterProps {
  frame:        number;
  fps:          number;
  orbitron:     string;
  shareTechMono: string;
}

export const Counter: React.FC<CounterProps> = ({ frame, fps, orbitron, shareTechMono }) => {
  // El contador solo es visible durante la fase de carga (4s-9s)
  const opacity = interpolate(
    frame,
    [F_ASSEMBLY_END - 10, F_ASSEMBLY_END + 30, F_LOAD_END - 10, F_LOAD_END + 30],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const loadProgress = interpolate(frame, [F_ASSEMBLY_END, F_LOAD_END], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  const pct = Math.floor(loadProgress * 100);

  // El texto "INITIALIZING NOVA..." parpadea levemente
  const blinkPhase   = Math.sin((frame / fps) * 2 * Math.PI * 1.8);
  const blinkOpacity = 0.55 + 0.15 * blinkPhase;

  // Efecto de enfoque de lente: blur disminuye conforme sube al 100%
  const blurPx = interpolate(loadProgress, [0, 1], [5, 0]);

  return (
    <div style={{
      position:  "absolute",
      top:       CY - 56,
      left:      0,
      width:     "100%",
      textAlign: "center",
      opacity,
      filter:    `blur(${blurPx}px)`,
      pointerEvents: "none",
    }}>
      {/* Contador numérico */}
      <div style={{
        fontFamily:  orbitron,
        fontSize:    90,
        fontWeight:  900,
        lineHeight:  1,
        color:       C.cyan,
        letterSpacing: 6,
        textShadow:  `0 0 30px ${C.cyan}, 0 0 80px rgba(34,211,238,0.5), 0 0 160px rgba(34,211,238,0.2)`,
      }}>
        {pct}%
      </div>

      {/* Subtexto */}
      <div style={{
        marginTop:   18,
        fontFamily:  shareTechMono,
        fontSize:    20,
        color:       C.violetBright,
        letterSpacing: 14,
        opacity:     blinkOpacity,
        textShadow:  `0 0 18px rgba(192,132,252,0.5)`,
      }}>
        INITIALIZING NOVA...
      </div>
    </div>
  );
};
