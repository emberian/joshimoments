import { afterEach, describe, expect, it, vi } from "vitest";

import { LoopbackDataSource, MAX_GLASS_SNAPSHOT_BYTES } from "./client";
import { mockSnapshots } from "./mockSnapshot";

afterEach(() => vi.unstubAllGlobals());

describe("loopback glass client", () => {
  it("refuses a non-loopback core origin", () => {
    expect(() => new LoopbackDataSource("https://example.com")).toThrow(/loopback/i);
  });

  it("requests one mode, omits ambient credentials, and validates its digest", async () => {
    const responseSnapshot = structuredClone(mockSnapshots.witnessed);
    responseSnapshot.transport = "loopback";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseSnapshot), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const snapshot = await new LoopbackDataSource("http://127.0.0.1:8787", responseSnapshot.view.sceneId).loadSnapshot({ mode: "witnessed", basisSceneId: null });
    expect(snapshot.view.mode).toBe("witnessed");
    expect(snapshot.snapshotDigest).toBe(responseSnapshot.snapshotDigest);
    expect(snapshot.transport).toBe("loopback");
    expect(fetchMock).toHaveBeenCalledWith(
      new URL(`http://127.0.0.1:8787/api/v1/glass/snapshot?mode=witnessed&basisSceneId=${responseSnapshot.view.sceneId}`),
      expect.objectContaining({ credentials: "omit" }),
    );
  });

  it("rejects an oversized declared response before parsing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response("{}", { status: 200, headers: { "Content-Length": String(MAX_GLASS_SNAPSHOT_BYTES + 1) } }),
    ));
    await expect(new LoopbackDataSource("http://localhost:8787", "scene-launch").loadSnapshot({ mode: "witnessed", basisSceneId: null })).rejects.toThrow(/response bound/i);
  });

  it("cancels an oversized streamed response without a content-length claim", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response("x".repeat(MAX_GLASS_SNAPSHOT_BYTES + 1), { status: 200 }),
    ));
    await expect(new LoopbackDataSource("http://localhost:8787", "scene-launch").loadSnapshot({ mode: "witnessed", basisSceneId: null })).rejects.toThrow(/response bound/i);
  });

  it("rejects a valid but wrong-mode response", async () => {
    const responseSnapshot = structuredClone(mockSnapshots.retrospective);
    responseSnapshot.transport = "loopback";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(responseSnapshot), { status: 200 })));
    await expect(new LoopbackDataSource("http://localhost:8787", "scene-launch").loadSnapshot({ mode: "witnessed", basisSceneId: null })).rejects.toThrow(/requested witnessed/i);
  });

  it("rejects duplicate JSON keys before a parser can collapse them", async () => {
    const responseSnapshot = structuredClone(mockSnapshots.witnessed);
    responseSnapshot.transport = "loopback";
    const bodyWithDuplicateMode = JSON.stringify(responseSnapshot).replace(
      '"mode":"witnessed"',
      '"mode":"witnessed","mode":"witnessed"',
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(bodyWithDuplicateMode, { status: 200 })));

    await expect(
      new LoopbackDataSource("http://localhost:8787", "scene-launch").loadSnapshot({ mode: "witnessed", basisSceneId: null }),
    ).rejects.toThrow(/duplicated keys/i);
  });

  it("preserves unusual raw keys for the strict schema to reject", async () => {
    const responseSnapshot = structuredClone(mockSnapshots.witnessed);
    responseSnapshot.transport = "loopback";
    const bodyWithPrototypeKey = JSON.stringify(responseSnapshot).replace(
      '"transport":"loopback"',
      '"__proto__":{"polluted":true},"transport":"loopback"',
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(bodyWithPrototypeKey, { status: 200 })));

    await expect(
      new LoopbackDataSource("http://localhost:8787", "scene-launch").loadSnapshot({ mode: "witnessed", basisSceneId: null }),
    ).rejects.toThrow();
    expect(Object.prototype).not.toHaveProperty("polluted");
  });

  it("fails before fetch rather than inventing a mutable latest scene", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(new LoopbackDataSource("http://localhost:8787").loadSnapshot({ mode: "witnessed", basisSceneId: null })).rejects.toThrow(/explicit immutable scene ID/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
