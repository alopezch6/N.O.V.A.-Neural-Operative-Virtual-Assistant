import React from "react";

// Todos los filtros SVG en un solo <defs> compartido por el SVG principal
export const SvgFilters: React.FC = () => (
  <defs>
    {/* ── Deep Bloom Cyan (triple blur encadenado) ──────────────────────── */}
    <filter id="bloom-c" x="-80%" y="-80%" width="260%" height="260%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="3"  result="b1" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="10" result="b2" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="28" result="b3" />
      <feMerge>
        <feMergeNode in="b3" />
        <feMergeNode in="b2" />
        <feMergeNode in="b1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    {/* ── Deep Bloom Violet ────────────────────────────────────────────────── */}
    <filter id="bloom-v" x="-80%" y="-80%" width="260%" height="260%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="5"  result="b1" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="16" result="b2" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="42" result="b3" />
      <feMerge>
        <feMergeNode in="b3" />
        <feMergeNode in="b2" />
        <feMergeNode in="b1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    {/* ── Deep Bloom Core (intenso, gran radio) ────────────────────────────── */}
    <filter id="bloom-core" x="-150%" y="-150%" width="400%" height="400%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="6"  result="b1" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="20" result="b2" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="55" result="b3" />
      <feMerge>
        <feMergeNode in="b3" />
        <feMergeNode in="b2" />
        <feMergeNode in="b1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    {/* ── Flash / Impact ───────────────────────────────────────────────────── */}
    <filter id="bloom-flash" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="25" result="b1" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="70" result="b2" />
      <feMerge>
        <feMergeNode in="b2" />
        <feMergeNode in="b1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    {/* ── Gradientes radiales ───────────────────────────────────────────────── */}
    <radialGradient id="grad-orb" cx="50%" cy="50%" r="50%">
      <stop offset="0%"   stopColor="#22d3ee" stopOpacity="0.40" />
      <stop offset="55%"  stopColor="#a855f7" stopOpacity="0.12" />
      <stop offset="100%" stopColor="#a855f7" stopOpacity="0"    />
    </radialGradient>

    <radialGradient id="grad-flash" cx="50%" cy="50%" r="50%">
      <stop offset="0%"   stopColor="#ffffff" stopOpacity="1"   />
      <stop offset="25%"  stopColor="#22d3ee" stopOpacity="0.9" />
      <stop offset="65%"  stopColor="#a855f7" stopOpacity="0.4" />
      <stop offset="100%" stopColor="#a855f7" stopOpacity="0"   />
    </radialGradient>

    <linearGradient id="grad-ring3-arc" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%"   stopColor="#a855f7" />
      <stop offset="50%"  stopColor="#e879f9" />
      <stop offset="100%" stopColor="#22d3ee" />
    </linearGradient>

    {/* ── Bloom partículas (pequeño-medio) ────────────────────────────────── */}
    <filter id="bloom-particle" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="2"  result="b1" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="8"  result="b2" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="22" result="b3" />
      <feMerge>
        <feMergeNode in="b3" />
        <feMergeNode in="b2" />
        <feMergeNode in="b1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    {/* ── Bloom arcos eléctricos ────────────────────────────────────────────── */}
    <filter id="bloom-arc" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="3"  result="b1" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="12" result="b2" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="32" result="b3" />
      <feMerge>
        <feMergeNode in="b3" />
        <feMergeNode in="b2" />
        <feMergeNode in="b1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    {/* ── Bloom burst de impacto (muy intenso) ─────────────────────────────── */}
    <filter id="bloom-burst" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="8"  result="b1" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="26" result="b2" />
      <feGaussianBlur in="SourceGraphic" stdDeviation="65" result="b3" />
      <feMerge>
        <feMergeNode in="b3" />
        <feMergeNode in="b2" />
        <feMergeNode in="b1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>

    {/* ── Film Grain (seed cambia cada frame desde BootSequence) ───────────── */}
    <filter id="grain" x="0%" y="0%" width="100%" height="100%">
      <feTurbulence
        id="grain-turb"
        type="fractalNoise"
        baseFrequency="0.72"
        numOctaves="4"
        seed="0"
        stitchTiles="stitch"
        result="noise"
      />
      <feColorMatrix type="saturate" values="0" in="noise" result="gray" />
      <feBlend in="SourceGraphic" in2="gray" mode="overlay" />
    </filter>
  </defs>
);
