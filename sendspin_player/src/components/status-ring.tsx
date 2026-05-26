export type ConnectionState = "disconnected" | "connecting" | "connected" | "playing" | "reconnecting" | "error";

const arcColor: Record<ConnectionState, string> = {
  disconnected: "stroke-stroke-muted",
  connecting:   "stroke-warning",
  reconnecting: "stroke-warning",
  connected:    "stroke-success",
  playing:      "stroke-primary",
  error:        "stroke-destructive",
};

const dotColor: Record<ConnectionState, string> = {
  disconnected: "bg-stroke-muted",
  connecting:   "bg-warning shadow-[0_0_8px_var(--color-warning)]",
  reconnecting: "bg-warning shadow-[0_0_8px_var(--color-warning)]",
  connected:    "bg-success",
  playing:      "bg-primary shadow-[0_0_8px_var(--color-primary)]",
  error:        "bg-destructive",
};

// r=30 circle, circumference ≈ 188.5
const CIRC = 2 * Math.PI * 30;
const ARC_LEN = 47; // ~quarter-circle comet arc while spinning

export function StatusRing({ state }: { state: ConnectionState }) {
  const spinning = state === "connecting" || state === "reconnecting";
  const pulsing  = state === "playing";

  return (
    <div className="relative size-[58px]">
      {/* Pulse rings — always mounted, opacity fade avoids mount/unmount snap */}
      <span
        className={`absolute inset-[9px] rounded-full border border-[rgb(79_110_247/0.45)] transition-opacity duration-500 ${
          pulsing ? "animate-[playback-pulse_1.65s_ease-out_infinite]" : "opacity-0"
        }`}
        aria-hidden="true"
      />
      <span
        className={`absolute inset-[3px] rounded-full border border-[rgb(79_110_247/0.25)] transition-opacity duration-500 ${
          pulsing ? "animate-[playback-pulse_1.65s_ease-out_infinite]" : "opacity-0"
        }`}
        style={{ animationDelay: "0.45s" }}
        aria-hidden="true"
      />

      <svg viewBox="0 0 72 72" className="size-full" aria-hidden="true">
        {/* Track */}
        <circle cx="36" cy="36" r="30" className="fill-none stroke-muted [stroke-width:4]" />

        {/* Spinning: fixed-length arc that rotates — no dashoffset weirdness */}
        {spinning && (
          <g
            className={`animate-[spin_1.5s_linear_infinite] ${arcColor[state]}`}
            style={{ transformOrigin: "36px 36px" }}
          >
            <circle
              cx="36" cy="36" r="30"
              className="fill-none [stroke-width:4] [stroke-linecap:round]"
              style={{ strokeDasharray: `${ARC_LEN} ${CIRC - ARC_LEN}` }}
            />
          </g>
        )}

        {/* Not spinning: full arc, color transition between states */}
        {!spinning && (
          <circle
            cx="36" cy="36" r="30"
            className={`fill-none [stroke-width:4] [stroke-linecap:round] transition-[stroke] duration-300 [transform:rotate(-90deg)] [transform-origin:50%_50%] ${arcColor[state]}`}
            style={{ strokeDasharray: CIRC }}
          />
        )}
      </svg>

      {/* Center dot / playing bars */}
      <div className="absolute inset-0 flex items-center justify-center">
        {pulsing ? (
          <div className="flex h-[22px] items-center justify-center gap-[3px]" aria-hidden="true">
            {[0, 0.08, 0.16, 0.24, 0.32].map((delay, i) => (
              <span
                key={i}
                className="w-[3px] rounded-full bg-primary animate-[playing-bar_0.72s_ease-in-out_infinite] shadow-[0_0_8px_rgb(79_110_247/0.65)]"
                style={{ height: "8px", animationDelay: `${delay}s` }}
              />
            ))}
          </div>
        ) : (
          <span className={`size-[10px] rounded-full transition-colors duration-300 ${dotColor[state]}`} />
        )}
      </div>
    </div>
  );
}
