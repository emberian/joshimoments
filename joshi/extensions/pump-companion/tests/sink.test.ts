import { describe, expect, it, vi } from "vitest";

import { RECEIPT_SCHEMA } from "../src/constants";
import { durableReceiptSchema } from "../src/contracts";
import {
  buildSinkBatch,
  type CatalogBinding,
  type FetchLike,
  LoopbackSink,
  type SinkBatch,
} from "../src/sink";

const binding: CatalogBinding = {
  catalogId: "local-test-catalog",
  catalogSchema: "joshi.sqlite.v5",
};
const producer: SinkBatch["producer"] = {
  adapter: "pump-companion",
  adapterVersion: "0.1.0",
  installationId: "60000000-0000-4000-8000-000000000001",
  extensionSessionId: "70000000-0000-4000-8000-000000000001",
};

function receipt(batch: SinkBatch, status: "accepted" | "idempotent" = "accepted") {
  return {
    contract: RECEIPT_SCHEMA,
    schemaVersion: 1,
    catalogId: binding.catalogId,
    catalogSchema: binding.catalogSchema,
    ingressBatchId: batch.batchId,
    ingressBatchDigest: batch.batchDigest,
    status,
    fromCommitSeq: "40",
    throughCommitSeq: "40",
    durableBatchId: "durable-batch-1",
    durableBatchDigest: `sha256:${"e".repeat(64)}`,
    storeAdmissionDigest: `sha256:${"f".repeat(64)}`,
    acquisitionCount: "0",
    gapCount: "0",
    committedAcquisitionIds: [],
    committedGapIds: [],
  };
}

describe("loopback durable store-receipt adapter", () => {
  it("uses fixed loopback, omits credentials, and accepts an exact durable receipt", async () => {
    const batch = await buildSinkBatch([], [], producer, "30000000-0000-4000-8000-000000000001");
    const fetcher = vi.fn<FetchLike>(
      async () => new Response(JSON.stringify(receipt(batch)), { status: 202 }),
    );
    const result = await new LoopbackSink(fetcher, binding).send(batch);
    expect(result.ok).toBe(true);
    const [url, init] = fetcher.mock.calls[0] ?? [];
    expect(url).toBe("http://127.0.0.1:43119/v1/observations/pump-companion");
    expect(init?.credentials).toBe("omit");
    expect(init?.redirect).toBe("error");
    expect(JSON.stringify(init?.headers)).not.toMatch(/authorization|cookie|api-key/i);
  });

  it("refuses delivery before an exact local catalog binding exists", async () => {
    const batch = await buildSinkBatch([], [], producer);
    const fetcher = vi.fn<FetchLike>();
    const result = await new LoopbackSink(fetcher, null).send(batch);
    expect(result).toMatchObject({ ok: false, receipt: null });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([
    ["empty 204", () => new Response(null, { status: 204 })],
    ["wrong body", () => new Response('{"ok":true}', { status: 200 })],
  ])("keeps the batch queued for a %s response", async (_name, responseFactory) => {
    const batch = await buildSinkBatch([], [], producer);
    const result = await new LoopbackSink(async () => responseFactory(), binding).send(batch);
    expect(result.ok).toBe(false);
    expect(result.receipt).toBeNull();
  });

  it("rejects a partial ingress closure", async () => {
    const batch = await buildSinkBatch([], [], producer);
    const partial = { ...receipt(batch), acquisitionCount: "1" };
    const result = await new LoopbackSink(
      async () => new Response(JSON.stringify(partial), { status: 200 }),
      binding,
    ).send(batch);
    expect(result).toMatchObject({ ok: false, receipt: null });
  });

  it("rejects unknown receipt fields and decimal integers above u64::MAX", async () => {
    const batch = await buildSinkBatch([], [], producer);
    expect(durableReceiptSchema.safeParse({ ...receipt(batch), unexpected: true }).success).toBe(
      false,
    );
    expect(
      durableReceiptSchema.safeParse({
        ...receipt(batch),
        fromCommitSeq: "18446744073709551616",
      }).success,
    ).toBe(false);
  });

  it.each(["duplicate", "dangerous"])(
    "rejects %s receipt object keys before admission",
    async (kind) => {
      const batch = await buildSinkBatch([], [], producer);
      const valid = JSON.stringify(receipt(batch));
      const body =
        kind === "duplicate"
          ? valid.replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1')
          : valid.replace("{", '{"__proto__":{"polluted":true},');
      const result = await new LoopbackSink(
        async () => new Response(body, { status: 200 }),
        binding,
      ).send(batch);
      expect(result).toMatchObject({ ok: false, receipt: null });
      expect(({} as { polluted?: boolean }).polluted).toBeUndefined();
    },
  );

  it("accepts an idempotent receipt for the exact same persisted batch", async () => {
    const batch = await buildSinkBatch([], [], producer, "30000000-0000-4000-8000-000000000002");
    let attempt = 0;
    const sink = new LoopbackSink(async () => {
      attempt += 1;
      return new Response(
        JSON.stringify(receipt(batch, attempt === 1 ? "accepted" : "idempotent")),
        { status: 200 },
      );
    }, binding);
    await expect(sink.send(batch)).resolves.toMatchObject({ ok: true });
    await expect(sink.send(batch)).resolves.toMatchObject({ ok: true });
  });

  it("honors a loopback Retry-After response", async () => {
    const batch = await buildSinkBatch([], [], producer);
    const result = await new LoopbackSink(
      async () => new Response(null, { status: 429, headers: { "Retry-After": "3" } }),
      binding,
    ).send(batch);
    expect(result).toMatchObject({ ok: false, retryAfterMs: 3_000 });
  });

  it("refuses a non-pinned destination", () => {
    expect(
      () =>
        new LoopbackSink(
          async () => new Response(null, { status: 200 }),
          binding,
          "http://127.0.0.1:9999/exfil" as "http://127.0.0.1:43119/v1/observations/pump-companion",
        ),
    ).toThrow(/pinned/);
  });
});
