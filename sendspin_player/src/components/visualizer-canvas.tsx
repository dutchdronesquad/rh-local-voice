import { useEffect, useRef, type RefObject } from "react";

const BAR_COUNT = 48;

interface Props {
  analyserRef: RefObject<AnalyserNode | null>;
  playing: boolean;
}

export function VisualizerCanvas({ analyserRef, playing }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colorRef  = useRef<HTMLSpanElement>(null);
  const rafRef    = useRef<number>(0);
  const decayRef  = useRef(new Float32Array(BAR_COUNT));

  useEffect(() => {
    const canvas  = canvasRef.current;
    const colorEl = colorRef.current;
    if (!canvas || !colorEl) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    function resize() {
      if (!canvas) return;
      canvas.width  = canvas.offsetWidth  * devicePixelRatio;
      canvas.height = canvas.offsetHeight * devicePixelRatio;
    }
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    let cr = 96, cg = 165, cb = 250;
    function updateColor() {
      const m = getComputedStyle(colorEl!).color.match(/\d+/g);
      if (m?.length && m.length >= 3) { cr = +m[0]; cg = +m[1]; cb = +m[2]; }
    }
    updateColor();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", updateColor);

    const freqData = new Uint8Array(64);
    const decay    = decayRef.current;

    function draw() {
      rafRef.current = requestAnimationFrame(draw);
      const analyser = analyserRef.current;
      const w = canvas!.width;
      const h = canvas!.height;
      ctx!.clearRect(0, 0, w, h);

      if (analyser && playing) {
        analyser.getByteFrequencyData(freqData);
        for (let i = 0; i < BAR_COUNT; i++) {
          const bin = Math.floor((i / BAR_COUNT) * (freqData.length * 0.8));
          decay[i] = Math.max(decay[i] * 0.88, freqData[bin] / 255);
        }
      } else {
        let any = false;
        for (let i = 0; i < BAR_COUNT; i++) {
          if (decay[i] > 0.005) { decay[i] *= 0.93; any = true; }
          else decay[i] = 0;
        }
        if (!any) return;
      }

      const dpr    = devicePixelRatio;
      const gap    = 2 * dpr;
      const barW   = (w - gap * (BAR_COUNT - 1)) / BAR_COUNT;
      const radius = Math.min(barW / 2, 3 * dpr);

      for (let i = 0; i < BAR_COUNT; i++) {
        const v = decay[i];
        if (v < 0.005) continue;

        const barH = v * h * 0.88;
        const x    = i * (barW + gap);
        const barY = h - barH;

        // Fade from transparent at top to solid at bottom
        const grad = ctx!.createLinearGradient(0, barY, 0, h);
        grad.addColorStop(0,    `rgba(${cr},${cg},${cb},0)`);
        grad.addColorStop(0.35, `rgba(${cr},${cg},${cb},${+(v * 0.22).toFixed(3)})`);
        grad.addColorStop(1,    `rgba(${cr},${cg},${cb},${+(v * 0.45).toFixed(3)})`);

        ctx!.fillStyle = grad;
        ctx!.beginPath();
        ctx!.roundRect(x, barY, barW, barH, [radius, radius, 0, 0]);
        ctx!.fill();
      }
    }

    draw();
    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      mq.removeEventListener("change", updateColor);
    };
  }, [playing, analyserRef]);

  return (
    <>
      <span ref={colorRef} className="text-success absolute opacity-0 pointer-events-none" aria-hidden="true" />
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" aria-hidden="true" />
    </>
  );
}
