import React, { useEffect, useRef, useState } from 'react';

/**
 * Ambient.tsx — the BroPS AI-OS ambient layer + power-on ignition, ported from
 * the canonical `brops-aios` design mockup into React.
 *
 * It renders (behind everything, z-index negative) the aurora bands, the living
 * mesh field (a <canvas> painted by requestAnimationFrame), the grid/horizon/
 * scanline/vignette overlays, the ignition ember + shimmer, and the cursor-follow
 * light blob. The shared SVG <defs> (the GLYPH cyan gradient + sparkline fill)
 * live here too so every `.mark` and sparkline in any view can reference them.
 *
 * Every animation honours `prefers-reduced-motion`: with motion reduced the mesh
 * paints one static frame, the pointer light stops tracking, and ignition is
 * instant. Nothing here is interactive or load-bearing — it is pure atmosphere.
 */

/** The GLYPH power mark — a neon "power symbol" (arc + stem), stroked twice
 *  (tube + core) so the CSS can light it. viewBox + paths verbatim from the mockup. */
export function Glyph() {
  return (
    <svg viewBox="-118 -130 236 250" aria-hidden="true">
      <g className="tube">
        <path d="M -53.4 -84.6 A 100 100 0 1 0 53.4 -84.6" />
        <line x1="0" y1="-113" x2="0" y2="-27" />
      </g>
      <g className="core">
        <path d="M -53.4 -84.6 A 100 100 0 1 0 53.4 -84.6" />
        <line x1="0" y1="-113" x2="0" y2="-27" />
      </g>
    </svg>
  );
}

/** A sized GLYPH mark. `state` maps to the mockup's mark modifiers
 *  (live / boot / thinking / idle / alert / on). */
export function Mark({
  state = '',
  size = 40,
  className = '',
  style,
}: {
  state?: string;
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <span
      className={`mark ${state} ${className}`.trim()}
      style={{ width: size, height: size, ...style }}
    >
      <Glyph />
    </span>
  );
}

function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** The living mesh field — a constellation of drifting agent-nodes with a bright
 *  core, linked when near. Ported verbatim from the mockup's `mesh()` IIFE into a
 *  canvas effect with proper teardown. */
function useMesh(canvasRef: React.RefObject<HTMLCanvasElement | null>) {
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    const reduced = prefersReducedMotion();
    const AGENTS = 38;
    let W = 0;
    let H = 0;
    let DPR = 1;
    let nodes: Array<{ x: number; y: number; vx?: number; vy?: number; r: number; pulse?: number; core: boolean }> = [];
    let raf = 0;

    function seed() {
      DPR = Math.min(devicePixelRatio || 1, 2);
      W = cv!.width = innerWidth * DPR;
      H = cv!.height = innerHeight * DPR;
      cv!.style.width = innerWidth + 'px';
      cv!.style.height = innerHeight + 'px';
      nodes = [];
      nodes.push({ x: W * 0.72, y: H * 0.3, r: 3.4 * DPR, core: true });
      for (let i = 0; i < AGENTS; i++)
        nodes.push({
          x: Math.random() * W,
          y: Math.random() * H,
          vx: (Math.random() - 0.5) * 0.16 * DPR,
          vy: (Math.random() - 0.5) * 0.16 * DPR,
          r: (Math.random() * 1.1 + 0.8) * DPR,
          pulse: Math.random() * Math.PI * 2,
          core: false,
        });
    }
    const link = () => 168 * DPR;

    function draw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, W, H);
      const L = link();
      for (const n of nodes) {
        if (n.core) continue;
        n.x += n.vx!;
        n.y += n.vy!;
        n.pulse! += 0.012;
        if (n.x < -20) n.x = W + 20;
        if (n.x > W + 20) n.x = -20;
        if (n.y < -20) n.y = H + 20;
        if (n.y > H + 20) n.y = -20;
      }
      for (let i = 0; i < nodes.length; i++)
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d = Math.hypot(dx, dy);
          if (d > L) continue;
          const near = 1 - d / L;
          const isCore = a.core || b.core;
          ctx.strokeStyle = isCore ? `rgba(125,231,255,${near * 0.3})` : `rgba(56,189,248,${near * 0.13})`;
          ctx.lineWidth = (isCore ? 1.05 : 0.65) * DPR;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      for (const n2 of nodes) {
        if (n2.core) {
          const g = ctx.createRadialGradient(n2.x, n2.y, 0, n2.x, n2.y, 26 * DPR);
          g.addColorStop(0, 'rgba(234,240,248,.95)');
          g.addColorStop(0.28, 'rgba(125,231,255,.55)');
          g.addColorStop(0.62, 'rgba(10,132,255,.18)');
          g.addColorStop(1, 'rgba(10,132,255,0)');
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(n2.x, n2.y, 26 * DPR, 0, 7);
          ctx.fill();
        } else {
          const al = 0.3 + Math.sin(n2.pulse!) * 0.18;
          ctx.fillStyle = `rgba(56,189,248,${al})`;
          ctx.beginPath();
          ctx.arc(n2.x, n2.y, n2.r, 0, 7);
          ctx.fill();
        }
      }
      if (!reduced) raf = requestAnimationFrame(draw);
    }

    const onResize = () => {
      seed();
      if (reduced) draw();
    };
    seed();
    draw();
    addEventListener('resize', onResize, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      removeEventListener('resize', onResize);
    };
  }, [canvasRef]);
}

/** Cursor-follow light blob + per-surface spotlight + `.tilt` parallax.
 *  Ported from the mockup's `pointer()` IIFE. Writes CSS custom properties on
 *  :root and on the hovered `.surface`/`.tilt`; reduced-motion skips the blob. */
function usePointerLight() {
  useEffect(() => {
    const reduced = prefersReducedMotion();
    const root = document.documentElement;
    let px = innerWidth / 2;
    let py = innerHeight * 0.4;
    let queued = false;
    root.style.setProperty('--cx', px + 'px');
    root.style.setProperty('--cy', py + 'px');

    const onMove = (e: PointerEvent) => {
      px = e.clientX;
      py = e.clientY;
      const t = e.target as Element | null;
      const surf = t?.closest?.('.surface, .card') as HTMLElement | null;
      if (surf) {
        const r = surf.getBoundingClientRect();
        surf.style.setProperty('--mx', ((e.clientX - r.left) / r.width) * 100 + '%');
        surf.style.setProperty('--my', ((e.clientY - r.top) / r.height) * 100 + '%');
      }
      const tl = t?.closest?.('.tilt') as HTMLElement | null;
      if (tl) {
        const tr = tl.getBoundingClientRect();
        const rx = (e.clientX - tr.left) / tr.width - 0.5;
        const ry = (e.clientY - tr.top) / tr.height - 0.5;
        tl.style.setProperty('--rx', (rx * 6).toFixed(2) + 'deg');
        tl.style.setProperty('--ry', (-ry * 6).toFixed(2) + 'deg');
      }
      if (!queued && !reduced) {
        queued = true;
        requestAnimationFrame(() => {
          root.style.setProperty('--cx', px + 'px');
          root.style.setProperty('--cy', py + 'px');
          queued = false;
        });
      }
    };
    const onOut = (e: PointerEvent) => {
      const tl = (e.target as Element | null)?.closest?.('.tilt') as HTMLElement | null;
      if (tl) {
        tl.style.setProperty('--rx', '0deg');
        tl.style.setProperty('--ry', '0deg');
      }
    };
    addEventListener('pointermove', onMove, { passive: true });
    addEventListener('pointerout', onOut, { passive: true });
    return () => {
      removeEventListener('pointermove', onMove);
      removeEventListener('pointerout', onOut);
    };
  }, []);
}

/**
 * The power-on gate. On first launch the OS sits "cold"; pressing the mark (or
 * Space) runs the ignition cinematic — the mark boots, then `body.ignited`
 * lights the ambient layer and the gate lifts away. Persisted per browser so it
 * only greets on a true cold start. Reduced-motion ignites instantly.
 */
export function useIgnition(): {
  ignited: boolean;
  gateLift: boolean;
  powerOn: () => void;
  gateMarkRef: React.RefObject<HTMLSpanElement | null>;
} {
  const persistedKey = 'brops.ignited';
  const [ignited, setIgnited] = useState(false);
  const [gateLift, setGateLift] = useState(false);
  const gateMarkRef = useRef<HTMLSpanElement>(null);

  // On a warm start (already ignited this session), skip the gate entirely.
  useEffect(() => {
    let warm = false;
    try {
      warm = sessionStorage.getItem(persistedKey) === '1';
    } catch {
      /* storage unavailable — treat as cold */
    }
    if (warm) {
      setIgnited(true);
      setGateLift(true);
      document.body.classList.add('ignited');
    }
  }, []);

  const powerOn = React.useCallback(() => {
    if (gateLift) return;
    const reduced = prefersReducedMotion();
    gateMarkRef.current?.classList.add('boot');
    window.setTimeout(
      () => {
        setGateLift(true);
        setIgnited(true);
        document.body.classList.add('ignited');
        try {
          sessionStorage.setItem(persistedKey, '1');
        } catch {
          /* ignore */
        }
      },
      reduced ? 0 : 900,
    );
  }, [gateLift]);

  // Space powers on while the gate is up.
  useEffect(() => {
    if (gateLift) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        e.preventDefault();
        powerOn();
      }
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [gateLift, powerOn]);

  return { ignited, gateLift, powerOn, gateMarkRef };
}

/** The fixed ambient backdrop + shared SVG defs. Render once, near the app root. */
export function AmbientLayer() {
  const meshRef = useRef<HTMLCanvasElement>(null);
  useMesh(meshRef);
  usePointerLight();
  return (
    <>
      {/* shared SVG defs: the GLYPH cyan gradient + sparkline fill gradient */}
      <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
        <defs>
          <linearGradient id="menqCyan" x1="0" y1="-130" x2="0" y2="120" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#7DE7FF" />
            <stop offset=".5" stopColor="#38BDF8" />
            <stop offset="1" stopColor="#0EA5E9" />
          </linearGradient>
          <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#38BDF8" stopOpacity=".35" />
            <stop offset="1" stopColor="#38BDF8" stopOpacity="0" />
          </linearGradient>
        </defs>
      </svg>

      <div className="aurora" aria-hidden="true">
        <i className="band a" />
        <i className="band b" />
        <i className="band c" />
        <i className="band d" />
      </div>
      <canvas id="mesh" ref={meshRef} aria-hidden="true" />
      <div className="gridlay" aria-hidden="true" />
      <div className="horizon" aria-hidden="true" />
      <div className="scanline" aria-hidden="true" />
      <div id="ember" aria-hidden="true" />
      <div className="shimmer" aria-hidden="true" />
      <div className="vignette" aria-hidden="true" />
      <div id="cursorlight" aria-hidden="true" />
    </>
  );
}
