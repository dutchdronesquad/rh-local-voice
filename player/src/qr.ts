const VERSION = 4;
const SIZE = 17 + VERSION * 4;
const DATA_CODEWORDS = 80;
const ECC_CODEWORDS = 20;
const MAX_BYTES = 78;
const FORMAT_MASK = 0x5412;
const FORMAT_GENERATOR = 0x537;

type Cell = boolean | null;

export function qrMatrix(text: string): boolean[][] {
  const data = new TextEncoder().encode(text);
  if (data.length > MAX_BYTES) {
    throw new Error(`QR text is too long (${data.length}/${MAX_BYTES} bytes)`);
  }

  const modules: Cell[][] = Array.from({ length: SIZE }, () => Array<Cell>(SIZE).fill(null));
  const reserved: boolean[][] = Array.from({ length: SIZE }, () => Array<boolean>(SIZE).fill(false));

  drawFunctionPatterns(modules, reserved);
  drawCodewords(modules, reserved, [...encodeData(data), ...reedSolomonRemainder(encodeData(data), ECC_CODEWORDS)]);
  drawFormatBits(modules, reserved);

  return modules.map((row) => row.map(Boolean));
}

function encodeData(data: Uint8Array): number[] {
  const bits: number[] = [];
  appendBits(bits, 0b0100, 4);
  appendBits(bits, data.length, 8);
  for (const byte of data) appendBits(bits, byte, 8);

  const capacity = DATA_CODEWORDS * 8;
  appendBits(bits, 0, Math.min(4, capacity - bits.length));
  while (bits.length % 8 !== 0) bits.push(0);

  const codewords = bitsToBytes(bits);
  for (let pad = 0xec; codewords.length < DATA_CODEWORDS; pad ^= 0xec ^ 0x11) {
    codewords.push(pad);
  }
  return codewords;
}

function appendBits(bits: number[], value: number, length: number): void {
  for (let i = length - 1; i >= 0; i -= 1) {
    bits.push((value >>> i) & 1);
  }
}

function bitsToBytes(bits: number[]): number[] {
  const bytes: number[] = [];
  for (let i = 0; i < bits.length; i += 8) {
    let byte = 0;
    for (let j = 0; j < 8; j += 1) byte = (byte << 1) | bits[i + j];
    bytes.push(byte);
  }
  return bytes;
}

function drawFunctionPatterns(modules: Cell[][], reserved: boolean[][]): void {
  drawFinder(modules, reserved, 0, 0);
  drawFinder(modules, reserved, SIZE - 7, 0);
  drawFinder(modules, reserved, 0, SIZE - 7);
  drawAlignment(modules, reserved, 26, 26);

  for (let i = 8; i < SIZE - 8; i += 1) {
    setFunction(modules, reserved, i, 6, i % 2 === 0);
    setFunction(modules, reserved, 6, i, i % 2 === 0);
  }

  setFunction(modules, reserved, 8, VERSION * 4 + 9, true);
  reserveFormatAreas(modules, reserved);
}

function drawFinder(modules: Cell[][], reserved: boolean[][], left: number, top: number): void {
  for (let y = -1; y <= 7; y += 1) {
    for (let x = -1; x <= 7; x += 1) {
      const xx = left + x;
      const yy = top + y;
      if (xx < 0 || xx >= SIZE || yy < 0 || yy >= SIZE) continue;
      const onPattern = x >= 0 && x <= 6 && y >= 0 && y <= 6;
      const dark = onPattern && (x === 0 || x === 6 || y === 0 || y === 6 || (x >= 2 && x <= 4 && y >= 2 && y <= 4));
      setFunction(modules, reserved, xx, yy, dark);
    }
  }
}

function drawAlignment(modules: Cell[][], reserved: boolean[][], cx: number, cy: number): void {
  for (let y = -2; y <= 2; y += 1) {
    for (let x = -2; x <= 2; x += 1) {
      setFunction(modules, reserved, cx + x, cy + y, Math.max(Math.abs(x), Math.abs(y)) === 2 || (x === 0 && y === 0));
    }
  }
}

function reserveFormatAreas(modules: Cell[][], reserved: boolean[][]): void {
  for (let i = 0; i <= 8; i += 1) {
    if (i !== 6) {
      setFunction(modules, reserved, 8, i, false);
      setFunction(modules, reserved, i, 8, false);
    }
  }
  for (let i = 0; i < 8; i += 1) setFunction(modules, reserved, SIZE - 1 - i, 8, false);
  for (let i = 8; i < 15; i += 1) setFunction(modules, reserved, 8, SIZE - 15 + i, false);
}

function setFunction(modules: Cell[][], reserved: boolean[][], x: number, y: number, value: boolean): void {
  modules[y][x] = value;
  reserved[y][x] = true;
}

function drawCodewords(modules: Cell[][], reserved: boolean[][], codewords: number[]): void {
  const bits = codewords.flatMap((codeword) => Array.from({ length: 8 }, (_, i) => (codeword >>> (7 - i)) & 1));
  let bitIndex = 0;
  let upward = true;

  for (let right = SIZE - 1; right >= 1; right -= 2) {
    if (right === 6) right -= 1;
    for (let offset = 0; offset < SIZE; offset += 1) {
      const y = upward ? SIZE - 1 - offset : offset;
      for (let column = 0; column < 2; column += 1) {
        const x = right - column;
        if (reserved[y][x]) continue;
        const bit = bitIndex < bits.length ? bits[bitIndex] === 1 : false;
        modules[y][x] = bit !== mask(x, y);
        bitIndex += 1;
      }
    }
    upward = !upward;
  }
}

function mask(x: number, y: number): boolean {
  return (x + y) % 2 === 0;
}

function drawFormatBits(modules: Cell[][], reserved: boolean[][]): void {
  const bits = formatBits();
  for (let i = 0; i <= 5; i += 1) setFunction(modules, reserved, 8, i, bit(bits, i));
  setFunction(modules, reserved, 8, 7, bit(bits, 6));
  setFunction(modules, reserved, 8, 8, bit(bits, 7));
  setFunction(modules, reserved, 7, 8, bit(bits, 8));
  for (let i = 9; i < 15; i += 1) setFunction(modules, reserved, 14 - i, 8, bit(bits, i));
  for (let i = 0; i < 8; i += 1) setFunction(modules, reserved, SIZE - 1 - i, 8, bit(bits, i));
  for (let i = 8; i < 15; i += 1) setFunction(modules, reserved, 8, SIZE - 15 + i, bit(bits, i));
}

function formatBits(): number {
  const data = 0b01000;
  let remainder = data << 10;
  for (let i = 14; i >= 10; i -= 1) {
    if (bit(remainder, i)) remainder ^= FORMAT_GENERATOR << (i - 10);
  }
  return ((data << 10) | remainder) ^ FORMAT_MASK;
}

function bit(value: number, index: number): boolean {
  return ((value >>> index) & 1) !== 0;
}

function reedSolomonRemainder(data: number[], degree: number): number[] {
  const generator = reedSolomonGenerator(degree);
  const result = [...data, ...Array<number>(degree).fill(0)];
  for (let i = 0; i < data.length; i += 1) {
    const factor = result[i];
    if (factor === 0) continue;
    for (let j = 0; j < generator.length; j += 1) {
      result[i + j] ^= gfMultiply(generator[j], factor);
    }
  }
  return result.slice(data.length);
}

function reedSolomonGenerator(degree: number): number[] {
  let generator = [1];
  for (let i = 0; i < degree; i += 1) {
    const next = Array<number>(generator.length + 1).fill(0);
    const root = gfPow(i);
    for (let j = 0; j < generator.length; j += 1) {
      next[j] ^= generator[j];
      next[j + 1] ^= gfMultiply(generator[j], root);
    }
    generator = next;
  }
  return generator;
}

function gfPow(power: number): number {
  let value = 1;
  for (let i = 0; i < power; i += 1) value = gfMultiply(value, 2);
  return value;
}

function gfMultiply(left: number, right: number): number {
  let product = 0;
  for (let i = 0; i < 8; i += 1) {
    if (((right >>> i) & 1) !== 0) product ^= left;
    left <<= 1;
    if ((left & 0x100) !== 0) left ^= 0x11d;
  }
  return product & 0xff;
}
