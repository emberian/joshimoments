export function compactUsd(value: string | null): string {
  if (value === null) return "Not observed";
  const numeric = Number(value);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(numeric);
}

export function sol(value: string | null, digits = 4): string {
  if (value === null) return "Not observed";
  return `${Number(value).toFixed(digits)} SOL`;
}

export function priceSol(value: string | null): string {
  if (value === null) return "Not observed";
  const numeric = Number(value);
  return `${numeric.toExponential(4)} SOL`;
}

export function basisPoints(value: string | null): string {
  if (value === null) return "Not observed";
  const numeric = Number(value) / 100;
  return `${numeric > 0 ? "+" : ""}${numeric.toFixed(2)}%`;
}

export function duration(seconds: string | null): string {
  if (seconds === null) return "Unknown age";
  const total = Number(seconds);
  if (total < 60) return `${total}s`;
  if (total < 3600) return `${Math.floor(total / 60)}m`;
  return `${Math.floor(total / 3600)}h ${Math.floor((total % 3600) / 60)}m`;
}

export function clock(value: string | null): string {
  if (value === null) return "Never";
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(new Date(value));
}

export function signedTone(value: string | null): "positive" | "negative" | "neutral" {
  if (value === null || Number(value) === 0) return "neutral";
  return Number(value) > 0 ? "positive" : "negative";
}

export function sentenceCase(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase());
}
