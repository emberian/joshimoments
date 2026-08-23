import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { OfflineFixtureOperatorSink } from "../operator/client";
import type { OperatorCommandV2 } from "../operator/contract";
import { OfflineFixturePresentationSink, type PresentationSink } from "../presentation/client";
import type { ExplorationBundleV1, PresentationPolicyV1, PresentationSceneReceiptV1, PresentationSceneV1 } from "../presentation/contract";
import {
  MemoryOnlyPairingSession,
  OPERATIONAL_SESSION_SCOPES,
  canonicalPairingSessionId,
} from "../security/pairing";
import { CockpitPublicationDataSource } from "./client";
import { fixtureCockpitIndex, fixtureCockpitLaunch, fixtureSessionLaunch } from "./fixtures";
import { OperationalGlassShell, type OperationalClient, type OperationalRuntime } from "./OperationalShell";

const PAIRING_CODE = "JOSHI-040G-7080-XPTK-366S-YS65-1JRN-4N5D-NJ7N";

function fixtureClient(session: MemoryOnlyPairingSession) {
  let exchanges = 0;
  const sessionId = canonicalPairingSessionId(window.location.origin, "1", "1");
  const client: OperationalClient = {
    async exchange(code) {
      exchanges += 1;
      if (exchanges > 1 || code !== PAIRING_CODE) throw new Error("Pairing code is invalid, expired, or already consumed.");
      session.establish("jpc1_" + "a".repeat(64), {
        sessionId,
        origin: window.location.origin,
        epoch: "1",
        expiresAt: "2099-08-18T00:00:00.000000Z",
        scopes: OPERATIONAL_SESSION_SCOPES,
        authority: "read_only_no_execution",
      });
      return {
        contract: "joshi.pairing.session" as const,
        schemaVersion: 1 as const,
        sessionId,
        origin: window.location.origin,
        epoch: "1",
        expiresAt: "2099-08-18T00:00:00.000000Z",
        scopes: [...OPERATIONAL_SESSION_SCOPES],
        authority: "read_only_no_execution" as const,
      };
    },
    async listPublications() { return fixtureCockpitIndex; },
    async openPublication(cockpitPublicationId) {
      if (cockpitPublicationId !== fixtureCockpitLaunch.launch.cockpitPublication.cockpitPublicationId) throw new Error("unknown immutable publication");
      return fixtureCockpitLaunch;
    },
  };
  return client;
}

describe("operational Glass shell", () => {
  it("keeps the production entrypoint visibly unavailable while ordinary pairing is unmounted", () => {
    render(<OperationalGlassShell session={new MemoryOnlyPairingSession()} />);
    expect(screen.getByRole("heading", { name: /live pairing is unavailable/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/one-time pairing code/i)).not.toBeInTheDocument();
    expect(screen.getByText(/will not collect a one-time code/i)).toBeInTheDocument();
  });

  it("is accessible before pairing, clears the one-time code, and never auto-opens market information", async () => {
    const session = new MemoryOnlyPairingSession();
    const user = userEvent.setup();
    render(<OperationalGlassShell session={session} client={fixtureClient(session)} />);
    const gate = screen.getByRole("main");
    expect((await axe.run(gate, { rules: { "color-contrast": { enabled: false } } })).violations).toEqual([]);
    expect(screen.queryByText(/RADON/)).not.toBeInTheDocument();

    const code = screen.getByLabelText(/one-time pairing code/i);
    await user.type(code, PAIRING_CODE);
    await user.click(screen.getByRole("button", { name: /pair locally/i }));
    expect(await screen.findByRole("heading", { name: /choose an immutable cockpit publication/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/one-time pairing code/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /radon radon/i })).not.toBeInTheDocument();
    expect(screen.getByText(/nothing opens automatically/i)).toBeInTheDocument();
    expect(screen.getByText(/read only no execution/i)).toBeInTheDocument();
  });

  it("reveals only after the presentation receipt and emits presentation-complete V2 evidence", async () => {
    const session = new MemoryOnlyPairingSession();
    const user = userEvent.setup();
    const operatorSink = new OfflineFixtureOperatorSink();
    const presentationDelegate = new OfflineFixturePresentationSink();
    let release: (() => Promise<void>) | null = null;
    const delayedPresentation: PresentationSink = {
      kind: "offline_fixture",
      appendScene(scene: PresentationSceneV1, policy: PresentationPolicyV1, bundle: ExplorationBundleV1) {
        return new Promise<PresentationSceneReceiptV1>((resolve, reject) => {
          release = async () => presentationDelegate.appendScene(scene, policy, bundle).then(resolve, reject);
        });
      },
      appendEvent(event, signal) { return presentationDelegate.appendEvent(event, signal); },
    };
    const client = fixtureClient(session);
    const runtimeFactory = (operationalClient: OperationalClient): OperationalRuntime => ({
      source: new CockpitPublicationDataSource(operationalClient, fixtureCockpitLaunch),
      operatorSink,
      presentationSink: delayedPresentation,
    });
    render(<OperationalGlassShell session={session} client={client} runtimeFactory={runtimeFactory} />);
    await user.type(screen.getByLabelText(/one-time pairing code/i), PAIRING_CODE);
    await user.click(screen.getByRole("button", { name: /pair locally/i }));
    await user.click(await screen.findByRole("button", { name: /open exact publication/i }));
    expect(await screen.findByText(/staging the exact presentation policy/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /radon radon/i })).not.toBeInTheDocument();

    await act(async () => { await release?.(); });
    expect(await screen.findByRole("heading", { name: /radon radon/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /deliberate focus/i }));
    const dialog = screen.getByRole("dialog", { name: /record deliberate focus/i });
    await user.click(within(dialog).getByRole("button", { name: /append evidence record/i }));
    // The act plus its automatic viewport assertion; both carry the V2 presentation binding.
    await waitFor(() => expect(operatorSink.attemptBodies).toHaveLength(2));
    const command = JSON.parse(operatorSink.attemptBodies[0] ?? "null") as OperatorCommandV2;
    expect(command.schemaVersion).toBe(2);
    expect(command.presentation).toMatchObject({
      presentationId: expect.stringMatching(/^presentation-/),
      presentationDigest: expect.stringMatching(/^sha256:/),
    });
    expect(command.cockpitPublication).toEqual({
      cockpitPublicationId: fixtureCockpitLaunch.launch.cockpitPublication.cockpitPublicationId,
      cockpitPublicationDigest: fixtureCockpitLaunch.launch.cockpitPublication.cockpitPublicationDigest,
    });
    expect(JSON.stringify(command)).not.toMatch(/signer|transaction|slippage|quantityAtoms/i);
  });

  it("keeps ordinary paired observation usable with an explicit presentation gap", async () => {
    const session = new MemoryOnlyPairingSession();
    const user = userEvent.setup();
    const failingPresentation: PresentationSink = {
      kind: "offline_fixture",
      appendScene() { return Promise.reject(new Error("ordinary presentation receipt unavailable")); },
      appendEvent() { throw new Error("presentation events require a scene receipt"); },
    };
    const runtimeFactory = (operationalClient: OperationalClient): OperationalRuntime => ({
      source: new CockpitPublicationDataSource(operationalClient, fixtureCockpitLaunch),
      operatorSink: new OfflineFixtureOperatorSink(),
      presentationSink: failingPresentation,
    });
    render(<OperationalGlassShell session={session} client={fixtureClient(session)} runtimeFactory={runtimeFactory} />);
    await user.type(screen.getByLabelText(/one-time pairing code/i), PAIRING_CODE);
    await user.click(screen.getByRole("button", { name: /pair locally/i }));
    await user.click(await screen.findByRole("button", { name: /open exact publication/i }));
    expect(await screen.findByRole("heading", { name: /radon radon/i })).toBeInTheDocument();
    const gap = await screen.findByText(/^Presentation not witnessed:/i);
    expect(gap).toHaveAttribute("role", "alert");
    expect(gap).toHaveTextContent(/rich information is visible/i);
  });

  it("requires re-pairing after an explicit restart and retains no publication", async () => {
    const session = new MemoryOnlyPairingSession();
    const user = userEvent.setup();
    render(<OperationalGlassShell session={session} client={fixtureClient(session)} />);
    await user.type(screen.getByLabelText(/one-time pairing code/i), PAIRING_CODE);
    await user.click(screen.getByRole("button", { name: /pair locally/i }));
    expect(await screen.findByRole("heading", { name: /choose an immutable cockpit publication/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /end session/i }));
    expect(await screen.findByRole("heading", { name: /pair this glass session/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open exact publication/i })).not.toBeInTheDocument();
    expect(session.paired()).toBe(false);
  });

  it("opens a server-bound prospective launch without listing or choosing another publication", async () => {
    const session = new MemoryOnlyPairingSession();
    const user = userEvent.setup();
    const base = fixtureClient(session);
    let listCalls = 0;
    const client: OperationalClient = {
      ...base,
      async listPublications() { listCalls += 1; return fixtureCockpitIndex; },
      async loadSessionLaunch() { return fixtureSessionLaunch; },
      async appendAbstention() { throw new Error("not exercised by this shell-boundary test"); },
      async appendProspectiveNomination() { throw new Error("not exercised by this shell-boundary test"); },
    };
    const presentationSink = new OfflineFixturePresentationSink();
    const runtimeFactory = (operationalClient: OperationalClient): OperationalRuntime => ({
      source: new CockpitPublicationDataSource(operationalClient, fixtureCockpitLaunch),
      operatorSink: new OfflineFixtureOperatorSink(),
      presentationSink,
    });
    render(<OperationalGlassShell mode="prospective" session={session} client={client} runtimeFactory={runtimeFactory} />);
    await user.type(screen.getByLabelText(/one-time pairing code/i), PAIRING_CODE);
    await user.click(screen.getByRole("button", { name: /pair locally/i }));
    expect(await screen.findByRole("heading", { name: /radon radon/i })).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`registered launch ${fixtureSessionLaunch.registration.launchId}`, "i"))).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /choose an immutable cockpit publication/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open exact publication/i })).not.toBeInTheDocument();
    expect(listCalls).toBe(0);
    await waitFor(() => expect(presentationSink.sceneAttemptBodies).toHaveLength(1));
    const admission = JSON.parse(presentationSink.sceneAttemptBodies[0] ?? "null") as { scene: PresentationSceneV1 };
    expect(admission.scene.presentationId).toBe(fixtureSessionLaunch.registration.reservedPresentationId);
    expect(admission.scene.policy.assignmentId).toBe(fixtureSessionLaunch.registration.presentation.assignmentId);
    expect(await screen.findByRole("heading", { name: /explicit abstention/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /qualifying nomination/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^nominate/i })).toBeDisabled();
    expect(screen.getByText(/ordinary evidence command v2 does not bind/i)).toBeInTheDocument();
  });
});
