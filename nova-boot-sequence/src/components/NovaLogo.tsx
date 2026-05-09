import React from "react";
import { interpolate, spring } from "remotion";
import { C, CX, CY, F_LOAD_END, F_IMPACT_END } from "../constants";

interface LogoProps {
  frame:    number;
  fps:      number;
  orbitron: string;
}

export const NovaLogo: React.FC<LogoProps> = ({ frame, fps, orbitron }) => {
  if (frame < F_LOAD_END) return null;

  // Aparición con spring
  const logoSpring = spring({
    frame: Math.max(0, frame - F_LOAD_END - 15),
    fps,
    config: { damping: 14, mass: 1.1, stiffness: 55 },
    from: 0, to: 1,
  });

  const logoOpacity = Math.min(1, logoSpring * 1.2);

  // Aberración cromática (split RGB): mayor al inicio del impacto, desaparece al terminar
  const impProg = interpolate(frame, [F_LOAD_END, F_IMPACT_END], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const rgbSplit = interpolate(impProg, [0, 0.35, 1], [18, 2, 0]);

  // Escala del logo
  const scaleSpring = spring({
    frame: Math.max(0, frame - F_LOAD_END),
    fps,
    config: { damping: 8, mass: 1.5, stiffness: 45 },
    from: 0.3, to: 1,
  });

  const centerX = CX;
  const topY    = CY - 160;

  const baseStyle: React.CSSProperties = {
    position:      "absolute",
    fontFamily:    orbitron,
    fontSize:      112,
    fontWeight:    900,
    letterSpacing: 28,
    whiteSpace:    "nowrap",
    transform:     `translateX(-50%) scale(${scaleSpring})`,
    transformOrigin: "center center",
    left:          centerX,
    top:           topY,
    userSelect:    "none",
    pointerEvents: "none",
  };

  return (
    <div style={{ opacity: logoOpacity }}>
      {/* ── Capa Roja (offset izquierda) ────────────────────────────────── */}
      <div style={{
        ...baseStyle,
        color: `rgba(255, 40, 40, 0.55)`,
        transform: `translateX(calc(-50% - ${rgbSplit}px)) scale(${scaleSpring})`,
        filter: `blur(${rgbSplit * 0.3}px)`,
      }}>
        NOVA
      </div>

      {/* ── Capa Azul (offset derecha) ──────────────────────────────────── */}
      <div style={{
        ...baseStyle,
        color: `rgba(40, 100, 255, 0.55)`,
        transform: `translateX(calc(-50% + ${rgbSplit}px)) scale(${scaleSpring})`,
        filter: `blur(${rgbSplit * 0.3}px)`,
      }}>
        NOVA
      </div>

      {/* ── Logo principal con gradiente ───────────────────────────────── */}
      <div style={{
        ...baseStyle,
        background: `linear-gradient(90deg, ${C.violet}, ${C.cyan}, ${C.pink}, ${C.violet})`,
        backgroundSize: "200%",
        WebkitBackgroundClip: "text",
        WebkitTextFillColor: "transparent",
        backgroundClip: "text",
        filter: `drop-shadow(0 0 35px rgba(168,85,247,1)) drop-shadow(0 0 90px rgba(168,85,247,0.45))`,
        animation: "shimmer 4s linear infinite",
      }}>
        NOVA
      </div>

      {/* ── Subtítulo ───────────────────────────────────────────────────── */}
      <div style={{
        position:      "absolute",
        left:          centerX,
        top:           topY + 120,
        transform:     "translateX(-50%)",
        fontFamily:    "Share Tech Mono, monospace",
        fontSize:      14,
        letterSpacing: 10,
        color:         `rgba(34,211,238,0.6)`,
        whiteSpace:    "nowrap",
        opacity:       interpolate(impProg, [0, 0.3], [0, 1], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp",
        }),
        textShadow: `0 0 20px rgba(34,211,238,0.4)`,
      }}>
        NEURAL OPERATIVE VIRTUAL ASSISTANT
      </div>
    </div>
  );
};
