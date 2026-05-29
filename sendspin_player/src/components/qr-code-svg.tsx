import { qrMatrix } from "@/qr";

// QR finder patterns are 7×7 squares at the three corners
function isFinderModule(x: number, y: number, size: number): boolean {
  if (x <= 6 && y <= 6) return true;
  if (x >= size - 7 && y <= 6) return true;
  if (x <= 6 && y >= size - 7) return true;
  return false;
}

export function QrCodeSvg({ text }: { text: string }) {
  let matrix: boolean[][];

  try {
    matrix = qrMatrix(text);
  } catch (error) {
    return (
      <p className="p-4 text-center text-sm text-destructive">
        {error instanceof Error ? error.message : "Cannot render QR code"}
      </p>
    );
  }

  const size = matrix.length;
  const padding = 4;
  const total = size + padding * 2;

  return (
    <div
      className="mx-auto w-[min(100%-2rem,240px)] rounded-2xl p-[3px]"
      style={{ background: "linear-gradient(135deg, var(--primary) 0%, var(--success) 100%)" }}
    >
      <svg
        viewBox={`0 0 ${total} ${total}`}
        className="block w-full h-auto rounded-[14px]"
        role="img"
        aria-label="QR code for this player"
      >
        <rect width={total} height={total} fill="var(--card)" />
        {matrix.map((row, y) =>
          row.map((filled, x) => {
            if (!filled) return null;
            const finder = isFinderModule(x, y, size);
            return (
              <rect
                key={`${x}-${y}`}
                x={x + padding + 0.08}
                y={y + padding + 0.08}
                width="0.84"
                height="0.84"
                rx={finder ? "0.14" : "0.32"}
                fill={finder ? "var(--primary)" : "var(--foreground)"}
              />
            );
          }),
        )}
      </svg>
    </div>
  );
}
