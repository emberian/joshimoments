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

/**
 * A reconciled accounting figure, or its absence.
 *
 * Deliberately not `sol()`. For money the difference between "zero" and "not reconciled" is the
 * difference between flat and unknown, and a rendered `0.00000 SOL` cannot carry it -- a trader
 * reads that as flat. Glass never computes these figures; they arrive from a reconciled
 * accounting projection or they do not arrive.
 */
export function accountedSol(value: string | null, digits = 5): string {
  return value === null ? "Not reconciled" : `${Number(value).toFixed(digits)} SOL`;
}

/**
 * What to call a candidate the view names no ticker for.
 *
 * The mint is the identity the source actually supplied, so its leading characters stand in --
 * never a placeholder word, and never behind a `$`. The `$` prefix is reserved for a ticker the
 * view really carries, so an abbreviated mint can never be misread as one.
 */
export function candidateSymbol(symbol: string | null, mint: string): string {
  return symbol === null ? `${mint.slice(0, 6)}…` : `$${symbol}`;
}

/** A candidate display name, or an explicit statement that this view carries none. */
export function candidateName(name: string | null): string {
  return name ?? "No name in this view";
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

/**
 * How long ago something happened, in words, from a millisecond span.
 *
 * Deliberately coarse and deliberately never negative-looking: a readout whose receipt clock is
 * ahead of this browser's clock is a clock disagreement, not a measurement from the future, and it
 * says so rather than printing a minus sign that reads as a countdown.
 */
export function elapsedWords(milliseconds: number): string {
  if (!Number.isFinite(milliseconds)) return "an unreadable time";
  if (milliseconds < 0) return "less than a second (this browser's clock is behind the reading clock)";
  const seconds = Math.floor(milliseconds / 1000);
  if (seconds < 1) return "less than a second";
  if (seconds < 60) return `${seconds} second${seconds === 1 ? "" : "s"}`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"}`;
  const days = Math.floor(hours / 24);
  return `${days} days`;
}

/**
 * An instant this view does carry, plus its explicit absence. A null instant means the view
 * recorded none; it is never evidence that the moment did not happen, so it must not read as one.
 */
export function instantOrAbsent(value: string | null): string {
  return value === null ? "Not recorded" : `${clock(value)}Z`;
}

export function clock(value: string | null): string {
  if (value === null) return "Not recorded";
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
