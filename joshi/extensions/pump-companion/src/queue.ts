export interface QueueItem {
  approxBytes: number;
}

export interface EnqueueResult {
  accepted: boolean;
  reason?: "item-too-large" | "queue-full";
}

export class BoundedQueue<T extends QueueItem> {
  readonly #items: T[];
  #bytes: number;

  constructor(
    readonly maxItems: number,
    readonly maxBytes: number,
    initial: readonly T[] = [],
  ) {
    this.#items = [];
    this.#bytes = 0;
    for (const item of initial) {
      if (this.enqueue(item).accepted === false) {
        break;
      }
    }
  }

  get length(): number {
    return this.#items.length;
  }

  get bytes(): number {
    return this.#bytes;
  }

  enqueue(item: T): EnqueueResult {
    if (item.approxBytes > this.maxBytes) {
      return { accepted: false, reason: "item-too-large" };
    }
    if (this.#items.length >= this.maxItems || this.#bytes + item.approxBytes > this.maxBytes) {
      return { accepted: false, reason: "queue-full" };
    }
    this.#items.push(item);
    this.#bytes += item.approxBytes;
    return { accepted: true };
  }

  peekBatch(maxItems: number, maxBytes: number): T[] {
    const batch: T[] = [];
    let bytes = 0;
    for (const item of this.#items) {
      if (batch.length >= maxItems || bytes + item.approxBytes > maxBytes) {
        break;
      }
      batch.push(item);
      bytes += item.approxBytes;
    }
    return batch;
  }

  remove(count: number): void {
    if (!Number.isInteger(count) || count < 0 || count > this.#items.length) {
      throw new RangeError("queue removal count is outside the current queue");
    }
    const removed = this.#items.splice(0, count);
    this.#bytes -= removed.reduce((total, item) => total + item.approxBytes, 0);
  }

  snapshot(): T[] {
    return [...this.#items];
  }
}
