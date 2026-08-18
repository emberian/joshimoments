import { describe, expect, it } from "vitest";

import { BoundedQueue } from "../src/queue";

describe("bounded queue", () => {
  it("rejects rather than silently evicting when item or byte capacity is exhausted", () => {
    const queue = new BoundedQueue<{ id: string; approxBytes: number }>(2, 10);
    expect(queue.enqueue({ id: "a", approxBytes: 4 }).accepted).toBe(true);
    expect(queue.enqueue({ id: "b", approxBytes: 6 }).accepted).toBe(true);
    expect(queue.enqueue({ id: "c", approxBytes: 1 })).toEqual({
      accepted: false,
      reason: "queue-full",
    });
    expect(queue.snapshot().map((item) => item.id)).toEqual(["a", "b"]);
    expect(queue.bytes).toBe(10);
  });

  it("forms bounded batches without removing until delivery succeeds", () => {
    const queue = new BoundedQueue<{ id: string; approxBytes: number }>(10, 200);
    queue.enqueue({ id: "a", approxBytes: 30 });
    queue.enqueue({ id: "b", approxBytes: 40 });
    queue.enqueue({ id: "c", approxBytes: 50 });
    expect(queue.peekBatch(10, 80).map((item) => item.id)).toEqual(["a", "b"]);
    expect(queue.length).toBe(3);
    queue.remove(2);
    expect(queue.snapshot().map((item) => item.id)).toEqual(["c"]);
  });
});
