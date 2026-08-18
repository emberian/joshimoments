import { afterEach, describe, expect, it, vi } from "vitest";

import { MemoryOnlyPairingSession, canonicalPairingSessionId } from "../security/pairing";
import { SameOriginOperationalClient } from "./client";
import {
  canonicalExplicitAbstention,
  digestCockpitLaunch,
  digestExplicitAbstention,
  digestProspectiveNomination,
  explicitAbstentionCommandV1Schema,
  explicitAbstentionReceiptV1Schema,
  prospectiveNominationCommandV1Schema,
  prospectiveNominationReceiptV1Schema,
  type CockpitLaunchEnvelopeV1,
} from "./contract";
import { fixtureCockpitIndex, fixtureCockpitLaunch, fixtureSessionLaunch } from "./fixtures";

const PAIRING_CODE = "JOSHI-040G-7080-XPTK-366S-YS65-1JRN-4N5D-NJ7N";

function productionLaunch(): CockpitLaunchEnvelopeV1 {
  const envelope = structuredClone(fixtureCockpitLaunch);
  envelope.launch.snapshot.transport = "loopback";
  envelope.launchDigest = digestCockpitLaunch(envelope.launch);
  return envelope;
}

afterEach(() => vi.unstubAllGlobals());

describe("same-origin operational client", () => {
  it("consumes a one-time code, keeps the capability in memory, and explicitly opens one durable ID", async () => {
    const session = new MemoryOnlyPairingSession();
    const launch = productionLaunch();
    const capability = "jpc1_" + "a".repeat(64);
    const sessionId = canonicalPairingSessionId(window.location.origin, "1", "1");
    const responses = [
      new Response(JSON.stringify({
        contract: "joshi.pairing.session",
        schemaVersion: 1,
        sessionId,
        origin: window.location.origin,
        epoch: "1",
        expiresAt: "2099-08-18T00:00:00.000000Z",
        scopes: ["cockpit_read", "operator_evidence_write", "presentation_evidence_write", "replay_read"],
        authority: "read_only_no_execution",
        capability,
      }), { status: 200 }),
      new Response(JSON.stringify(fixtureCockpitIndex), { status: 200 }),
      new Response(JSON.stringify(launch), { status: 200 }),
    ];
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(responses.shift()));
    vi.stubGlobal("fetch", fetchMock);
    const client = new SameOriginOperationalClient(session);

    const descriptor = await client.exchange(PAIRING_CODE.toLowerCase());
    expect(descriptor).not.toHaveProperty("capability");
    expect(session.descriptor()).toMatchObject({ sessionId, authority: "read_only_no_execution" });
    const exchangeCall = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(exchangeCall[0].pathname).toBe("/api/v1/pairing/exchange");
    expect(exchangeCall[1]).toMatchObject({ credentials: "omit", cache: "no-store" });
    expect(exchangeCall[1].headers).not.toHaveProperty("X-Joshi-Pairing-Token");
    expect(exchangeCall[1].body).toBe(`{"contract":"joshi.pairing.exchange","schemaVersion":1,"oneTimeCode":"${PAIRING_CODE}"}`);

    await client.listPublications();
    const opened = await client.openPublication(launch.launch.cockpitPublication.cockpitPublicationId);
    expect(opened.launch.cockpitPublication.cockpitPublicationDigest).toBe(launch.launch.cockpitPublication.cockpitPublicationDigest);
    for (const [, init] of fetchMock.mock.calls.slice(1) as Array<[URL, RequestInit]>) {
      expect(init.headers).toMatchObject({ "X-Joshi-Pairing-Token": capability });
      expect(init.credentials).toBe("omit");
    }
    expect(JSON.stringify(descriptor)).not.toContain(capability);
  });

  it("rejects cross-origin construction and fails before publication fetch without a session", async () => {
    expect(() => new SameOriginOperationalClient(new MemoryOnlyPairingSession(), "http://127.0.0.1:6553")).toThrow(/exact page origin/i);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(new SameOriginOperationalClient(new MemoryOnlyPairingSession()).listPublications()).rejects.toThrow(/not paired/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("clears the memory capability on revocation and rejects duplicate response keys", async () => {
    const session = new MemoryOnlyPairingSession();
    session.pair("a".repeat(64));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    await expect(new SameOriginOperationalClient(session).listPublications()).rejects.toThrow(/revoked/i);
    expect(session.paired()).toBe(false);

    session.pair("b".repeat(64));
    const duplicate = JSON.stringify(fixtureCockpitIndex).replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1');
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(duplicate, { status: 200 })));
    await expect(new SameOriginOperationalClient(session).listPublications()).rejects.toThrow(/duplicated keys/i);
  });

  it("never treats an unavailable or noncanonical session-launch response as a launch", async () => {
    const session = new MemoryOnlyPairingSession();
    session.pair("e".repeat(64));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      contract: "joshi.problem",
      code: "prospective_store_adapter_unavailable",
    }), { status: 503 })));
    await expect(new SameOriginOperationalClient(session).loadSessionLaunch()).rejects.toThrow(/503/);
    expect(session.paired()).toBe(true);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(`${JSON.stringify(fixtureSessionLaunch)}\n`, { status: 200 })));
    await expect(new SameOriginOperationalClient(session).loadSessionLaunch()).rejects.toThrow(/exact canonical/i);
  });

  it("loads only the parameterless server-bound launch and appends both exact dedicated choice branches", async () => {
    const session = new MemoryOnlyPairingSession();
    session.pair("c".repeat(64));
    const command = explicitAbstentionCommandV1Schema.parse({
      contract: "joshi.operator.explicit_abstention",
      schemaVersion: 1,
      abstentionId: fixtureSessionLaunch.registration.reservedCommandId,
      idempotencyKey: fixtureSessionLaunch.registration.reservedCommandIdempotencyKey,
      episodeLaunchId: fixtureSessionLaunch.registration.launchId,
      clientSessionId: "session-client-abstention",
      clientCommandSeq: "1",
      cockpitPublicationId: fixtureSessionLaunch.registration.cockpit.publicationId,
      scene: {
        sceneId: fixtureSessionLaunch.registration.scene.sceneId,
        viewDigest: fixtureSessionLaunch.registration.scene.viewDigest,
      },
      presentation: { presentationId: fixtureSessionLaunch.registration.reservedPresentationId, presentationDigest: `sha256:${"d".repeat(64)}` },
      assignmentId: fixtureSessionLaunch.registration.presentation.assignmentId,
      asOfDigest: fixtureSessionLaunch.registration.asOfDigest,
      choiceUniverseDigest: fixtureSessionLaunch.registration.choiceUniverseDigest,
      decisionDeadline: "2026-08-17T18:30:00.000000Z",
      reason: "risk_boundary",
      issuedAt: "2026-08-17T18:10:00.000000Z",
      clientClock: { clockId: "clock-client-abstention", monotonicNs: "1000" },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    const receipt = explicitAbstentionReceiptV1Schema.parse({
      contract: "joshi.store.explicit_abstention_receipt",
      schemaVersion: 1,
      catalogId: "catalog-test",
      catalogSchema: "joshi.sqlite.v7",
      batchId: "batch-abstention-1",
      abstentionId: command.abstentionId,
      episodeLaunchId: command.episodeLaunchId,
      scene: command.scene,
      presentation: command.presentation,
      choiceUniverseDigest: command.choiceUniverseDigest,
      abstentionDigest: digestExplicitAbstention(command),
      commitSeq: "92",
      status: "accepted",
    });
    const nomination = prospectiveNominationCommandV1Schema.parse({
      contract: "joshi.operator.prospective_nomination",
      schemaVersion: 1,
      nominationId: fixtureSessionLaunch.registration.reservedCommandId,
      idempotencyKey: fixtureSessionLaunch.registration.reservedCommandIdempotencyKey,
      episodeLaunchId: fixtureSessionLaunch.registration.launchId,
      clientSessionId: "session-client-nomination",
      clientCommandSeq: "1",
      subject: fixtureSessionLaunch.registration.choiceMembers[2],
      cockpitPublicationId: fixtureSessionLaunch.registration.cockpit.publicationId,
      scene: {
        sceneId: fixtureSessionLaunch.registration.scene.sceneId,
        viewDigest: fixtureSessionLaunch.registration.scene.viewDigest,
      },
      presentation: { presentationId: fixtureSessionLaunch.registration.reservedPresentationId, presentationDigest: `sha256:${"d".repeat(64)}` },
      assignmentId: fixtureSessionLaunch.registration.presentation.assignmentId,
      asOfDigest: fixtureSessionLaunch.registration.asOfDigest,
      choiceUniverseDigest: fixtureSessionLaunch.registration.choiceUniverseDigest,
      decisionDeadline: "2026-08-17T18:30:00.000000Z",
      issuedAt: "2026-08-17T18:10:00.000000Z",
      clientClock: { clockId: "clock-client-nomination", monotonicNs: "2000" },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    const nominationReceipt = prospectiveNominationReceiptV1Schema.parse({
      contract: "joshi.store.prospective_nomination_receipt",
      schemaVersion: 1,
      catalogId: "catalog-test",
      catalogSchema: "joshi.sqlite.v7",
      batchId: "batch-nomination-1",
      nominationId: nomination.nominationId,
      episodeLaunchId: nomination.episodeLaunchId,
      subject: nomination.subject,
      scene: nomination.scene,
      presentation: nomination.presentation,
      choiceUniverseDigest: nomination.choiceUniverseDigest,
      nominationDigest: digestProspectiveNomination(nomination),
      commitSeq: "93",
      status: "accepted",
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(fixtureSessionLaunch), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(receipt), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(nominationReceipt), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new SameOriginOperationalClient(session);
    expect((await client.loadSessionLaunch()).registration.launchId).toBe(command.episodeLaunchId);
    expect(await client.appendAbstention(command)).toEqual(receipt);
    expect((fetchMock.mock.calls[0] as [URL])[0].pathname).toBe("/api/v1/session/launch");
    expect((fetchMock.mock.calls[0] as [URL])[0].search).toBe("");
    const abstentionCall = fetchMock.mock.calls[1] as [URL, RequestInit];
    expect(abstentionCall[0].pathname).toBe("/api/v1/operator/abstentions");
    expect(abstentionCall[1].body).toBe(canonicalExplicitAbstention(command));
    expect(abstentionCall[1].headers).toMatchObject({ "X-Joshi-Pairing-Token": "c".repeat(64) });
    expect(await client.appendProspectiveNomination(nomination)).toEqual(nominationReceipt);
    const nominationCall = fetchMock.mock.calls[2] as [URL, RequestInit];
    expect(nominationCall[0].pathname).toBe("/api/v1/operator/prospective-nominations");
    expect(nominationCall[1].body).toBe(JSON.stringify(nomination));
    expect(nominationCall[1].headers).toMatchObject({ "X-Joshi-Pairing-Token": "c".repeat(64) });
  });
});
