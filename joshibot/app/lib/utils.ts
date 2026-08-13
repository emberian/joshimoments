import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function shortAddress(value: string) {
  if (!value) return "—";
  return `${value.slice(0, 5)}…${value.slice(-5)}`;
}

export function number(value: string | number | null | undefined, digits = 3) {
  if (value == null || value === "") return "—";
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(parsed);
}

export function age(iso: string | null | undefined, now: number) {
  if (!iso) return "never";
  const timestamp = new Date(iso).getTime();
  if (!Number.isFinite(timestamp)) return "time invalid";
  const seconds = Math.max(0, Math.round((now - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export const BASE58_ADDRESS = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
