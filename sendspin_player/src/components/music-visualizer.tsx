const BARS = 22;

// Pre-computed per-bar config — varied duration + delay for organic spectrum feel
const BAR_CONFIG = Array.from({ length: BARS }, (_, i) => {
  const duration = (0.55 + Math.abs(Math.sin(i * 2.3 + 0.7)) * 0.25 + Math.abs(Math.cos(i * 1.1)) * 0.15).toFixed(2);
  const delay = ((i / (BARS - 1)) * 0.32 + Math.abs(Math.sin(i * 3.1)) * 0.1).toFixed(3);
  return { duration, delay };
});

export function MusicVisualizer({ playing }: { playing: boolean }) {
  return (
    <div
      className={`flex items-end justify-center gap-[2px] h-8 overflow-hidden transition-opacity duration-500 ${
        playing ? "opacity-100" : "opacity-0 pointer-events-none"
      }`}
      aria-hidden="true"
    >
      {BAR_CONFIG.map(({ duration, delay }, i) => (
        <span
          key={i}
          className="w-[3px] shrink-0 rounded-full bg-primary"
          style={{
            height: "4px",
            opacity: 0.45 + Math.abs(Math.sin(i * 0.75)) * 0.55,
            animation: playing
              ? `playing-bar ${duration}s ease-in-out ${delay}s infinite`
              : "none",
          }}
        />
      ))}
    </div>
  );
}
