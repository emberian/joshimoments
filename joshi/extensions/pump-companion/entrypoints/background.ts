import { browser } from "wxt/browser";

import {
  CATALOG_BINDING_STORAGE_KEY,
  CONFIG_STORAGE_KEY,
  INSTALLATION_STORAGE_KEY,
  MAX_BATCH_BYTES,
  MAX_BATCH_ITEMS,
  MAX_BATCHES_PER_FLUSH,
  MAX_GAP_BYTES,
  MAX_GAP_ITEMS,
  MAX_QUEUE_BYTES,
  MAX_QUEUE_ITEMS,
  RETRY_ALARM,
  RETRY_MAX_MS,
  RETRY_MIN_MS,
  SESSION_STORAGE_KEY,
} from "../src/constants";
import {
  type CaptureConfig,
  type CompanionState,
  captureConfigSchema,
  DEFAULT_CAPTURE_CONFIG,
  originIdSchema,
  type PageResponseAcquisition,
  pageObservationSchema,
  type RuntimeRequest,
  type RuntimeResponse,
  runtimeRequestSchema,
} from "../src/contracts";
import {
  acquisitionFromPageResponse,
  approximateEnvelopeBytes,
  scopedGapFrom,
} from "../src/pipeline";
import { isPumpPage } from "../src/policy";
import { BoundedQueue } from "../src/queue";
import {
  buildSinkBatch,
  LoopbackSink,
  type QueuedAcquisition,
  type QueuedGap,
  type SinkBatch,
} from "../src/sink";

interface StoredSession {
  version: 2;
  items: QueuedAcquisition[];
  gapItems: QueuedGap[];
  pendingBatch: SinkBatch | null;
  extensionSessionId: string;
  accepted: number;
  delivered: number;
  dropped: number;
  rejectedMessages: number;
  lastAcceptedByScope: Record<string, string>;
  lastCaptureAt: string | null;
  lastDeliveryAt: string | null;
  lastError: string | null;
  backpressure: boolean;
  retryAttempt: number;
  nextAttemptAt: number;
}

const EMPTY_SESSION: StoredSession = {
  version: 2,
  items: [],
  gapItems: [],
  pendingBatch: null,
  extensionSessionId: crypto.randomUUID(),
  accepted: 0,
  delivered: 0,
  dropped: 0,
  rejectedMessages: 0,
  lastAcceptedByScope: {},
  lastCaptureAt: null,
  lastDeliveryAt: null,
  lastError: null,
  backpressure: false,
  retryAttempt: 0,
  nextAttemptAt: 0,
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isStoredSession(value: unknown): value is StoredSession {
  if (value === null || typeof value !== "object") return false;
  const candidate = value as Partial<StoredSession>;
  return (
    candidate.version === 2 &&
    typeof candidate.extensionSessionId === "string" &&
    UUID_PATTERN.test(candidate.extensionSessionId) &&
    Array.isArray(candidate.items) &&
    Array.isArray(candidate.gapItems) &&
    typeof candidate.accepted === "number" &&
    typeof candidate.delivered === "number" &&
    typeof candidate.dropped === "number" &&
    typeof candidate.rejectedMessages === "number" &&
    candidate.lastAcceptedByScope !== null &&
    typeof candidate.lastAcceptedByScope === "object" &&
    typeof candidate.backpressure === "boolean" &&
    typeof candidate.retryAttempt === "number" &&
    typeof candidate.nextAttemptAt === "number"
  );
}

function scopeKey(source: Pick<PageResponseAcquisition, "pageInstanceId" | "routeId">): string {
  return `${source.pageInstanceId}:${source.routeId}`;
}

class Coordinator {
  config: CaptureConfig = DEFAULT_CAPTURE_CONFIG;
  session: StoredSession = { ...EMPTY_SESSION };
  queue = new BoundedQueue<QueuedAcquisition>(MAX_QUEUE_ITEMS, MAX_QUEUE_BYTES);
  gapQueue = new BoundedQueue<QueuedGap>(MAX_GAP_ITEMS, MAX_GAP_BYTES);
  installationId: string = crypto.randomUUID();
  sink = new LoopbackSink((input, init) => fetch(input, init), null);
  #flushPromise: Promise<void> | null = null;

  async initialize(): Promise<void> {
    const [local, session] = await Promise.all([
      browser.storage.local.get([
        CONFIG_STORAGE_KEY,
        INSTALLATION_STORAGE_KEY,
        CATALOG_BINDING_STORAGE_KEY,
      ]),
      browser.storage.session.get(SESSION_STORAGE_KEY),
    ]);
    const config = captureConfigSchema.safeParse(local[CONFIG_STORAGE_KEY]);
    this.config = config.success ? config.data : DEFAULT_CAPTURE_CONFIG;
    const installationId = local[INSTALLATION_STORAGE_KEY];
    this.installationId =
      typeof installationId === "string" && UUID_PATTERN.test(installationId)
        ? installationId
        : crypto.randomUUID();
    const bindingValue = local[CATALOG_BINDING_STORAGE_KEY];
    const binding =
      bindingValue !== null &&
      typeof bindingValue === "object" &&
      Object.keys(bindingValue).length === 2 &&
      typeof (bindingValue as { catalogId?: unknown }).catalogId === "string" &&
      (bindingValue as { catalogSchema?: unknown }).catalogSchema === "joshi.sqlite.v5"
        ? {
            catalogId: (bindingValue as { catalogId: string }).catalogId,
            catalogSchema: "joshi.sqlite.v5" as const,
          }
        : null;
    this.sink = new LoopbackSink((input, init) => fetch(input, init), binding);
    const stored = session[SESSION_STORAGE_KEY];
    if (isStoredSession(stored)) {
      this.session = stored;
      this.queue = new BoundedQueue(MAX_QUEUE_ITEMS, MAX_QUEUE_BYTES, stored.items);
      this.gapQueue = new BoundedQueue(MAX_GAP_ITEMS, MAX_GAP_BYTES, stored.gapItems);
    }
    await this.persistConfig();
    await browser.storage.local.set({ [INSTALLATION_STORAGE_KEY]: this.installationId });
    await this.persistSession();
    await this.updateAction();
  }

  state(): CompanionState {
    const health: CompanionState["health"] = !this.config.captureEnabled
      ? "paused"
      : this.session.backpressure
        ? "backpressure"
        : this.session.lastError !== null
          ? "error"
          : this.session.lastDeliveryAt !== null
            ? "healthy"
            : "idle";
    return {
      config: this.config,
      health,
      queueDepth: this.queue.length,
      queueBytes: this.queue.bytes + this.gapQueue.bytes,
      gapDepth: this.gapQueue.length,
      accepted: this.session.accepted,
      delivered: this.session.delivered,
      dropped: this.session.dropped,
      rejectedMessages: this.session.rejectedMessages,
      lastCaptureAt: this.session.lastCaptureAt,
      lastDeliveryAt: this.session.lastDeliveryAt,
      lastError: this.session.lastError,
    };
  }

  async setConfig(config: CaptureConfig): Promise<void> {
    this.config = config;
    await this.persistConfig();
    await this.updateAction();
  }

  async enqueueGap(gap: ReturnType<typeof scopedGapFrom>): Promise<void> {
    const queued: QueuedGap = { gap, approxBytes: approximateEnvelopeBytes(gap) };
    if (this.gapQueue.enqueue(queued).accepted) return;
    this.config = { ...this.config, captureEnabled: false };
    this.session.lastError = "coverage-gap reserve exhausted; capture paused fail-closed";
    this.session.backpressure = true;
    await this.persistConfig();
  }

  async ingest(observationValue: unknown, senderUrl: string | undefined): Promise<void> {
    if (!this.config.captureEnabled || !isPumpPage(senderUrl)) return;
    const parsed = pageObservationSchema.safeParse(observationValue);
    if (!parsed.success) {
      this.session.rejectedMessages += 1;
      this.session.lastError = "rejected invalid page message (not counted as a coverage gap)";
      await this.persistSession();
      await this.updateAction();
      return;
    }

    const senderPagePath = new URL(senderUrl ?? "https://pump.fun/").pathname;
    const observation = { ...parsed.data, pagePath: senderPagePath };
    const key = scopeKey(observation);
    const lastAcceptedSequence = this.session.lastAcceptedByScope[key] ?? null;

    if (observation.kind === "capture-gap") {
      await this.enqueueGap(
        scopedGapFrom(observation, {
          reason: observation.reason,
          lastAcceptedSequence,
          droppedBytes: observation.responseBytes,
        }),
      );
      this.session.dropped += 1;
      this.session.lastError = `captured scoped gap: ${observation.reason}`;
    } else {
      let envelope: Awaited<ReturnType<typeof acquisitionFromPageResponse>>;
      try {
        envelope = await acquisitionFromPageResponse(observation, this.config, { allowRaw: true });
      } catch {
        await this.enqueueGap(
          scopedGapFrom(observation, {
            reason: "boundary-validation-failed",
            lastAcceptedSequence,
            responseBlobId: observation.responseBlobId,
            droppedBytes: observation.responseBytes,
          }),
        );
        this.session.dropped += 1;
        this.session.lastError = "response failed the exact-byte admission boundary";
        envelope = null;
      }
      if (envelope !== null) {
        const queued: QueuedAcquisition = {
          envelope,
          approxBytes: approximateEnvelopeBytes(envelope),
        };
        const result = this.queue.enqueue(queued);
        if (result.accepted) {
          this.session.accepted += 1;
          this.session.lastCaptureAt = envelope.capturedAt;
          this.session.lastAcceptedByScope[key] = envelope.sequence;
        } else {
          await this.enqueueGap(
            scopedGapFrom(envelope, {
              reason: result.reason ?? "queue-full",
              lastAcceptedSequence,
              droppedRecords: envelope.emittedRecordCount,
              droppedBytes: String(queued.approxBytes),
            }),
          );
          this.session.dropped += 1;
          this.session.lastError = `bounded queue rejected acquisition: ${result.reason}`;
          this.session.backpressure = true;
        }
      }
    }
    await this.persistSession();
    await this.updateAction();
    if (Date.now() >= this.session.nextAttemptAt) await this.flush();
  }

  async flush(force = false): Promise<void> {
    if (this.#flushPromise !== null) return this.#flushPromise;
    if (!force && Date.now() < this.session.nextAttemptAt) return;
    this.#flushPromise = this.flushInner().finally(() => {
      this.#flushPromise = null;
    });
    return this.#flushPromise;
  }

  async preparePendingBatch(): Promise<SinkBatch | null> {
    if (this.session.pendingBatch !== null) return this.session.pendingBatch;
    const acquisitions = this.queue.peekBatch(MAX_BATCH_ITEMS, MAX_BATCH_BYTES);
    const usedBytes = acquisitions.reduce((total, item) => total + item.approxBytes, 0);
    const gaps = this.gapQueue.peekBatch(
      Math.max(0, MAX_BATCH_ITEMS - acquisitions.length),
      Math.max(0, MAX_BATCH_BYTES - usedBytes),
    );
    if (acquisitions.length === 0 && gaps.length === 0) return null;
    this.session.pendingBatch = await buildSinkBatch(
      acquisitions.map((item) => item.envelope),
      gaps.map((item) => item.gap),
      {
        adapter: "pump-companion",
        adapterVersion: browser.runtime.getManifest().version,
        installationId: this.installationId,
        extensionSessionId: this.session.extensionSessionId,
      },
    );
    await this.persistSession();
    return this.session.pendingBatch;
  }

  async flushInner(): Promise<void> {
    let batches = 0;
    while ((this.queue.length > 0 || this.gapQueue.length > 0) && batches < MAX_BATCHES_PER_FLUSH) {
      const batch = await this.preparePendingBatch();
      if (batch === null) {
        this.session.lastError = "no queued acquisition or gap fits the sink batch budget";
        this.session.backpressure = true;
        break;
      }
      const result = await this.sink.send(batch);
      if (!result.ok || result.receipt === null) {
        this.session.retryAttempt += 1;
        const exponential = Math.min(
          RETRY_MAX_MS,
          RETRY_MIN_MS * 2 ** Math.min(this.session.retryAttempt - 1, 6),
        );
        const delay = result.retryAfterMs ?? exponential;
        this.session.nextAttemptAt = Date.now() + delay;
        this.session.lastError = result.error;
        this.session.backpressure = result.retryAfterMs !== null;
        await browser.alarms.create(RETRY_ALARM, { when: this.session.nextAttemptAt });
        break;
      }
      this.queue.remove(batch.acquisitions.length);
      this.gapQueue.remove(batch.gaps.length);
      this.session.delivered += batch.acquisitions.length;
      this.session.pendingBatch = null;
      this.session.lastDeliveryAt = new Date().toISOString();
      this.session.lastError = null;
      this.session.backpressure = false;
      this.session.retryAttempt = 0;
      this.session.nextAttemptAt = 0;
      batches += 1;
      await this.persistSession();
    }

    if ((this.queue.length > 0 || this.gapQueue.length > 0) && this.session.nextAttemptAt === 0) {
      this.session.nextAttemptAt = Date.now() + RETRY_MIN_MS;
      await browser.alarms.create(RETRY_ALARM, { when: this.session.nextAttemptAt });
    }
    await this.persistSession();
    await this.updateAction();
  }

  async persistConfig(): Promise<void> {
    await browser.storage.local.set({ [CONFIG_STORAGE_KEY]: this.config });
  }

  async persistSession(): Promise<void> {
    this.session.items = this.queue.snapshot();
    this.session.gapItems = this.gapQueue.snapshot();
    await browser.storage.session.set({ [SESSION_STORAGE_KEY]: this.session });
  }

  async updateAction(): Promise<void> {
    const state = this.state();
    const presentation = {
      paused: { text: "Ⅱ", color: "#59636e" },
      idle: { text: "ON", color: "#1769aa" },
      healthy: { text: "ON", color: "#197a3e" },
      backpressure: { text: "!", color: "#a45b00" },
      error: { text: "X", color: "#a61b1b" },
    }[state.health];
    await Promise.all([
      browser.action.setBadgeText({ text: presentation.text }),
      browser.action.setBadgeBackgroundColor({ color: presentation.color }),
      browser.action.setTitle({
        title: `Joshi Pump Companion — ${state.health}; ${state.queueDepth} acquisitions + ${state.gapDepth} gaps; ${state.dropped} dropped`,
      }),
    ]);
  }
}

export default defineBackground(() => {
  const coordinator = new Coordinator();
  const ready = coordinator.initialize();
  browser.runtime.onMessage.addListener(
    async (requestValue: unknown, sender): Promise<RuntimeResponse> => {
      await ready;
      const parsedRequest = runtimeRequestSchema.safeParse(requestValue);
      if (!parsedRequest.success) return { ok: false, error: "invalid companion message" };
      const request: RuntimeRequest = parsedRequest.data;
      switch (request.kind) {
        case "get-config":
          return { ok: true, config: coordinator.config };
        case "get-state":
          return { ok: true, state: coordinator.state() };
        case "set-capture-enabled":
          await coordinator.setConfig({ ...coordinator.config, captureEnabled: request.enabled });
          return { ok: true, state: coordinator.state() };
        case "set-raw-capture-enabled":
          await coordinator.setConfig({
            ...coordinator.config,
            rawCaptureEnabled: request.enabled,
          });
          return { ok: true, state: coordinator.state() };
        case "set-origin-enabled": {
          const originId = originIdSchema.safeParse(request.originId);
          if (!originId.success) return { ok: false, error: "unknown capture origin" };
          await coordinator.setConfig({
            ...coordinator.config,
            origins: { ...coordinator.config.origins, [originId.data]: request.enabled },
          });
          return { ok: true, state: coordinator.state() };
        }
        case "ingest-page-observation":
          await coordinator.ingest(request.observation, sender.url);
          return { ok: true, state: coordinator.state() };
        case "flush-now":
          coordinator.session.nextAttemptAt = 0;
          await coordinator.flush(true);
          return { ok: true, state: coordinator.state() };
        default:
          return { ok: false, error: "unknown companion message" };
      }
    },
  );
  browser.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === RETRY_ALARM) void ready.then(() => coordinator.flush(true));
  });
});
