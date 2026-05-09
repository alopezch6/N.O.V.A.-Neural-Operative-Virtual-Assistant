import React from "react";
import { interpolate } from "remotion";
import { W, H, F_RINGS_END, F_ACCEL_END } from "../constants";

interface HexScrollProps { frame: number; fps: number; }

function hexLine(seed: number, frame: number): string {
  const cols = 8;
  return Array.from({ length: cols }, (_, i) => {
    const n = Math.abs(((seed + i) * 7919 + frame * 13 + i * frame * 3) % 65536);
    return n.toString(16).padStart(4, "0").toUpperCase();
  }).join(" ");
}

const LINES = 28;
const LINE_H = H / LINES;

export const HexScroll: React.FC<HexScrollProps> = ({ frame, fps }) => {
  const t = frame / fps;

  const op = interpolate(frame, [F_RINGS_END, F_RINGS_END + 40, F_ACCEL_END - 30, F_ACCEL_END], [0, 1, 1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  if (op < 0.005) return null;

  const scrollY = (t * 65) % (LINE_H * LINES);

  const colStyle: React.CSSProperties = {
    position: "absolute",
    top: 0,
    width: 320,
    height: H,
    overflow: "hidden",
    pointerEvents: "none",
    fontFamily: "'Share Tech Mono', 'Courier New', monospace",
    fontSize: 11,
    lineHeight: `${LINE_H}px`,
    letterSpacing: "0.05em",
    color: "rgba(34,211,238,0.45)",
    opacity: op,
  };

  const lines = Array.from({ length: LINES + 2 }, (_, i) => (
    <div key={i} style={{ whiteSpace: "nowrap", paddingLeft: 8 }}>
      {hexLine(i * 31 + 7, Math.floor(frame / 4) + i)}
    </div>
  ));

  return (
    <>
      {/* Left column */}
      <div style={{ ...colStyle, left: 0, zIndex: 5 }}>
        <div style={{ transform: `translateY(-${scrollY}px)` }}>{lines}</div>
      </div>
      {/* Right column — scrolls opposite direction */}
      <div style={{ ...colStyle, right: 0, left: "auto", textAlign: "right", zIndex: 5 }}>
        <div style={{ transform: `translateY(-${(H * 2 - scrollY) % (LINE_H * LINES)}px)` }}>
          {Array.from({ length: LINES + 2 }, (_, i) => (
            <div key={i} style={{ whiteSpace: "nowrap", paddingRight: 8 }}>
              {hexLine(i * 53 + 99, Math.floor(frame / 4) + i + 14)}
            </div>
          ))}
        </div>
      </div>
    </>
  );
};
