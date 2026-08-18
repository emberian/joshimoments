import { browser } from "wxt/browser";

import type {
  CompanionState,
  OriginId,
  RuntimeRequest,
  RuntimeResponse,
} from "../../src/contracts";
import "./style.css";

function requiredElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`missing popup element: ${id}`);
  }
  return element as T;
}

const health = requiredElement<HTMLSpanElement>("health");
const captureToggle = requiredElement<HTMLButtonElement>("capture-toggle");
const rawCapture = requiredElement<HTMLInputElement>("raw-capture");
const flush = requiredElement<HTMLButtonElement>("flush");
const queued = requiredElement<HTMLElement>("queued");
const accepted = requiredElement<HTMLElement>("accepted");
const delivered = requiredElement<HTMLElement>("delivered");
const dropped = requiredElement<HTMLElement>("dropped");
const lastCapture = requiredElement<HTMLElement>("last-capture");
const lastDelivery = requiredElement<HTMLElement>("last-delivery");
const lastError = requiredElement<HTMLParagraphElement>("last-error");

const originInputs: Record<OriginId, HTMLInputElement> = {
  "pump-frontend": requiredElement<HTMLInputElement>("origin-pump-frontend"),
  "coin-communities": requiredElement<HTMLInputElement>("origin-coin-communities"),
  "pump-profile": requiredElement<HTMLInputElement>("origin-pump-profile"),
};

let currentState: CompanionState | null = null;

function formatBytes(bytes: number): string {
  if (bytes < 1_024) {
    return `${bytes} B`;
  }
  return `${(bytes / 1_024).toFixed(1)} KiB`;
}

function formatTime(value: string | null): string {
  return value === null ? "Never" : new Date(value).toLocaleTimeString();
}

function render(state: CompanionState): void {
  currentState = state;
  health.textContent = state.health[0]?.toUpperCase() + state.health.slice(1);
  health.dataset.health = state.health;
  captureToggle.textContent = state.config.captureEnabled ? "Pause capture" : "Start capture";
  captureToggle.setAttribute("aria-pressed", String(state.config.captureEnabled));
  rawCapture.checked = state.config.rawCaptureEnabled;
  for (const [originId, input] of Object.entries(originInputs) as [OriginId, HTMLInputElement][]) {
    input.checked = state.config.origins[originId];
  }
  queued.textContent = `${state.queueDepth} acquisitions + ${state.gapDepth} gaps / ${formatBytes(state.queueBytes)}`;
  accepted.textContent = String(state.accepted);
  delivered.textContent = String(state.delivered);
  dropped.textContent = String(state.dropped);
  lastCapture.textContent = formatTime(state.lastCaptureAt);
  lastDelivery.textContent = formatTime(state.lastDeliveryAt);
  lastError.hidden = state.lastError === null;
  lastError.textContent = state.lastError ?? "";
}

async function send(request: RuntimeRequest): Promise<void> {
  const response = await browser.runtime.sendMessage<RuntimeRequest, RuntimeResponse>(request);
  if (!response.ok) {
    throw new Error(response.error);
  }
  if (response.state !== undefined) {
    render(response.state);
  }
}

captureToggle.addEventListener("click", () => {
  void send({
    kind: "set-capture-enabled",
    enabled: !(currentState?.config.captureEnabled ?? false),
  });
});

rawCapture.addEventListener("change", () => {
  void send({ kind: "set-raw-capture-enabled", enabled: rawCapture.checked });
});

for (const [originId, input] of Object.entries(originInputs) as [OriginId, HTMLInputElement][]) {
  input.addEventListener("change", () => {
    void send({ kind: "set-origin-enabled", originId, enabled: input.checked });
  });
}

flush.addEventListener("click", () => {
  void send({ kind: "flush-now" });
});

void send({ kind: "get-state" });
