import React, { useMemo, useRef } from "react";
import { ThreeCanvas } from "@remotion/three";
import { useThree } from "@react-three/fiber";
import { Text3D, Center } from "@react-three/drei";
import * as THREE from "three";
import {
  EffectComposer, Bloom, ChromaticAberration, Vignette, Noise, Glitch,
} from "@react-three/postprocessing";
import { BlendFunction, KernelSize, GlitchMode } from "postprocessing";
import { interpolate, spring, staticFile } from "remotion";
import {
  W, H, C,
  R1, R2, R3, R4, R5, CORE,
  F_BOOT_END, F_RINGS_END, F_ACCEL_END, F_PRECRIT_END,
  F_SHAKE_END, F_IMPACT_BRIEF, F_HUD_END,
} from "../constants";

// ── helpers ───────────────────────────────────────────────────────────────────
const EL  = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const CAM_Z = 1200;
const FOV   = 2 * Math.atan(H / 2 / CAM_Z) * (180 / Math.PI);

function rnd(n: number): number {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

// Dash ring shader
const VERT = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
const FRAG = `
  varying vec2 vUv;
  uniform vec3  uColor;
  uniform float uOpacity;
  uniform float uDashCount;
  void main() {
    float u       = vUv.y;
    float seg     = floor(u * uDashCount);
    float isMajor = 1.0 - sign(mod(seg, 4.0));
    float ratio   = isMajor > 0.5 ? 0.82 : 0.55;
    float phase   = fract(u * uDashCount);
    if (phase > ratio) discard;
    float bright  = 0.78 + isMajor * 0.22;
    gl_FragColor  = vec4(uColor * bright, uOpacity);
  }
`;

// RGB colour triples for particles
const RGB_CYAN   = [0.133, 0.827, 0.933] as const;
const RGB_VIOLET = [0.659, 0.333, 0.969] as const;
const RGB_VB     = [0.753, 0.518, 0.988] as const;
const RGB_PINK   = [0.910, 0.475, 0.976] as const;
const RGB_WHITE  = [1.000, 1.000, 1.000] as const;
const PALETTE    = [RGB_CYAN, RGB_VIOLET, RGB_VB, RGB_PINK, RGB_WHITE, RGB_CYAN];

interface Props { frame: number; fps: number; }

// ════════════════════════════════════════════════════════════════════════════
// MAIN EXPORT
// ════════════════════════════════════════════════════════════════════════════
export const ThreeScene: React.FC<Props> = ({ frame, fps }) => (
  <ThreeCanvas
    width={W} height={H}
    style={{ position: "absolute", top: 0, left: 0, zIndex: 2 }}
    gl={{ alpha: true, antialias: true }}
    camera={{ position: [0, 0, CAM_Z], fov: FOV, near: 1, far: 6000 }}
  >
    <SceneContent frame={frame} fps={fps} />
  </ThreeCanvas>
);

// ── Root scene ────────────────────────────────────────────────────────────────
const SceneContent: React.FC<Props> = ({ frame, fps }) => {
  const t = frame / fps;

  // Phase progress values
  const bootProg   = interpolate(frame, [0,            F_BOOT_END],    [0, 1], EL);
  const ringProg   = interpolate(frame, [F_BOOT_END,   F_RINGS_END],   [0, 1], EL);
  const accelProg  = interpolate(frame, [F_RINGS_END,  F_ACCEL_END],   [0, 1], EL);
  const loadProg   = interpolate(frame, [F_RINGS_END,  F_SHAKE_END],   [0, 1], EL);
  const logoProg   = interpolate(frame, [F_ACCEL_END,  F_PRECRIT_END], [0, 1], EL);
  const impProg    = interpolate(frame, [F_SHAKE_END,  F_IMPACT_BRIEF],[0, 1], EL);
  const operProg   = interpolate(frame, [F_HUD_END,    F_HUD_END+120], [0, 1], EL);

  const isGlitch   = frame >= F_SHAKE_END && frame <= F_IMPACT_BRIEF;

  // Bloom: ramps from 1 → 3.5 during pre-crit, spikes at impact
  const bloomI = 1.0
    + logoProg * 2.5
    + interpolate(frame, [F_SHAKE_END, F_SHAKE_END + 20, F_IMPACT_BRIEF], [0, 8, 0], EL);

  const caOff = 0.0008
    + interpolate(frame, [F_SHAKE_END, F_SHAKE_END + 8, F_SHAKE_END + 50], [0, 0.005, 0], EL);

  return (
    <>
      <ambientLight intensity={0.04} color={C.cyan} />
      {/* PointLight above logo — blooms onto rings */}
      <pointLight position={[0, 180, 200]} intensity={logoProg * 4} color={C.cyan} distance={800} />

      <CameraRig frame={frame} fps={fps} t={t}
        accelProg={accelProg} loadProg={loadProg}
        impProg={impProg} operProg={operProg} />

      <GodRays3D    t={t} loadProg={loadProg} operProg={operProg} />
      <DashRings3D  frame={frame} fps={fps} t={t}
        ringProg={ringProg} loadProg={loadProg} accelProg={accelProg} />
      <EnergyArcs3D frame={frame} t={t} loadProg={loadProg} />
      <Particles3D  frame={frame} fps={fps} t={t}
        loadProg={loadProg} impProg={impProg} operProg={operProg} />
      <Nucleus3D    frame={frame} fps={fps} t={t}
        loadProg={loadProg} impProg={impProg} operProg={operProg} />
      <NovaLogo3D   frame={frame} fps={fps} t={t}
        logoProg={logoProg} impProg={impProg} operProg={operProg} />
      <ImpactBurst3D frame={frame} fps={fps} />

      <EffectComposer>
        <Bloom
          luminanceThreshold={0.05}
          luminanceSmoothing={0.85}
          intensity={bloomI}
          kernelSize={KernelSize.HUGE}
          mipmapBlur
        />
        <Glitch
          strength={new THREE.Vector2(0.55, 0.9) as any}
          mode={GlitchMode.CONSTANT_WILD}
          active={isGlitch}
          ratio={0.85}
        />
        <ChromaticAberration
          offset={new THREE.Vector2(caOff, caOff * 0.6) as any}
          radialModulation={true}
          modulationOffset={0.65}
        />
        <Vignette eskil={false} offset={0.22} darkness={0.88} />
        <Noise opacity={0.035} blendFunction={BlendFunction.OVERLAY} />
      </EffectComposer>
    </>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// CAMERA RIG — shake (8-9s), punch at impact, float (12-20s)
// ════════════════════════════════════════════════════════════════════════════
interface CamProps {
  frame: number; fps: number; t: number;
  accelProg: number; loadProg: number; impProg: number; operProg: number;
}
const CameraRig: React.FC<CamProps> = ({ frame, fps, t, accelProg, loadProg, impProg, operProg }) => {
  const { camera } = useThree();

  // Shake: 8-9s, ramping intensity
  const shakeAmt = interpolate(frame, [F_PRECRIT_END, F_SHAKE_END], [0, 1], EL)
    * (1 - impProg);
  const shake = shakeAmt * 16;
  const sx = shake * (Math.sin(t * 83.7) * 0.65 + Math.sin(t * 131.3) * 0.35);
  const sy = shake * (Math.sin(t * 71.2) * 0.55 + Math.sin(t * 107.9) * 0.45);

  // Punch forward at impact (camera rushes in then snaps back)
  const punch = interpolate(frame,
    [F_SHAKE_END, F_SHAKE_END + 8, F_IMPACT_BRIEF + 10],
    [0, 180, 0], EL);

  // Slow float: 12-20s
  const floatAmt = interpolate(frame, [F_HUD_END, F_HUD_END + 120], [0, 1], EL);
  const fx = floatAmt * 10 * Math.sin(t * 0.29);
  const fy = floatAmt *  7 * Math.sin(t * 0.43);

  camera.position.set(fx + sx, fy + sy, CAM_Z - punch);
  camera.lookAt(0, 0, 0);
  return null;
};

// ════════════════════════════════════════════════════════════════════════════
// GOD RAYS
// ════════════════════════════════════════════════════════════════════════════
const GodRays3D: React.FC<{ t: number; loadProg: number; operProg: number }> = ({ t, loadProg, operProg }) => {
  const op = loadProg * 0.055 + operProg * 0.04;
  if (op < 0.003) return null;

  const RAY_LEN   = Math.sqrt(W * W + H * H) * 0.7;
  const RAY_COUNT = 16;

  const rays = useMemo(() =>
    Array.from({ length: RAY_COUNT }, (_, i) => {
      const angle = (i / RAY_COUNT) * Math.PI * 2;
      const halfW = i % 4 === 0 ? 0.026 : i % 2 === 0 ? 0.014 : 0.007;
      const ha    = halfW * Math.PI * 2;
      return {
        pos: new Float32Array([
          0, 0, 0,
          Math.cos(angle - ha) * RAY_LEN, Math.sin(angle - ha) * RAY_LEN, 0,
          Math.cos(angle + ha) * RAY_LEN, Math.sin(angle + ha) * RAY_LEN, 0,
        ]),
        major: i % 4 === 0,
        color: i % 3 === 0 ? C.cyan : C.violet,
      };
    })
  , []);

  const rot1 =  t * 3.8 * Math.PI / 180;
  const rot2 = -t * 2.1 * Math.PI / 180;

  return (
    <group>
      <group rotation={[0, 0, rot1]}>
        {rays.filter((_, i) => i % 2 === 0).map(({ pos, major, color }, i) => (
          <mesh key={i}>
            <bufferGeometry><bufferAttribute attach="attributes-position" args={[pos, 3]} /></bufferGeometry>
            <meshBasicMaterial color={color} transparent opacity={op * (major ? 1 : 0.45)}
              side={THREE.DoubleSide} depthWrite={false} />
          </mesh>
        ))}
      </group>
      <group rotation={[0, 0, rot2]}>
        {rays.filter((_, i) => i % 2 === 1).map(({ pos, major }, i) => (
          <mesh key={i}>
            <bufferGeometry><bufferAttribute attach="attributes-position" args={[pos, 3]} /></bufferGeometry>
            <meshBasicMaterial color={C.violet} transparent opacity={op * 0.5 * (major ? 1 : 0.4)}
              side={THREE.DoubleSide} depthWrite={false} />
          </mesh>
        ))}
      </group>
    </group>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// DASH RINGS — shader-based dash arrays + motion trail
// ════════════════════════════════════════════════════════════════════════════
const RING_CFG = [
  { R: R1, tube: 2.8, color: C.cyan,        tiltX: 0,               tiltZ: 0,     spd:  60, delay: 0,   cfg: { damping: 5, mass: 1.6, stiffness: 42 } },
  { R: R2, tube: 2.2, color: C.violetBright, tiltX:  Math.PI * 0.12, tiltZ: 0.07, spd: -44, delay: 0.5, cfg: { damping: 5, mass: 1.6, stiffness: 42 } },
  { R: R3, tube: 2.6, color: C.pink,         tiltX: -Math.PI * 0.17, tiltZ:-0.09, spd:  26, delay: 1.0, cfg: { damping: 5, mass: 1.6, stiffness: 42 } },
  { R: R4, tube: 1.6, color: C.violet,       tiltX:  Math.PI * 0.26, tiltZ: 0.14, spd: -16, delay: 0.2, cfg: { damping: 9, mass: 2.2, stiffness: 30 } },
  { R: R5, tube: 1.3, color: C.cyan,         tiltX: -Math.PI * 0.21, tiltZ:-0.13, spd:   8, delay: 0.4, cfg: { damping: 9, mass: 2.2, stiffness: 30 } },
] as const;

interface DashRingsProps {
  frame: number; fps: number; t: number;
  ringProg: number; loadProg: number; accelProg: number;
}
const DashRings3D: React.FC<DashRingsProps> = ({ frame, fps, t, ringProg, loadProg, accelProg }) => {
  // Speed multiplier: slow at start, accelerates through accel phase
  const speedMult = 0.2 + accelProg * 0.8 + loadProg * 0.4;
  const elapsed   = Math.max(0, t - 1.5); // seconds since rings start

  // Per-ring dash shader materials (one per ring, updated each frame)
  const mats = useMemo(() =>
    RING_CFG.map(({ color }) => new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: {
        uColor:     { value: new THREE.Color(color) },
        uOpacity:   { value: 1.0 },
        uDashCount: { value: 24.0 },
      },
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
    }))
  , []);

  return (
    <>
      <AxesCross frame={frame} fps={fps} />
      {RING_CFG.map(({ R, tube, tiltX, tiltZ, spd, delay, cfg }, i) => {
        const raw  = spring({ frame: Math.max(0, frame - Math.round(F_BOOT_END + delay * fps)), fps, config: cfg, from: 0, to: 1 });
        const p    = Math.min(1, Math.max(0, raw));
        const op   = Math.min(1, raw * 1.2) * ringProg;
        const arc  = p * Math.PI * 2;
        const spin = elapsed * spd * speedMult * Math.PI / 180;
        const spinPerFrame = spd * speedMult * Math.PI / 180 / fps;

        // Update shader uniforms
        mats[i].uniforms.uOpacity.value = op * 0.92;

        const TRAIL_N = 6;

        return (
          <group key={i} rotation={[tiltX, 0, tiltZ]}>
            {/* Motion trail: ghost copies at previous positions */}
            {Array.from({ length: TRAIL_N }, (_, ti) => {
              const ghostSpin = spin - spinPerFrame * (ti + 1) * 2.5;
              const trailOp   = ((TRAIL_N - ti) / TRAIL_N) * op * 0.18 * accelProg;
              if (trailOp < 0.005) return null;
              return (
                <mesh key={`tr-${ti}`} rotation={[0, 0, ghostSpin]}>
                  <torusGeometry args={[R, tube * 1.2, 6, 128, arc]} />
                  <meshBasicMaterial color={RING_CFG[i].color} transparent
                    opacity={trailOp} depthWrite={false} />
                </mesh>
              );
            })}
            {/* Primary dash ring */}
            <mesh rotation={[0, 0, spin]} material={mats[i]}>
              <torusGeometry args={[R, tube, 8, 256, arc]} />
            </mesh>
            {/* Wide soft halo */}
            {p > 0.25 && (
              <mesh rotation={[0, 0, spin]}>
                <torusGeometry args={[R, tube * 5.5, 6, 96, arc]} />
                <meshBasicMaterial color={RING_CFG[i].color} transparent
                  opacity={op * 0.03} depthWrite={false} />
              </mesh>
            )}
          </group>
        );
      })}
    </>
  );
};

const AxesCross: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  const raw    = spring({ frame, fps, config: { damping: 10, mass: 0.8, stiffness: 90 }, from: 0, to: 1 });
  const p      = Math.min(1, Math.max(0, raw));
  // Flicker in boot phase
  const t      = frame / fps;
  const flicker = 0.5 + 0.5 * Math.abs(Math.sin(t * 47.3 + Math.sin(t * 31.1) * 3));
  const op     = p * (frame < F_BOOT_END ? flicker : 1) * 0.28;
  return (
    <>
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position"
            args={[new Float32Array([-W/2 * p, 0, 0,  W/2 * p, 0, 0]), 3]} />
        </bufferGeometry>
        <lineBasicMaterial color={C.cyan} transparent opacity={op} />
      </lineSegments>
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position"
            args={[new Float32Array([0, -H/2 * p, 0,  0, H/2 * p, 0]), 3]} />
        </bufferGeometry>
        <lineBasicMaterial color={C.cyan} transparent opacity={op} />
      </lineSegments>
    </>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// 3D NOVA LOGO — MeshStandardMaterial metalness:1 + flies in from Z
// ════════════════════════════════════════════════════════════════════════════
interface LogoProps {
  frame: number; fps: number; t: number;
  logoProg: number; impProg: number; operProg: number;
}
const NovaLogo3D: React.FC<LogoProps> = ({ frame, fps, t, logoProg, impProg, operProg }) => {
  if (frame < F_ACCEL_END - 20) return null;

  const logoZ   = interpolate(frame, [F_ACCEL_END, F_PRECRIT_END], [900, 0], EL);
  const logoOp  = interpolate(frame, [F_ACCEL_END, F_ACCEL_END + 55], [0, 1], EL);
  // Fade out in operational (HTML logo takes over)
  const fadeOut = interpolate(frame, [F_HUD_END - 60, F_HUD_END], [1, 0], EL);
  const finalOp = logoOp * fadeOut;

  if (finalOp < 0.005) return null;

  const breathPhase = t * 2 * Math.PI * 0.45;
  const breathScale = operProg > 0 ? 0.95 + 0.05 * Math.sin(breathPhase) : 1.0;

  // Emissive intensity: glows brighter during load
  const emissiveI = 0.3 + logoProg * 1.2 + impProg * 2;

  return (
    <group position={[0, logoZ > 0 ? 0 : 0, logoZ]} scale={[breathScale, breathScale, 1]}>
      <Center>
        <Text3D
          font={staticFile("fonts/helvetiker_bold.typeface.json")}
          size={95}
          height={22}
          curveSegments={12}
          bevelEnabled
          bevelThickness={3}
          bevelSize={1.5}
          bevelSegments={5}
        >
          NOVA
          <meshStandardMaterial
            color={C.cyan}
            emissive={C.cyan}
            emissiveIntensity={emissiveI}
            metalness={1}
            roughness={0.0}
            transparent
            opacity={finalOp}
          />
        </Text3D>
      </Center>
    </group>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// ENERGY ARCS
// ════════════════════════════════════════════════════════════════════════════
const EnergyArcs3D: React.FC<{ frame: number; t: number; loadProg: number }> = ({ frame, t, loadProg }) => {
  if (frame < F_RINGS_END + 8 || frame > F_SHAKE_END + 18) return null;

  const tick   = Math.floor(frame / 3);
  const opBase = interpolate(frame,
    [F_RINGS_END + 8, F_RINGS_END + 35, F_SHAKE_END, F_SHAKE_END + 18],
    [0, 1, 0.75, 0], EL);

  const arcs = useMemo(() => {
    const tRs = [R1 * 0.80, R2 * 0.85, R3 * 0.87];
    return Array.from({ length: 12 }, (_, i) => {
      const seed = i * 100 + tick * 7;
      const bAng = rnd(seed * 3.14) * Math.PI * 2;
      const tR   = tRs[(i + tick) % 3];
      const tAng = bAng + (rnd(seed * 2.71) - 0.5) * 0.8;
      const sx = Math.cos(bAng) * CORE * 1.2;
      const sy = Math.sin(bAng) * CORE * 1.2;
      const ex = Math.cos(tAng) * tR;
      const ey = Math.sin(tAng) * tR;
      const SEGS = 9;
      const pts: number[] = [];
      for (let j = 0; j <= SEGS; j++) {
        const fr = j / SEGS;
        const lx = sx + (ex - sx) * fr;
        const ly = sy + (ey - sy) * fr;
        const dx = -(ey - sy); const dy = ex - sx;
        const pl = Math.sqrt(dx*dx + dy*dy) || 1;
        const d  = fr * (1 - fr) * 4 * (rnd(seed * 0.91 + j * 17.3) - 0.5) * 80;
        pts.push(lx + dx/pl*d, ly + dy/pl*d, 0);
      }
      return { pos: new Float32Array(pts), color: i % 3 === 0 ? C.cyan : C.violetBright, flicker: rnd(i*5.3+tick) };
    });
  }, [tick]);

  return (
    <>
      {arcs.map(({ pos, color, flicker }, i) => (
        <line key={i}>
          <bufferGeometry><bufferAttribute attach="attributes-position" args={[pos, 3]} /></bufferGeometry>
          <lineBasicMaterial color={color} transparent opacity={opBase * (0.4 + flicker * 0.6)} />
        </line>
      ))}
    </>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// PARTICLES 3D
// ════════════════════════════════════════════════════════════════════════════
const N_PTS = 3000;

interface P3DProps {
  frame: number; fps: number; t: number;
  loadProg: number; impProg: number; operProg: number;
}
const Particles3D: React.FC<P3DProps> = ({ frame, fps, t, loadProg, impProg, operProg }) => {
  const inLoad   = frame <= F_SHAKE_END;
  const inImpact = frame <= F_IMPACT_BRIEF + 35;
  const fadeIn   = interpolate(frame, [F_RINGS_END - 25, F_RINGS_END + 50], [0, 1], EL);

  const { positions, colors } = useMemo(() => {
    const positions = new Float32Array(N_PTS * 3);
    const colors    = new Float32Array(N_PTS * 3);
    for (let i = 0; i < N_PTS; i++) {
      const r1 = rnd(i*7.31); const r2 = rnd(i*13.71+42.3); const r3 = rnd(i*5.13+87.1);
      const r4 = rnd(i*17.97+23.7); const r5 = rnd(i*3.33+61.9); const r6 = rnd(i*11.11+5.5);
      const baseAngle = r1 * Math.PI * 2;
      const angSpeed  = (0.2 + r3 * 0.7) * (r4 > 0.5 ? 1 : -1);
      const baseR     = 60 + r2 * 380;
      const col       = PALETTE[Math.floor(r6 * PALETTE.length)];
      let x = 0, y = 0, z = 0, op = 0;
      if (inLoad) {
        const angle  = baseAngle + t * angSpeed;
        const radius = baseR * (0.2 + loadProg * 0.8);
        x = Math.cos(angle) * radius;
        y = Math.sin(angle) * radius;
        z = (r5 - 0.5) * 25;
        const flicker = 0.3 + 0.7 * Math.abs(Math.sin(t * (2+r3*5) + i*0.7));
        op = fadeIn * loadProg * flicker * 0.9;
      } else if (inImpact) {
        const dt = (frame - F_SHAKE_END) / fps;
        const speed = 180 + r2 * 490;
        const eAng  = baseAngle + (r3 - 0.5) * 0.65;
        x = Math.cos(eAng) * (baseR * 0.15 + dt * speed);
        y = Math.sin(eAng) * (baseR * 0.15 + dt * speed);
        z = (r5 - 0.5) * 35;
        op = interpolate(frame, [F_SHAKE_END, F_SHAKE_END+50, F_IMPACT_BRIEF+35], [1, 0.6, 0], EL);
      } else {
        const ambAngle = baseAngle + t * angSpeed * 0.2;
        const ambR     = 180 + r2 * 580;
        x = Math.cos(ambAngle) * ambR;
        y = Math.sin(ambAngle) * ambR;
        z = (r5 - 0.5) * 60;
        const flicker = 0.2 + 0.8 * Math.abs(Math.sin(t * (0.8+r3*2.5) + i*0.8));
        op = operProg * 0.28 * flicker;
      }
      positions[i*3]=x; positions[i*3+1]=y; positions[i*3+2]=z;
      colors[i*3]=col[0]*op; colors[i*3+1]=col[1]*op; colors[i*3+2]=col[2]*op;
    }
    return { positions, colors };
  }, [frame]);

  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color"    args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial vertexColors size={2.8} transparent opacity={1}
        blending={THREE.AdditiveBlending} depthWrite={false} sizeAttenuation={false} />
    </points>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// NUCLEUS 3D
// ════════════════════════════════════════════════════════════════════════════
interface NucProps {
  frame: number; fps: number; t: number;
  loadProg: number; impProg: number; operProg: number;
}
const Nucleus3D: React.FC<NucProps> = ({ frame, fps, t, loadProg, impProg, operProg }) => {
  const isOp    = frame >= F_IMPACT_BRIEF;
  const vibAmp  = loadProg * 9;
  const vibFreq = 7 + loadProg * 18;
  const vx = vibAmp * Math.sin(t * vibFreq * 2 * Math.PI);
  const vy = vibAmp * 0.35 * Math.cos(t * vibFreq * 2 * Math.PI * 1.4);
  const breathPhase = t * 2 * Math.PI * 0.45;
  const breathScale = isOp ? 0.93 + 0.07 * Math.sin(breathPhase) : 1.0;
  const breathOp    = isOp ? 0.72 + 0.28 * Math.sin(breathPhase) : 1.0;
  const impBoost    = interpolate(frame, [F_SHAKE_END, F_SHAKE_END+20, F_IMPACT_BRIEF], [0, 1.5, 0], EL);
  const glowStr     = Math.pow(loadProg, 1.8) * 65 + 4;
  const r           = CORE * breathScale;
  const chargeArc   = loadProg > 0.05 ? loadProg * Math.PI * 2 : 0;

  const petals = useMemo(() => loadProg > 0.01
    ? Array.from({ length: 12 }, (_, i) => {
        const angle = (i / 12) * Math.PI * 2;
        const pProg = Math.max(0, Math.min(1, (loadProg - i/12) * 12));
        const rp    = 132;
        return {
          pos: new Float32Array([
            Math.cos(angle-0.08)*rp, Math.sin(angle-0.08)*rp, 0,
            Math.cos(angle+0.08)*rp, Math.sin(angle+0.08)*rp, 0,
          ]),
          color: i % 3 === 0 ? C.cyan : C.violetBright,
          op: pProg * (i % 3 === 0 ? 1 : 0.75),
        };
      })
    : []
  , [loadProg]);

  return (
    <group position={[vx, vy, 0]}>
      <mesh>
        <sphereGeometry args={[r*3.6+glowStr*0.35, 32, 32]} />
        <meshBasicMaterial color={C.cyan} transparent opacity={0.022+loadProg*0.032} depthWrite={false} />
      </mesh>
      <mesh>
        <sphereGeometry args={[r*2.1, 32, 32]} />
        <meshBasicMaterial color={C.cyan} transparent opacity={(0.1+loadProg*0.22)*breathOp} depthWrite={false} />
      </mesh>
      <mesh>
        <sphereGeometry args={[r, 48, 48]} />
        <meshBasicMaterial color={C.cyan} transparent opacity={Math.min(1,(1+impBoost*0.4)*breathOp)} depthWrite={false} />
      </mesh>
      <mesh>
        <sphereGeometry args={[r*0.58, 32, 32]} />
        <meshBasicMaterial color={C.cyan} transparent opacity={0.09+loadProg*0.14+impBoost*0.3} depthWrite={false} />
      </mesh>
      <mesh>
        <sphereGeometry args={[9+impBoost*4, 16, 16]} />
        <meshBasicMaterial color={"#ffffff"} transparent opacity={Math.min(1.5,0.9+impBoost*0.5)} depthWrite={false} />
      </mesh>
      {chargeArc > 0 && (
        <mesh rotation={[Math.PI/2, 0, -Math.PI/2]}>
          <torusGeometry args={[108, 1.2, 4, 128, chargeArc]} />
          <meshBasicMaterial color={C.violetBright} transparent opacity={loadProg*0.55} depthWrite={false} />
        </mesh>
      )}
      {petals.map(({ pos, color, op }, i) => (
        <lineSegments key={i}>
          <bufferGeometry><bufferAttribute attach="attributes-position" args={[pos, 3]} /></bufferGeometry>
          <lineBasicMaterial color={color} transparent opacity={op} />
        </lineSegments>
      ))}
    </group>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// IMPACT BURST — 36 rays + 4 shockwave rings
// ════════════════════════════════════════════════════════════════════════════
const ImpactBurst3D: React.FC<{ frame: number; fps: number }> = ({ frame, fps }) => {
  if (frame < F_SHAKE_END - 2) return null;
  const since = Math.max(0, frame - F_SHAKE_END);
  const burstProg = Math.min(1, Math.max(0, spring({
    frame: since, fps, config: { damping: 10, mass: 0.35, stiffness: 320 }, from: 0, to: 1,
  })));
  const rayOp = interpolate(frame,
    [F_SHAKE_END, F_SHAKE_END + 12, F_IMPACT_BRIEF],
    [0, 1, 0], EL);
  const WAVES = [
    { delay:  0, maxR:  500, dur: 35, sw: 3.0, color: C.cyan         },
    { delay:  6, maxR:  850, dur: 45, sw: 1.8, color: C.violetBright },
    { delay: 14, maxR: 1250, dur: 55, sw: 1.0, color: C.cyan         },
    { delay: 24, maxR: 1850, dur: 70, sw: 0.7, color: C.violet       },
  ];
  const RAY_N = 36;
  const rays = useMemo(() => Array.from({ length: RAY_N }, (_, i) => {
    const angle  = (i / RAY_N) * Math.PI * 2;
    const major  = i % 4 === 0;
    const med    = i % 2 === 0 && !major;
    const maxLen = major ? 650+(i%5)*95 : med ? 400+(i%7)*65 : 230+(i%3)*55;
    const COLS   = [C.cyan, C.violet, C.pink, "#ffffff", C.violetBright, C.cyan];
    return { angle, maxLen, color: COLS[i % COLS.length], major };
  }), []);

  return (
    <>
      {WAVES.map(({ delay, maxR, dur, sw, color }, wi) => {
        const ws = since - delay; if (ws < 0) return null;
        const wp  = Math.min(1, ws / dur);
        const rad = wp * maxR;
        const wOp = interpolate(wp, [0, 0.12, 1], [0, 0.9, 0], EL);
        return (
          <mesh key={wi} rotation={[Math.PI/2, 0, 0]}>
            <torusGeometry args={[rad, sw, 4, 128]} />
            <meshBasicMaterial color={color} transparent opacity={wOp} depthWrite={false} />
          </mesh>
        );
      })}
      {rayOp > 0.01 && rays.map(({ angle, maxLen, color, major }, i) => {
        const len = burstProg * maxLen;
        return (
          <lineSegments key={i}>
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[new Float32Array([
                0, 0, 0, Math.cos(angle)*len, Math.sin(angle)*len, 0,
              ]), 3]} />
            </bufferGeometry>
            <lineBasicMaterial color={color} transparent opacity={rayOp*(major?1:0.65)} />
          </lineSegments>
        );
      })}
    </>
  );
};
