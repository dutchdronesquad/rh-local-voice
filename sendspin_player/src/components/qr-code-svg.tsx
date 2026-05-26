import { qrMatrix } from "@/qr";

export function QrCodeSvg({ text }: { text: string }) {
  try {
    const matrix = qrMatrix(text);
    const size = matrix.length;
    const padding = 4;
    return (
      <svg
        viewBox={`0 0 ${size + padding * 2} ${size + padding * 2}`}
        className="mx-auto block w-[min(100%-2rem,280px)] h-auto rounded-lg"
        role="img"
        aria-label="QR code for this player"
      >
        <rect width={size + padding * 2} height={size + padding * 2} fill="white" />
        {matrix.map((row, y) =>
          row.map(
            (filled, x) =>
              filled && (
                <rect key={`${x}-${y}`} x={x + padding} y={y + padding} width="1" height="1" fill="black" />
              ),
          ),
        )}
      </svg>
    );
  } catch (error) {
    return (
      <p className="p-4 text-center text-sm text-destructive">
        {error instanceof Error ? error.message : "Cannot render QR code"}
      </p>
    );
  }
}
