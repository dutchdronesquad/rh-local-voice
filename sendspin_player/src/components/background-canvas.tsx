import { useEffect, useRef, type RefObject } from "react";

type RGB = [number, number, number];

interface OrbDef {
  bx: number; by: number; // base position (0–1 normalized)
  rx: number; ry: number; // motion radius (normalized)
  px: number; py: number; // motion period (seconds)
  phase: number;
  baseR: number;          // base radius as fraction of min(w,h)
  role: "primary" | "success" | "mix";
  bin: number;            // frequency bin index for audio reactivity
}

const ORBS: OrbDef[] = [
  { bx: 0.15, by: 0.20, rx: 0.12, ry: 0.10, px: 9.3,  py: 7.8,  phase: 0,   baseR: 0.58, role: "primary", bin: 2  },
  { bx: 0.85, by: 0.80, rx: 0.10, ry: 0.12, px: 11.7, py: 13.2, phase: 2.1, baseR: 0.52, role: "success", bin: 8  },
  { bx: 0.72, by: 0.14, rx: 0.08, ry: 0.07, px: 7.1,  py: 8.9,  phase: 4.2, baseR: 0.36, role: "primary", bin: 5  },
  { bx: 0.18, by: 0.86, rx: 0.09, ry: 0.08, px: 13.4, py: 10.1, phase: 1.5, baseR: 0.33, role: "success", bin: 12 },
  { bx: 0.55, by: 0.50, rx: 0.06, ry: 0.07, px: 6.2,  py: 9.3,  phase: 3.3, baseR: 0.24, role: "mix",     bin: 16 },
];

function resolveRgb(el: HTMLSpanElement | null, fallback: RGB): RGB {
  if (!el) return fallback;
  const m = getComputedStyle(el).color.match(/\d+/g);
  return m && m.length >= 3 ? [+m[0], +m[1], +m[2]] : fallback;
}

export function BackgroundCanvas({
  analyserRef,
  playing,
}: {
  analyserRef: RefObject<AnalyserNode | null>;
  playing: boolean;
}) {
  const canvasRef  = useRef<HTMLCanvasElement>(null);
  const primaryRef = useRef<HTMLSpanElement>(null);
  const successRef = useRef<HTMLSpanElement>(null);
  const rafRef     = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    function resize() {
      canvas!.width  = window.innerWidth;
      canvas!.height = window.innerHeight;
    }
    window.addEventListener("resize", resize);
    resize();

    let prim: RGB = [251, 146,  60];
    let succ: RGB = [ 96, 165, 250];
    function updateColors() {
      prim = resolveRgb(primaryRef.current, prim);
      succ = resolveRgb(successRef.current, succ);
    }
    updateColors();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", updateColors);

    const freqData  = new Uint8Array(64);
    const orbDecay  = ORBS.map(() => 0);
    let   haloDecay = 0;
    const t0        = performance.now();

    function draw(ts: number) {
      rafRef.current = requestAnimationFrame(draw);
      const t        = (ts - t0) / 1000;
      const w        = canvas!.width;
      const h        = canvas!.height;
      const min      = Math.min(w, h);
      const analyser = analyserRef.current;

      ctx!.clearRect(0, 0, w, h);

      if (analyser && playing) {
        analyser.getByteFrequencyData(freqData);
        const bass = (freqData[0] + freqData[1] + freqData[2] + freqData[3]) / (4 * 255);
        haloDecay = Math.max(haloDecay * 0.88, bass);
        ORBS.forEach((o, i) => {
          orbDecay[i] = Math.max(orbDecay[i] * 0.86, freqData[o.bin] / 255);
        });
      } else {
        haloDecay *= 0.97;
        ORBS.forEach((_, i) => { orbDecay[i] *= 0.97; });
      }

      // ── Central halo ───────────────────────────────────────────────────────
      // Large soft glow centered behind the card, pulses with bass amplitude
      {
        const r    = min * (0.52 + haloDecay * 0.4);
        const a    = 0.05 + haloDecay * 0.18;
        const grad = ctx!.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, r);
        grad.addColorStop(0,   `rgba(${prim[0]},${prim[1]},${prim[2]},${+(a * 2.2).toFixed(3)})`);
        grad.addColorStop(0.4, `rgba(${prim[0]},${prim[1]},${prim[2]},${+a.toFixed(3)})`);
        grad.addColorStop(1,   "rgba(0,0,0,0)");
        ctx!.fillStyle = grad;
        ctx!.fillRect(0, 0, w, h);
      }

      // ── Floating orbs ──────────────────────────────────────────────────────
      ORBS.forEach((o, i) => {
        const v  = orbDecay[i];
        // Lissajous-like paths: two overlapping sine/cosine waves per axis
        const cx = (o.bx + Math.sin(t / o.px) * o.rx + Math.sin(t / o.px * 1.31 + o.phase) * o.rx * 0.28) * w;
        const cy = (o.by + Math.cos(t / o.py) * o.ry + Math.cos(t / o.py * 0.73 + o.phase + 1.1) * o.ry * 0.22) * h;
        const r  = o.baseR * min * (1 + v * 0.42);
        const rgb: RGB = o.role === "primary" ? prim
          : o.role === "success" ? succ
          : [(prim[0] + succ[0]) >> 1, (prim[1] + succ[1]) >> 1, (prim[2] + succ[2]) >> 1];
        const a = playing ? 0.17 + v * 0.26 : 0.14;

        const grad = ctx!.createRadialGradient(cx, cy, 0, cx, cy, r);
        grad.addColorStop(0,    `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${+(a * 1.6).toFixed(3)})`);
        grad.addColorStop(0.45, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${+a.toFixed(3)})`);
        grad.addColorStop(1,    "rgba(0,0,0,0)");

        ctx!.fillStyle = grad;
        ctx!.beginPath();
        ctx!.arc(cx, cy, r, 0, Math.PI * 2);
        ctx!.fill();
      });

      // ── Vignette ───────────────────────────────────────────────────────────
      {
        const r    = Math.max(w, h) * 0.78;
        const grad = ctx!.createRadialGradient(w / 2, h / 2, r * 0.28, w / 2, h / 2, r);
        grad.addColorStop(0, "rgba(0,0,0,0)");
        grad.addColorStop(1, "rgba(0,0,0,0.72)");
        ctx!.fillStyle = grad;
        ctx!.fillRect(0, 0, w, h);
      }
    }

    draw(performance.now());
    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", resize);
      mq.removeEventListener("change", updateColors);
    };
  }, [playing, analyserRef]);

  return (
    <>
      {/* Hidden elements to resolve CSS color vars for canvas use */}
      <span ref={primaryRef} className="text-primary sr-only" aria-hidden="true" />
      <span ref={successRef} className="text-success sr-only" aria-hidden="true" />
      <canvas ref={canvasRef} className="fixed inset-0 z-0 pointer-events-none" aria-hidden="true" />
    </>
  );
}
