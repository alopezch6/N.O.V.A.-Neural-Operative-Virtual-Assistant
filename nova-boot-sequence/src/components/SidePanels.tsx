import React from "react";
import { interpolate } from "remotion";
import { C, F_IMPACT_BRIEF, pseudoHex } from "../constants";

interface SidePanelsProps {
  frame:         number;
  fps:           number;
  shareTechMono: string;
  orbitron:      string;
}

// ── Panel izquierdo ──────────────────────────────────────────────────────────
const LeftPanel: React.FC<SidePanelsProps> = ({ frame, fps, shareTechMono, orbitron }) => {
  const t = frame / fps;

  const opacity = interpolate(frame, [F_IMPACT_BRIEF, F_IMPACT_BRIEF + 45], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  // ── Datos del sistema (se actualizan cada 0.5s = ~82 frames) ──────────────
  const updateCycle = Math.floor(frame / 82);
  const cpuLoad  = (35 + Math.abs(Math.sin(t * 0.7 + updateCycle) * 58)).toFixed(1);
  const coreTemp = (52 + Math.abs(Math.sin(t * 0.4 + updateCycle * 0.7) * 31)).toFixed(1);
  const encKey   = `${pseudoHex(updateCycle * 3 + 1, frame)}${pseudoHex(updateCycle * 3 + 2, frame)}`;

  // Coordenadas LAT/LONG (Zaragoza + drift)
  const lat = (41.6561 + Math.sin(t * 0.08) * 0.0012).toFixed(6);
  const lon = (-0.8773 + Math.cos(t * 0.12) * 0.0008).toFixed(6);

  // Histograma de energía (20 barras animadas)
  const bars = Array.from({ length: 20 }, (_, i) => {
    const v = 0.15 + 0.85 * Math.abs(Math.sin(t * (1.4 + i * 0.28) + i * 0.9));
    return v;
  });

  // Cascada hex (ENCRYPT stream)
  const hexLines = Array.from({ length: 10 }, (_, i) => {
    const seed = i * 31 + Math.floor(frame / 4);
    return `${pseudoHex(seed, frame)} ${pseudoHex(seed + 7, frame)} ${pseudoHex(seed + 13, frame)}`;
  });

  return (
    <div style={{
      position:   "absolute",
      left:        60,
      top:         "50%",
      transform:  "translateY(-50%)",
      width:       540,
      opacity,
      fontFamily:  shareTechMono,
      color:      `rgba(168,85,247,0.7)`,
      pointerEvents: "none",
    }}>
      {/* ── Título ──────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <div style={{ width: 3, height: 24, background: C.cyan, boxShadow: `0 0 10px ${C.cyan}` }} />
        <span style={{ fontSize: 11, letterSpacing: 5, color: C.cyan, opacity: 0.55 }}>ENERGY GRID</span>
      </div>

      {/* ── Histograma ──────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 80, marginBottom: 20 }}>
        {bars.map((v, i) => (
          <div key={i} style={{
            flex: 1,
            height: `${v * 100}%`,
            background: `linear-gradient(to top, ${C.violet}, ${C.cyan})`,
            boxShadow: `0 0 6px ${C.violet}`,
            borderRadius: "1px 1px 0 0",
            opacity: 0.75 + v * 0.25,
          }} />
        ))}
      </div>

      {/* ── System metrics ──────────────────────────────────────────────── */}
      <div style={{ marginBottom: 20 }}>
        {[
          { label: "CPU_LOAD",    value: `${cpuLoad}%`,        color: C.cyan         },
          { label: "CORE_TEMP",   value: `${coreTemp}°C`,      color: C.violetBright },
          { label: "ENCRYPT_KEY", value: encKey,               color: C.pink         },
          { label: "LAT",         value: `${lat}°N`,           color: C.cyan         },
          { label: "LONG",        value: `${lon}°W`,           color: C.cyan         },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontSize: 10, color: C.cyan, opacity: 0.45, letterSpacing: 3 }}>{label}</span>
            <span style={{ fontSize: 13, color, fontFamily: orbitron, fontWeight: 700, letterSpacing: 1 }}>
              {value}
            </span>
          </div>
        ))}
      </div>

      {/* ── ENCRYPT stream ──────────────────────────────────────────────── */}
      <div style={{ borderTop: `1px solid rgba(168,85,247,0.18)`, paddingTop: 12 }}>
        <div style={{ fontSize: 10, letterSpacing: 4, color: C.cyan, opacity: 0.35, marginBottom: 8 }}>
          ENCRYPT STREAM
        </div>
        {hexLines.map((line, i) => (
          <div key={i} style={{
            fontSize: 11, lineHeight: "1.75",
            opacity: 0.2 + (i / hexLines.length) * 0.5,
            color: i % 3 === 0 ? C.cyan : i % 3 === 1 ? C.violetBright : "rgba(168,85,247,0.55)",
            letterSpacing: 1,
          }}>{line}</div>
        ))}
      </div>
    </div>
  );
};

// ── Panel derecho ────────────────────────────────────────────────────────────
const RightPanel: React.FC<SidePanelsProps> = ({ frame, fps, shareTechMono, orbitron }) => {
  const t = frame / fps;

  const opacity = interpolate(frame, [F_IMPACT_BRIEF + 10, F_IMPACT_BRIEF + 55], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  // Barras de señal (5 sensores)
  const signals = [
    { label: "VOICE STT",  freq: 1.2, phase: 0.0 },
    { label: "LLM LOCAL",  freq: 0.9, phase: 1.1 },
    { label: "ORACLE NET", freq: 1.5, phase: 2.2 },
    { label: "TTS ENGINE", freq: 1.1, phase: 0.7 },
    { label: "TAILSCALE",  freq: 0.7, phase: 1.8 },
  ];

  // Indicadores de estado de subsistemas
  const systems = [
    { name: "WHISPER CUDA",    color: C.green  },
    { name: "DEEPSEEK-R1:14B", color: C.cyan   },
    { name: "FISH SPEECH 1.5", color: C.green  },
    { name: "TELEGRAM BOT",    color: C.green  },
    { name: "TAILSCALE VPN",   color: C.cyan   },
    { name: "ORACLE A1",       color: C.violet },
  ];

  const uptime = frame - F_IMPACT_BRIEF;
  const uptimeSec = Math.max(0, uptime / fps).toFixed(1);

  return (
    <div style={{
      position:   "absolute",
      right:       60,
      top:         "50%",
      transform:  "translateY(-50%)",
      width:       520,
      textAlign:  "right",
      opacity,
      fontFamily:  shareTechMono,
      pointerEvents: "none",
    }}>
      {/* ── Cabecera ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-end gap-3 mb-4">
        <span style={{ fontSize: 11, letterSpacing: 5, color: C.cyan, opacity: 0.55 }}>
          SYSTEM STATUS
        </span>
        <div style={{ width: 3, height: 24, background: C.violet, boxShadow: `0 0 10px ${C.violet}` }} />
      </div>

      {/* ── Barras de señal ──────────────────────────────────────────────── */}
      <div className="mb-6">
        {signals.map(({ label, freq, phase }) => {
          const strength = 0.45 + 0.55 * Math.abs(Math.sin(t * freq * 2 * Math.PI + phase));
          return (
            <div key={label} className="mb-3">
              <div className="flex justify-between mb-1">
                <span style={{ fontSize: 11, color: C.cyan, opacity: 0.45, letterSpacing: 2 }}>{label}</span>
                <span style={{ fontSize: 12, color: C.violetBright, fontFamily: orbitron }}>
                  {Math.floor(strength * 100)}%
                </span>
              </div>
              <div style={{ height: 2, background: "rgba(168,85,247,0.12)", borderRadius: 1, overflow: "hidden" }}>
                <div style={{
                  height:     "100%",
                  width:      `${strength * 100}%`,
                  background: `linear-gradient(90deg, ${C.violet}, ${C.cyan})`,
                  boxShadow:  `0 0 6px ${C.cyan}`,
                  borderRadius: 1,
                  marginLeft: `${(1 - strength) * 100}%`,
                }} />
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Subsistemas ──────────────────────────────────────────────────── */}
      <div style={{ borderTop: `1px solid rgba(168,85,247,0.2)`, paddingTop: 16, marginBottom: 20 }}>
        <div style={{ fontSize: 10, letterSpacing: 4, color: C.cyan, opacity: 0.4, marginBottom: 12 }}>
          MODULES
        </div>
        {systems.map(({ name, color }) => (
          <div key={name} className="flex items-center justify-end gap-3 mb-2">
            <span style={{ fontSize: 12, color: `rgba(168,85,247,0.65)`, letterSpacing: 1 }}>{name}</span>
            <div style={{
              width:  7, height: 7, borderRadius: "50%",
              background: color,
              boxShadow: `0 0 8px ${color}`,
              flexShrink: 0,
            }} />
          </div>
        ))}
      </div>

      {/* ── Uptime / Frame ───────────────────────────────────────────────── */}
      <div style={{ borderTop: `1px solid rgba(168,85,247,0.15)`, paddingTop: 14 }}>
        <div style={{ fontSize: 12, color: `rgba(34,211,238,0.35)`, letterSpacing: 3 }}>
          UPTIME {uptimeSec}s
        </div>
        <div style={{ fontSize: 11, color: `rgba(168,85,247,0.28)`, letterSpacing: 2, marginTop: 4 }}>
          165 FPS · 3440×1440 · 21:9
        </div>
      </div>
    </div>
  );
};

// ── Exportación combinada ─────────────────────────────────────────────────────
export const SidePanels: React.FC<SidePanelsProps> = (props) => (
  <>
    <LeftPanel  {...props} />
    <RightPanel {...props} />
  </>
);
