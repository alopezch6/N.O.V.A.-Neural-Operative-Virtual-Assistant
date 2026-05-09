// ── Composición ──────────────────────────────────────────────────────────────
export const W   = 3440;
export const H   = 1440;
export const FPS = 165;
export const CX  = W / 2;   // 1720
export const CY  = H / 2;   // 720

// ── Fases legacy (mantenidas para compatibilidad con componentes HTML) ────────
export const F_ASSEMBLY_END = 4  * FPS;   //  660
export const F_LOAD_END     = 9  * FPS;   // 1485
export const F_IMPACT_END   = 10 * FPS;   // 1650
export const F_TOTAL        = 20 * FPS;   // 3300

// ── Nuevo timeline cinematográfico ────────────────────────────────────────────
export const F_BOOT_END     = Math.round(1.5 * FPS);   //  248 — noise + ejes
export const F_RINGS_END    = Math.round(3.0 * FPS);   //  495 — anillos dibujados
export const F_ACCEL_END    = Math.round(5.5 * FPS);   //  908 — aceleración + hex
export const F_PRECRIT_END  = Math.round(8.0 * FPS);   // 1320 — logo ensamblado
export const F_SHAKE_END    = Math.round(9.0 * FPS);   // 1485 — fin vibración = inicio impacto
export const F_IMPACT_BRIEF = Math.round(9.2 * FPS);   // 1518 — fin "the pop"
export const F_HUD_END      = Math.round(12.0 * FPS);  // 1980 — HUD desplegado

// ── Geometría de anillos ──────────────────────────────────────────────────────
export const R1   = 230;
export const R2   = 300;
export const R3   = 370;
export const R4   = 470;
export const R5   = 590;
export const CORE = 72;

// ── Paleta (de hud-v2.html) ───────────────────────────────────────────────────
export const C = {
  bg:           "#04000f",
  cyan:         "#22d3ee",
  violet:       "#a855f7",
  violetBright: "#c084fc",
  pink:         "#e879f9",
  green:        "#4ade80",
  orange:       "#fb923c",
  white:        "#ffffff",
} as const;

export type Phase = "assembly" | "load" | "impact" | "operational";

export function getPhase(frame: number): Phase {
  if (frame < F_ASSEMBLY_END) return "assembly";
  if (frame < F_LOAD_END)     return "load";
  if (frame < F_IMPACT_END)   return "impact";
  return "operational";
}

// Hex pseudo-random para cascadas del panel lateral
export function pseudoHex(seed: number, frame: number): string {
  const n = Math.abs((seed * 7919 + frame * 31 + seed * frame * 3) % 65536);
  return n.toString(16).padStart(4, "0").toUpperCase();
}
