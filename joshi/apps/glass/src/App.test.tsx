import axe from "axe-core";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlassApp } from "./App";
import type { GlassSnapshotV1 } from "./contract/v1";
import type { HeldVenueReadout } from "./components/HeldCoins";
import { OfflineFixtureDataSource, type GlassDataSource, type SnapshotRequest } from "./data/client";
import { mockSnapshots } from "./data/mockSnapshot";
import { canonicalOperatorCommand, type CommandReceipt, type OperatorCommand, type OperatorCommandV1 } from "./operator/contract";
import { OfflineFixtureOperatorSink, RetryableCommandError, type OperatorCommandSink } from "./operator/client";
import { MemoryPendingOperatorCommandQueue, type PendingOperatorCommandQueue, type PendingOperatorCommandV1 } from "./operator/pendingQueue";
import type { ExplorationBundleV1, PresentationEventReceiptV1, PresentationEventV1, PresentationPolicyV1, PresentationSceneReceiptV1, PresentationSceneV1 } from "./presentation/contract";
import { OfflineFixturePresentationSink, type PresentationSink } from "./presentation/client";

function renderGlass() {
  return render(<GlassApp dataSource={new OfflineFixtureDataSource()} />);
}

describe("accessibility-first glass", () => {
  it("renders the witnessed market, exposure rail, and safety boundary", async () => {
    renderGlass();
    expect(await screen.findByRole("heading", { name: /radon radon/i })).toBeInTheDocument();
    expect(screen.getByText(/read, record & replay only/i)).toBeInTheDocument();
    expect(screen.getByText(/flat, re-entry watch/i)).toBeInTheDocument();
    expect(screen.getAllByText(/watching while flat/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/coverage gap/i).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /submit (?:buy|sell|swap)|buy now|sell now|confirm trade/i })).not.toBeInTheDocument();
  });

  it("supports semantic keyboard navigation without pointer precision", async () => {
    const user = userEvent.setup();
    renderGlass();
    await screen.findByRole("heading", { name: /radon radon/i });

    await user.keyboard("j");
    await waitFor(() => expect(screen.getByRole("heading", { name: /orbitfan orbit fan club/i })).toBeInTheDocument());

    await user.keyboard("/");
    const search = screen.getByRole("searchbox", { name: /search candidates in this served snapshot/i });
    expect(search).toHaveFocus();
    await user.type(search, "fancoin");
    expect(await screen.findByRole("button", { name: /orbitfan/i })).toBeInTheDocument();
    await user.clear(search);
    search.blur();
    await user.keyboard("r");
    expect(await screen.findByText(/separate later reconstruction/i)).toBeInTheDocument();
  });

  it("finds an exact mint inside the immutable served surface", async () => {
    const user = userEvent.setup();
    renderGlass();
    await screen.findByRole("heading", { name: /radon radon/i });
    const target = mockSnapshots.witnessed.view.payload.candidates.find((candidate) => candidate.symbol === "ORBITFAN");
    expect(target).toBeDefined();
    const search = screen.getByRole("searchbox", { name: /search candidates in this served snapshot/i });
    await user.type(search, target!.mint);
    expect(await screen.findByRole("button", { name: /orbitfan/i })).toBeInTheDocument();
  });

  it("opens a view-only command surface and toggles provenance", async () => {
    const user = userEvent.setup();
    renderGlass();
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard("{Meta>}k{/Meta}");
    const dialog = screen.getByRole("dialog", { name: /navigate the glass/i });
    expect(within(dialog).getByText(/no capital actions are available/i)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /toggle provenance/i }));
    expect(await screen.findByRole("heading", { name: /radon field provenance/i })).toBeInTheDocument();
  });

  it("keeps later-only candidates and social evidence out of the witnessed lens", async () => {
    const user = userEvent.setup();
    renderGlass();
    await screen.findByRole("heading", { name: /radon radon/i });
    expect(screen.queryByText(/later_post/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /later/i }));
    await screen.findByText(/separate later reconstruction/i);
    await user.keyboard("/");
    const search = screen.getByRole("searchbox", { name: /search candidates in this served snapshot/i });
    await user.type(search, "afterglow");
    expect(await screen.findByRole("button", { name: /afterglow/i })).toBeInTheDocument();
  });

  it("loads mode changes as distinct snapshot requests bound to the witnessed scene", async () => {
    const delegate = new OfflineFixtureDataSource();
    const requests: Array<Omit<SnapshotRequest, "signal">> = [];
    const recordingSource: GlassDataSource = {
      kind: "offline_fixture",
      loadSnapshot(request) {
        requests.push({ mode: request.mode, basisSceneId: request.basisSceneId });
        return delegate.loadSnapshot(request);
      },
    };
    const user = userEvent.setup();
    render(<GlassApp dataSource={recordingSource} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.click(screen.getByRole("radio", { name: /later/i }));
    await screen.findByText(/separate later reconstruction/i);

    expect(requests).toEqual([
      { mode: "witnessed", basisSceneId: null },
      { mode: "retrospective", basisSceneId: "scene-20260816-184215-witnessed" },
    ]);
  });

  it("keeps the verified witnessed DTO intact until a later response validates", async () => {
    const delegate = new OfflineFixtureDataSource();
    let releaseLater: ((snapshot: GlassSnapshotV1) => void) | undefined;
    const delayedSource: GlassDataSource = {
      kind: "offline_fixture",
      loadSnapshot(request) {
        if (request.mode !== "retrospective") return delegate.loadSnapshot(request);
        return new Promise((resolve) => { releaseLater = resolve; });
      },
    };
    const user = userEvent.setup();
    render(<GlassApp dataSource={delayedSource} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.click(screen.getByRole("radio", { name: /later/i }));

    expect(screen.getByRole("radio", { name: /witnessed/i })).toBeChecked();
    expect(screen.getByText(/loading a distinct retrospective snapshot/i)).toBeInTheDocument();
    expect(screen.getByText(/exact witnessed view/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("LATER_SOCIAL_CLUSTER");

    await act(async () => releaseLater?.(mockSnapshots.retrospective));
    expect(await screen.findByText(/separate later reconstruction/i)).toBeInTheDocument();
  });

  it("has no automatically detectable accessibility violations in its initial view", async () => {
    const { container } = renderGlass();
    await screen.findByRole("heading", { name: /radon radon/i });
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });

  it("does not render a semantic mark as committed before its append receipt", async () => {
    const delegate = new OfflineFixtureOperatorSink();
    let release: (() => Promise<void>) | undefined;
    const delayedSink: OperatorCommandSink = {
      kind: "offline_fixture",
      appendCommand(command) {
        return new Promise<CommandReceipt>((resolve, reject) => {
          release = async () => delegate.appendCommand(command).then(resolve, reject);
        });
      },
    };
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={delayedSink} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.click(screen.getByRole("button", { name: /deliberate focus/i }));
    await user.type(screen.getByLabelText(/why now/i), "The tape changed shape.");
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));

    expect(await screen.findByText(/waiting for a durable receipt/i)).toBeInTheDocument();
    expect(screen.queryByText(/commit 1001/i)).not.toBeInTheDocument();
    await act(async () => { await release?.(); });
    expect((await screen.findAllByText(/commit 1001/i)).length).toBeGreaterThan(0);
  });

  it("recovers exact pending bytes after reload and a fresh pairing context", async () => {
    const queue = new MemoryPendingOperatorCommandQueue();
    const outage: OperatorCommandSink = {
      kind: "offline_fixture",
      async appendCommand() {
        throw new RetryableCommandError("fixture outage");
      },
    };
    const firstUser = userEvent.setup();
    const first = render(<GlassApp
      dataSource={new OfflineFixtureDataSource()}
      operatorSink={outage}
      pendingOperatorQueue={queue}
    />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await firstUser.click(screen.getByRole("button", { name: /deliberate focus/i }));
    await firstUser.click(screen.getByRole("button", { name: /append evidence record/i }));
    expect(await screen.findByText(/disconnected.*retained for retry/i)).toBeInTheDocument();
    const retained = (await queue.list())[0]!;
    first.unmount();

    const accepted: OperatorCommand[] = [];
    const delegate = new OfflineFixtureOperatorSink();
    const recoveredSink: OperatorCommandSink = {
      kind: "offline_fixture",
      async appendCommand(command) {
        accepted.push(command);
        return delegate.appendCommand(command);
      },
    };
    const secondUser = userEvent.setup();
    render(<GlassApp
      dataSource={new OfflineFixtureDataSource()}
      operatorSink={recoveredSink}
      pendingOperatorQueue={queue}
    />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await secondUser.click(await screen.findByRole("button", { name: /recover retained exact bytes/i }));
    await waitFor(async () => expect(await queue.list()).toHaveLength(0));
    expect(accepted).toHaveLength(1);
    expect(canonicalOperatorCommand(accepted[0]!)).toBe(retained.canonicalCommand);
  });

  it("retains exact canonical command bytes locally before the first server attempt", async () => {
    const sink = new OfflineFixtureOperatorSink();
    let releaseRetention: (() => void) | undefined;
    const retained: PendingOperatorCommandV1[] = [];
    const queue: PendingOperatorCommandQueue = {
      append(pending) {
        retained.push(pending);
        return new Promise<void>((resolve) => { releaseRetention = resolve; });
      },
      async list() { return []; },
      async acknowledge() {},
    };
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={sink} pendingOperatorQueue={queue} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.click(screen.getByRole("button", { name: /deliberate focus/i }));
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));
    expect(await screen.findByText(/retaining the exact canonical command/i)).toBeInTheDocument();
    expect(retained).toHaveLength(1);
    expect(sink.attemptBodies).toHaveLength(0);
    act(() => releaseRetention?.());
    await waitFor(() => expect(sink.attemptBodies).toHaveLength(1));
    expect(sink.attemptBodies[0]).toBe(retained[0]?.canonicalCommand);
  });

  it("retries the exact queued command after reconnect and commits it once", async () => {
    const sink = new OfflineFixtureOperatorSink();
    sink.setOnline(false);
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={sink} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard("f");
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));
    expect(await screen.findByText(/exact command envelope is retained for retry/i)).toBeInTheDocument();

    sink.setOnline(true);
    act(() => window.dispatchEvent(new Event("online")));
    expect((await screen.findAllByText(/commit 1001/i)).length).toBeGreaterThan(0);
    expect(sink.attemptBodies).toHaveLength(2);
    expect(sink.attemptBodies[1]).toBe(sink.attemptBodies[0]);
  });

  it("undoes with a new compensating event and never erases the prior command", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={sink} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.click(screen.getByRole("button", { name: /deliberate focus/i }));
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));
    expect((await screen.findAllByText(/commit 1001/i)).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /compensate/i }));
    expect((await screen.findAllByText(/commit 1002/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/compensated by a later append-only record/i)).toBeInTheDocument();

    const first = JSON.parse(sink.attemptBodies[0] ?? "null") as OperatorCommandV1;
    const second = JSON.parse(sink.attemptBodies[1] ?? "null") as OperatorCommandV1;
    expect(second.commandKind).toBe("compensate_command");
    if (second.commandKind !== "compensate_command") throw new Error("expected compensating command");
    expect(second.payload.compensatesCommandId).toBe(first.commandId);
    expect(sink.attemptBodies).toHaveLength(2);
  });

  it("keeps committed operator overlays bound to their exact replay scene", async () => {
    const user = userEvent.setup();
    renderGlass();
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.click(screen.getByRole("button", { name: /deliberate focus/i }));
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));
    expect((await screen.findAllByText(/commit 1001/i)).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("radio", { name: /later/i }));
    await screen.findByText(/separate later reconstruction/i);
    expect(screen.queryByText(/commit 1001/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /witnessed/i }));
    expect((await screen.findAllByText(/commit 1001/i)).length).toBeGreaterThan(0);
  });

  it("provides an accessible capture dialog and semantic point annotation without display price duplication", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={sink} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.click(await screen.findByRole("button", { name: /mark latest point/i }));
    const dialog = screen.getByRole("dialog", { name: /annotate the chart/i });
    const results = await axe.run(dialog, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
    await user.type(within(dialog).getByLabelText(/free-text fragment/i), "This pivot is the shape I meant.");
    await user.click(within(dialog).getByRole("button", { name: /append evidence record/i }));
    await screen.findAllByText(/commit 1001/i);

    const command = JSON.parse(sink.attemptBodies[0] ?? "null") as OperatorCommandV1;
    expect(command.commandKind).toBe("record_annotation");
    expect(sink.attemptBodies[0]).not.toContain("priceSol");
    if (command.commandKind !== "record_annotation") throw new Error("expected annotation command");
    expect(command.payload.chart.anchor).toMatchObject({ anchorKind: "point", sampleId: expect.stringMatching(/^radon:/) });
  });

  it("inspects exact scene provenance and keeps choice-context categories distinct", async () => {
    const user = userEvent.setup();
    renderGlass();
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard("i");
    const dialog = screen.getByRole("dialog", { name: /scene provenance inspector/i });
    expect(within(dialog).getByText("scene-20260816-184215-witnessed")).toBeInTheDocument();
    expect(within(dialog).getByText(mockSnapshots.witnessed.snapshotDigest)).toBeInTheDocument();
    expect(within(dialog).getByText(/^surfaced ·/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/^viewport ·/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/^interacted ·/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/marks from another replay mode are not substituted/i)).toBeInTheDocument();
  });

  it("captures an explicit interaction set rather than calling the whole feed a decision", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={sink} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard("j");
    await screen.findByRole("heading", { name: /orbitfan orbit fan club/i });
    await user.click(screen.getByRole("button", { name: /capture choices/i }));
    await user.selectOptions(screen.getByLabelText(/which honest set/i), "interacted");
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));
    await screen.findAllByText(/commit 1001/i);

    const command = JSON.parse(sink.attemptBodies[0] ?? "null") as OperatorCommandV1;
    expect(command.commandKind).toBe("record_choice_set");
    if (command.commandKind !== "record_choice_set") throw new Error("expected choice-set command");
    expect(command.payload.choiceSet).toEqual({
      setKind: "interacted",
      subjects: [{ kind: "candidate", key: "orbitfan" }],
      selectedSubject: { kind: "candidate", key: "orbitfan" },
    });
  });

  it("links a later interview to the exact quick post-action report", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={sink} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.click(screen.getByRole("button", { name: /quick report/i }));
    await user.type(screen.getByLabelText(/free-text fragment/i), "I clipped this outside Joshi because the bounce weakened.");
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));
    await screen.findAllByText(/commit 1001/i);

    await user.click(screen.getByRole("button", { name: /later interview/i }));
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));
    await screen.findAllByText(/commit 1002/i);
    const report = JSON.parse(sink.attemptBodies[0] ?? "null") as OperatorCommandV1;
    const interview = JSON.parse(sink.attemptBodies[1] ?? "null") as OperatorCommandV1;
    expect(report.commandKind).toBe("record_post_action_report");
    expect(interview.commandKind).toBe("link_interview");
    if (interview.commandKind !== "link_interview") throw new Error("expected interview link");
    expect(interview.payload.sourceCommandIds).toContain(report.commandId);
    expect(interview.payload.outcomeVisibility).toBe("hidden");
  });

  it("records episode language as an external observation rather than client-side PnL truth", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={sink} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.click(screen.getByText(/record episode meaning/i));
    await user.click(screen.getByRole("button", { name: /record partial recognition/i }));
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));
    await screen.findAllByText(/commit 1001/i);

    const command = JSON.parse(sink.attemptBodies[0] ?? "null") as OperatorCommandV1;
    expect(command.commandKind).toBe("record_gesture");
    if (command.commandKind !== "record_gesture") throw new Error("expected gesture record");
    expect(command.payload).toMatchObject({
      gestureLabel: "partial recognition observed outside Joshi",
      episodeRef: { episodeId: "episode-radon" },
      observedExternally: true,
    });
    expect(sink.attemptBodies[0]).not.toMatch(/quantity|slippage|transaction|signer/i);
  });

  it("renders all eight non-scalar exploratory fields with row-level epistemic labels", async () => {
    const sink = new OfflineFixturePresentationSink();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} presentationSink={sink} />);
    expect(await screen.findByRole("heading", { name: /field lab/i })).toBeInTheDocument();
    for (const name of ["Wallet flow", "Caller kernel", "Attention", "Order marks", "Liquidity", "PvP churn", "Lifecycle", "Field bundle"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${name}$`, "i") })).toBeInTheDocument();
    }
    expect(screen.getByText(/admitted wallet addresses and swaps may become protocol facts/i)).toBeInTheDocument();
    expect(screen.getByText(/transfer does not prove common control/i)).toBeInTheDocument();
    expect(screen.getAllByText(/^Observed$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^Inferred$/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/no scalar pressure/i)).toBeInTheDocument();
    await waitFor(() => expect(sink.sceneAttemptBodies).toHaveLength(1));
  });

  it("does not reveal any declared shell panel before the exact presentation receipt", async () => {
    const delegate = new OfflineFixturePresentationSink();
    let release: (() => Promise<void>) | undefined;
    let plannedRenderItemIds: string[] = [];
    const exposureEvents: PresentationEventV1[] = [];
    const delayedSink: PresentationSink = {
      kind: "offline_fixture",
      appendScene(scene: PresentationSceneV1, policy: PresentationPolicyV1, bundle: ExplorationBundleV1) {
        plannedRenderItemIds = scene.manifest.plannedRenderItemIds;
        return new Promise<PresentationSceneReceiptV1>((resolve, reject) => {
          release = async () => delegate.appendScene(scene, policy, bundle).then(resolve, reject);
        });
      },
      appendEvent(event: PresentationEventV1) {
        exposureEvents.push(event);
        return delegate.appendEvent(event);
      },
    };
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} presentationSink={delayedSink} />);
    expect(await screen.findByText(/staging the exact presentation policy/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /radon radon/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /field lab/i })).not.toBeInTheDocument();
    expect(exposureEvents).toHaveLength(0);
    await act(async () => { await release?.(); });
    expect(await screen.findByRole("heading", { name: /radon radon/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /field lab/i })).toBeInTheDocument();
    await waitFor(() => expect(exposureEvents).toHaveLength(plannedRenderItemIds.length));
    expect(exposureEvents.every((event) => event.eventKind === "visibility_started")).toBe(true);
    expect(exposureEvents.map((event) => event.subject.key).sort()).toEqual([...plannedRenderItemIds].sort());
  });

  it("reveals rich information with an explicit non-witnessed gap when presentation admission fails", async () => {
    const failingSink: PresentationSink = {
      kind: "offline_fixture",
      appendScene() {
        return Promise.reject(new Error("fixture presentation admission unavailable"));
      },
      appendEvent() {
        throw new Error("events must not be appended without a presentation receipt");
      },
    };
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} presentationSink={failingSink} />);
    expect(await screen.findByRole("heading", { name: /radon radon/i })).toBeInTheDocument();
    const gap = await screen.findByText(/^Presentation not witnessed:/i);
    expect(gap).toHaveAttribute("role", "alert");
    expect(gap).toHaveTextContent(/rich information is visible/i);
  });

  it("serializes presentation events so later sequence numbers cannot overtake a delayed receipt", async () => {
    const delegate = new OfflineFixturePresentationSink();
    const attempts: PresentationEventV1[] = [];
    let releaseFirst: (() => Promise<void>) | undefined;
    const delayedSink: PresentationSink = {
      kind: "offline_fixture",
      appendScene(scene, policy, bundle, signal) {
        return delegate.appendScene(scene, policy, bundle, signal);
      },
      appendEvent(event, signal) {
        attempts.push(event);
        if (attempts.length === 1) {
          return new Promise<PresentationEventReceiptV1>((resolve, reject) => {
            releaseFirst = async () => delegate.appendEvent(event, signal).then(resolve, reject);
          });
        }
        return delegate.appendEvent(event, signal);
      },
    };
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} presentationSink={delayedSink} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await waitFor(() => expect(attempts).toHaveLength(1));
    await act(async () => Promise.resolve());
    expect(attempts).toHaveLength(1);
    await act(async () => { await releaseFirst?.(); });
    await waitFor(() => expect(attempts.length).toBeGreaterThan(1));
    expect(attempts.map((event) => BigInt(event.presentationEventSeq))).toEqual(
      attempts.map((_, index) => BigInt(index + 1)),
    );
  });

  it("fails the presentation event stream closed after a missing receipt", async () => {
    const delegate = new OfflineFixturePresentationSink();
    const attempts: PresentationEventV1[] = [];
    const failingSink: PresentationSink = {
      kind: "offline_fixture",
      appendScene(scene, policy, bundle, signal) {
        return delegate.appendScene(scene, policy, bundle, signal);
      },
      appendEvent(event) {
        attempts.push(event);
        return Promise.reject(new Error("fixture durable event receipt missing"));
      },
    };
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} presentationSink={failingSink} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    expect(await screen.findByText(/fixture durable event receipt missing/i)).toBeInTheDocument();
    await act(async () => Promise.resolve());
    expect(attempts).toHaveLength(1);
  });

  it("supports keyboard field switching, pinning, comparison, and exact presentation-event receipts", async () => {
    const sink = new OfflineFixturePresentationSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} presentationSink={sink} />);
    await screen.findByRole("heading", { name: /field lab/i });
    await screen.findByText(/witnessed · commit 8001/i);

    await user.keyboard("h");
    expect(document.querySelector("#hypothesis-lab")).toHaveFocus();
    await user.keyboard("8");
    expect(await screen.findByRole("heading", { name: /coupled field bundle/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^pin$/i }));
    await user.keyboard("1");
    await user.click(screen.getByRole("button", { name: /^compare/i }));
    expect(await screen.findByRole("heading", { name: /wallet and cluster flow/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /coupled field bundle/i })).toBeInTheDocument();

    await waitFor(() => expect(sink.eventAttemptBodies.length).toBeGreaterThanOrEqual(8));
    const events = sink.eventAttemptBodies.map((body) => JSON.parse(body) as PresentationEventV1);
    expect(events.some((event) => event.eventKind === "control_changed" && event.payload.controlKind === "pin")).toBe(true);
    expect(events.some((event) => event.eventKind === "control_changed" && event.payload.controlKind === "comparison")).toBe(true);
    expect(events.some((event) => event.eventKind === "focus_started" && event.subject.key === "hypothesis-lab")).toBe(true);
  });

  it("admits exact next policy bytes and a fresh assignment before applying a policy change", async () => {
    const sink = new OfflineFixturePresentationSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} presentationSink={sink} />);
    await screen.findByText(/witnessed · commit 8001/i);
    await user.selectOptions(screen.getByLabelText(/presentation policy/i), "policy-coupled-fields-v1");
    expect(await screen.findByRole("heading", { name: /coupled field bundle/i })).toBeInTheDocument();
    await waitFor(() => expect(sink.sceneAttemptBodies).toHaveLength(2));
    const first = JSON.parse(sink.sceneAttemptBodies[0] ?? "null") as { scene: PresentationSceneV1 };
    const second = JSON.parse(sink.sceneAttemptBodies[1] ?? "null") as { policy: PresentationPolicyV1; scene: PresentationSceneV1 };
    expect(second.policy.policyId).toBe("policy-coupled-fields-v1");
    expect(second.scene.policy.policyId).toBe(second.policy.policyId);
    expect(second.scene.policy.assignmentId).not.toBe(first.scene.policy.assignmentId);
    expect(second.scene.presentationSeq).toBe("2");
  });

  it("records evidence-toggle omissions while keeping safety truth outside the lab visible", async () => {
    const sink = new OfflineFixturePresentationSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} presentationSink={sink} />);
    await screen.findByText(/witnessed · commit 8001/i);
    expect(screen.getByText(/cluster hypothesis a confidence/i)).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /^inferred$/i }));
    expect(screen.queryByText(/cluster hypothesis a confidence/i)).not.toBeInTheDocument();
    expect(screen.getByText(/row intentionally hidden by the current evidence toggle/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /source health/i })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: /exposure & episodes/i })).toBeInTheDocument();
    await waitFor(() => {
      const events = sink.eventAttemptBodies.map((body) => JSON.parse(body) as PresentationEventV1);
      expect(events.some((event) => event.eventKind === "control_changed" && event.subject.key === "inferred")).toBe(true);
    });
  });

  it("provides an accessible usefulness report without accepting client PnL", async () => {
    const sink = new OfflineFixturePresentationSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} presentationSink={sink} />);
    await screen.findByText(/witnessed · commit 8001/i);
    await user.click(screen.getByRole("button", { name: /after-action note/i }));
    const dialog = screen.getByRole("dialog", { name: /was this presentation useful/i });
    const results = await axe.run(dialog, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
    expect(within(dialog).getByText(/awaiting a reconciled, versioned accounting projection/i)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/pnl/i)).not.toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText(/overall usefulness/i), "helpful");
    await user.selectOptions(within(dialog).getByLabelText(/attention cost/i), "lower");
    await user.type(within(dialog).getByLabelText(/optional note/i), "The disagreement between fields was the useful part.");
    await user.click(within(dialog).getByRole("button", { name: /record usefulness/i }));
    await waitFor(() => {
      const events = sink.eventAttemptBodies.map((body) => JSON.parse(body) as PresentationEventV1);
      const usefulness = events.find((event) => event.eventKind === "usefulness_reported");
      expect(usefulness?.payload.pnl).toEqual({ status: "awaiting_reconciled_projection", projectionDigest: null });
      expect(JSON.stringify(usefulness)).not.toMatch(/valueSol|profit|loss/i);
    });
  });
});

/** Reaches a control with Tab alone. No pointer event exists anywhere in these paths. */
/** Every element the browser would stop on with Tab. Used to count what a change costs her. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), '
  + 'textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

/**
 * One venue readout exactly as the local core serves it, for the live bonding curve Study M0
 * measured. Every number here is one this repository's own Rust tests assert over the retained
 * `getMultipleAccounts` bytes at finalized slot 440840124; nothing in it is invented for the
 * screenshot, because a cockpit test that renders a plausible number teaches the reader to trust
 * plausible numbers.
 */
const measuredCurve: HeldVenueReadout = {
  contract: "joshi.glass.venue_readout",
  schemaVersion: 1,
  authority: "read_record_replay_only",
  mint: "BKdJofyhtW3sBgC8PGuXaawKHmrPjTdzxqaJfSpupump",
  venueKind: "Pump bonding curve",
  venueKindLabel: "pump_bonding_curve",
  venueAccount: "wrXaYnT8PBRSqigbLL3fTfHN2iYcGHCNfMwaGUKijeW",
  venueBinding: "the curve is the recomputed PDA([\"bonding-curve\", mint], Pump program) at bump 255; nothing in the curve account itself names the mint",
  feeFloorBps: "247",
  feeFloorProbeSol: "0.001000000",
  declaredLiftBps: "800",
  breakEvenClip: {
    smallestSol: "0.000277945",
    largestSol: "0.810409517",
    smallestHurdleBps: "801",
    largestHurdleBps: "801",
  },
  feeTier: {
    marketCapSol: "29.012189574",
    rowOrdinal: "1",
    rowCount: "1",
    thresholdSol: "0.000000000",
    legBps: "125",
    belowFirstThreshold: false,
    next: { absence: "This is the top row. There is no further threshold to cross." },
  },
  pessimisticTierBranch: null,
  stateAge: {
    contextSlot: "440840124",
    requestedCommitment: "finalized",
    chainToReceipt: {
      absence: "The provider stated no blockTime for this slot, so the chain end of the age is an absent record rather than an age of zero.",
    },
    receivedAtUnixMs: "1787371691252",
    clockId: "joshi-repository-fixture-write",
    drift: {
      absence: "Not measured. One observation says nothing about how fast this venue moves, and a pool measured on 2026-08-21 drifted nine to ten basis points in thirty seconds.",
    },
  },
  declaredCosts: "network fee 7,422 lamports per transaction x 2, declared by the operator and not measured for this coin",
  unsupported: [
    "the curve fee tables carry one row at threshold zero, so no market cap selects anything here",
  ],
};

/**
 * The third mint of the three measured: graduated, and as expensive as the curve above.
 *
 * Its 42.8 SOL market cap selects the fee program's first tier row at 125 basis points a leg, and
 * the next row sits at 420 SOL of market cap -- both thresholds read out of the retained
 * `PumpSwap` fee configuration. The two retained tier tables disagree at this cap, so the rates
 * are the worse of the two and the readout says so.
 */
const measuredSmallPool: HeldVenueReadout = {
  ...measuredCurve,
  mint: "AxshJi4UfQaUL2ZjF11111111111111111111111111",
  venueKind: "Graduated PumpSwap pool",
  venueKindLabel: "pumpswap_pool",
  venueAccount: "7njsrpwivXWJYYTRbpJJ1UhfnjQHrhovuMbY6GLFfbBg",
  venueBinding: "the pool account states this base mint itself, and its address is the derived address of its own index, creator and mint pair at bump 255",
  feeFloorBps: "249",
  breakEvenClip: {
    smallestSol: "0.000277945",
    largestSol: "0.810409517",
    smallestHurdleBps: "801",
    largestHurdleBps: "801",
  },
  feeTier: {
    marketCapSol: "42.800000000",
    rowOrdinal: "1",
    rowCount: "25",
    thresholdSol: "0.000000000",
    legBps: "125",
    belowFirstThreshold: false,
    next: {
      rowOrdinal: "2",
      thresholdSol: "420.000000000",
      gapSol: "377.200000000",
      gapBpsOfMarketCap: "88131",
      legBps: "120",
      direction: "cheaper",
    },
  },
  pessimisticTierBranch:
    "The retained fee tier tables disagree here (table 0 on row 1 at 125 bps a leg; table 1 on row "
    + "2 at 120 bps a leg) and no retained byte says which the program applies. Every number above "
    + "uses the most expensive of them, which errs against the trade and never for it.",
  unsupported: [
    "the address list is a declaration, not evidence: a getMultipleAccounts body is positional and names no address",
    "pool byte 245 carries quote atoms this decoder can locate and cannot name",
    "chart mark: no landed fill was read, so no chart mark is stated",
  ],
};

async function tabTo(user: ReturnType<typeof userEvent.setup>, target: HTMLElement): Promise<void> {
  for (let step = 0; step < 400 && document.activeElement !== target; step += 1) {
    await user.tab();
  }
  expect(document.activeElement).toBe(target);
}

describe("holding a coin before it scrolls away", () => {
  /**
   * The bottleneck this replaces, in Ember's words: "i literally couldn't push buttons fast
   * enough to capture the opportunity before it scrolled past me". So the gate is not that a
   * mark can be made -- it is that exactly one keystroke makes it, with no dialog to answer, no
   * field to fill and no pointer event anywhere in the test.
   */
  it("commits a hold from one keystroke with no dialog and no pointer event", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={sink} pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()} />);
    await screen.findByRole("heading", { name: /radon radon/i });

    await user.keyboard("k");
    await waitFor(() => expect(screen.getByRole("heading", { name: /fable fable market/i })).toBeInTheDocument());
    await user.keyboard(";");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(await within(rail).findByRole("heading", { name: /\$FABLE/ })).toBeInTheDocument();

    await waitFor(() => expect(sink.attemptBodies.length).toBe(1));
    const command = JSON.parse(sink.attemptBodies[0] ?? "{}") as OperatorCommandV1;
    expect(command.commandKind).toBe("record_focus");
    expect(command.subject).toEqual({ kind: "candidate", key: "fable" });
    expect(command.effectCeiling).toBe("observe_only");
    expect(command.authorityClass).toBe("evidence_only");
    expect(command.scene.sceneId).toBe(mockSnapshots.witnessed.view.sceneId);
    expect(command.scene.viewDigest).toBe(mockSnapshots.witnessed.snapshotDigest);
    if (command.commandKind !== "record_focus") throw new Error("hold must be a record_focus act");
    expect(command.payload.context.uiLabel).toBe("Hold coin");
    // Nothing was asked of her at the moment of noticing, so nothing was answered.
    expect(command.payload.context.whyNow).toBeNull();
    expect(command.payload.context.note).toBeNull();
    expect(command.payload.context.urgency).toBeNull();
    expect(command.payload.context.confidencePpm).toBeNull();
  });

  it("keeps a held coin, and its last observation, after the feed stops carrying it", async () => {
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()} />);
    await screen.findByRole("heading", { name: /radon radon/i });

    await user.keyboard("k");
    await waitFor(() => expect(screen.getByRole("heading", { name: /fable fable market/i })).toBeInTheDocument());
    await user.keyboard(";");
    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(await within(rail).findByRole("heading", { name: /\$FABLE/ })).toBeInTheDocument();
    expect(within(rail).queryByText(/stopped carrying this coin/i)).not.toBeInTheDocument();

    // Two loads later the served scene no longer carries this coin at all.
    await user.keyboard("r");
    await screen.findByText(/separate later reconstruction/i);
    await user.keyboard("r");
    await screen.findByText(/separate as-known reconstruction/i);
    expect(screen.queryByRole("button", { name: /\$FABLE/ })).not.toBeInTheDocument();

    const afterReload = screen.getByRole("region", { name: /held coins/i });
    expect(within(afterReload).getByRole("heading", { name: /\$FABLE/ })).toBeInTheDocument();
    expect(within(afterReload).getByText(/the feed stopped carrying this coin/i)).toBeInTheDocument();
    expect(within(afterReload).getByText(/not a claim about what the coin is doing now/i)).toBeInTheDocument();
    expect(within(afterReload).getByRole("button", { name: /not in this view/i })).toBeDisabled();
  });

  it("states that the venue and clip lines are unmeasured rather than printing a number", async () => {
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard(";");

    const rail = await screen.findByRole("region", { name: /held coins/i });
    const venue = within(rail).getByRole("heading", { name: /venue and clip/i }).parentElement;
    if (!venue) throw new Error("venue block did not render");
    expect(within(venue).getAllByText(/not yet measured/i)).toHaveLength(4);
    expect(within(venue).getByText(/nothing here is estimated/i)).toBeInTheDocument();
    expect(venue.textContent).not.toMatch(/\d/);
  });

  it("renders a measured readout as an interval, and a refusal as an answer", async () => {
    const user = userEvent.setup();
    render(
      <GlassApp
        dataSource={new OfflineFixtureDataSource()}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
        venueReadout={(subjectKey) => subjectKey !== "radon"
          ? null
          : { state: "measured", readout: measuredCurve }}
      />,
    );
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard(";");

    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(within(rail).getByText(/pump bonding curve/i)).toBeInTheDocument();
    expect(within(rail).getByText(/247 bps/)).toBeInTheDocument();
    // The interval, both ends, and never a single ceiling number.
    expect(within(rail).getByText(/0\.000277945 SOL to 0\.810409517 SOL/)).toBeInTheDocument();
    expect(within(rail).getByText(/an interval, not a ceiling/i)).toBeInTheDocument();
    expect(within(rail).getByText(/recomputed PDA/)).toBeInTheDocument();
    expect(within(rail).getByText(/curve fee tables carry one row/)).toBeInTheDocument();
    expect(within(rail).queryByText(/not yet measured/i)).not.toBeInTheDocument();
  });

  it("renders a lift with no break-even clip as an answer rather than a blank", async () => {
    const user = userEvent.setup();
    render(
      <GlassApp
        dataSource={new OfflineFixtureDataSource()}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
        venueReadout={() => ({
          state: "measured",
          readout: {
            ...measuredCurve,
            breakEvenClip: { refusal: "the fee floor alone exceeds the declared lift at every size" },
            unsupported: [],
          },
        })}
      />,
    );
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard(";");

    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(within(rail).getByText(/none\. the fee floor alone exceeds the declared lift/i)).toBeInTheDocument();
    // An empty "could not reconstruct" list is a claim of completeness, and is doubted out loud.
    expect(within(rail).getByText(/worth doubting rather than trusting/i)).toBeInTheDocument();
  });

  /**
   * The finding this whole lane exists to put on screen. Three real mints: a bonding curve at 247
   * basis points, a graduated pool at 60, and a second graduated pool at 249 -- graduated and as
   * expensive as the curve, because a 42.8 SOL market cap selects the fee program's first tier row
   * at 125 basis points a leg. If "graduated" were the lever those two would match; the row is the
   * lever, so the row and the distance to the next one have to be readable in a second.
   */
  it("shows which fee tier row the market cap selects and how far the next one is", async () => {
    const user = userEvent.setup();
    render(
      <GlassApp
        dataSource={new OfflineFixtureDataSource()}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
        venueReadout={() => ({ state: "measured", readout: measuredSmallPool })}
      />,
    );
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard(";");

    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(within(rail).getByText(/graduated pumpswap pool/i)).toBeInTheDocument();
    expect(within(rail).getByText(/249 bps/)).toBeInTheDocument();
    expect(within(rail).getByText(/row 1 of 25 · 125 bps a leg/i)).toBeInTheDocument();
    expect(within(rail).getByText(/42\.800000000 SOL selects the row at 0\.000000000 SOL/)).toBeInTheDocument();
    expect(within(rail).getByText(/next row 2 at 420\.000000000 SOL: 377\.200000000 SOL of market cap away/i)).toBeInTheDocument();
    expect(within(rail).getByText(/88131 bps of the current cap/)).toBeInTheDocument();
    expect(within(rail).getByText(/120 bps a leg there/)).toBeInTheDocument();
  });

  /**
   * The two `PumpSwap` tier tables disagree over a wide populated band and no retained byte says
   * which applies, so the readout uses the worse of them. Erring against the trade is correct, and
   * a reader must be able to see that a number is the pessimistic branch of an open question
   * rather than a settled measurement.
   */
  it("says out loud when a number is the pessimistic branch of an unresolved tier ambiguity", async () => {
    const user = userEvent.setup();
    render(
      <GlassApp
        dataSource={new OfflineFixtureDataSource()}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
        venueReadout={() => ({ state: "measured", readout: measuredSmallPool })}
      />,
    );
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard(";");

    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(within(rail).getByText(/retained fee tier tables disagree here/i)).toBeInTheDocument();
    expect(within(rail).getByText(/errs against the trade and never for it/i)).toBeInTheDocument();
  });

  /**
   * State age is bigger than the arithmetic. Chain to receipt was measured at eleven to thirteen
   * seconds, and one pool drifted nine to ten basis points in thirty seconds -- so its whole sixty
   * basis-point fee floor is two to four minutes of drift. A number without its age is a lie by
   * omission, so the age is on screen with the number and it keeps growing while she reads.
   */
  it("keeps the age of the reading on screen with the numbers it qualifies", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      vi.setSystemTime(new Date(Number(measuredCurve.stateAge.receivedAtUnixMs) + 12_000));
      render(
        <GlassApp
          dataSource={new OfflineFixtureDataSource()}
          pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
          venueReadout={() => ({ state: "measured", readout: measuredCurve })}
        />,
      );
      await screen.findByRole("heading", { name: /radon radon/i });
      await user.keyboard(";");

      const rail = await screen.findByRole("region", { name: /held coins/i });
      expect(within(rail).getByText(/read 12 seconds ago/i)).toBeInTheDocument();
      expect(within(rail).getByText(/slot 440840124, commitment finalized/i)).toBeInTheDocument();
      // The chain end of the age is absent on this reading, and an absent record renders as an
      // absence rather than as an age of zero.
      expect(within(rail).getByText(/absent record rather than an age of zero/i)).toBeInTheDocument();
      expect(within(rail).getByText(/one observation says nothing about how fast/i)).toBeInTheDocument();

      // And it keeps growing while the readout sits unread, because it really is growing.
      await act(async () => {
        vi.advanceTimersByTime(65_000);
      });
      await waitFor(() => expect(within(rail).getByText(/read 1 minute ago/i)).toBeInTheDocument());
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the core's own reason for having no readout, and never a blank", async () => {
    const user = userEvent.setup();
    render(
      <GlassApp
        dataSource={new OfflineFixtureDataSource()}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
        venueReadout={() => ({
          state: "absent",
          absence: "The local core was started without a venue account capture, so it has measured "
            + "no coin's fee floor or clip interval.",
        })}
      />,
    );
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard(";");

    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(within(rail).getByText(/started without a venue account capture/i)).toBeInTheDocument();
    // Not the generic placeholder: "nothing has been measured at all" and "we have not measured
    // this coin" are different things to know.
    expect(within(rail).queryByText(/not yet measured/i)).not.toBeInTheDocument();
  });

  /**
   * Every path in this cockpit is keyboard-only, and this one adds no shortcut at all: the readout
   * is prose and lists, so it is reachable by reading rather than by tabbing, and it adds no new
   * tab stop to a shell that already has too many.
   */
  it("reaches every readout line by keyboard with no pointer event and no new tab stop", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <GlassApp
        dataSource={new OfflineFixtureDataSource()}
        pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()}
        venueReadout={() => ({ state: "measured", readout: measuredSmallPool })}
      />,
    );
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard(";");
    const rail = await screen.findByRole("region", { name: /held coins/i });

    // The gaps are a list, so a screen reader can move through them by list navigation. A
    // disclosure would have been one more tab stop per held coin on a shell that already carries
    // more than fifty at first paint.
    const gaps = within(rail).getByRole("list", { name: /not reconstructed/i });
    expect(within(gaps).getAllByRole("listitem").length).toBe(measuredSmallPool.unsupported.length);

    // The readout costs zero keystrokes to get past: it is prose and lists, so every line is
    // reachable by reading and none of it is a tab stop she has to step over to reach the next
    // held coin.
    const venue = rail.querySelector(".held-venue");
    if (!venue) throw new Error("venue block did not render");
    expect(venue.querySelectorAll(FOCUSABLE)).toHaveLength(0);
    expect(venue.querySelectorAll("[aria-live]")).toHaveLength(0);

    // The card's own controls are still reached by Tab alone, with no pointer event anywhere.
    await tabTo(user, within(rail).getByRole("button", { name: /open in workbench/i }));
    expect(document.activeElement).toHaveFocus();

    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });

  it("appends a later free-text note as its own act, and refuses a blank one", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    render(<GlassApp dataSource={new OfflineFixtureDataSource()} operatorSink={sink} pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard(";");
    const rail = await screen.findByRole("region", { name: /held coins/i });
    await waitFor(() => expect(sink.attemptBodies.length).toBe(1));

    // Keyboard only, like every path in this cockpit: a disclosure, a field, a submit.
    await tabTo(user, within(rail).getByText(/add a note/i));
    await user.keyboard("{Enter}");
    await tabTo(user, within(rail).getByRole("button", { name: /append note/i }));
    await user.keyboard("{Enter}");
    expect(within(rail).getByRole("alert")).toHaveTextContent(/a note with no words is not recorded/i);
    expect(sink.attemptBodies.length).toBe(1);

    await tabTo(user, within(rail).getByLabelText(/in your own words/i));
    await user.keyboard("same wick as the one that ran yesterday");
    await tabTo(user, within(rail).getByRole("button", { name: /append note/i }));
    await user.keyboard("{Enter}");
    await waitFor(() => expect(sink.attemptBodies.length).toBe(2));
    const note = JSON.parse(sink.attemptBodies[1] ?? "{}") as OperatorCommandV1;
    if (note.commandKind !== "record_focus") throw new Error("a note must be a record_focus act");
    expect(note.subject).toEqual({ kind: "candidate", key: "radon" });
    expect(note.payload.context.uiLabel).toBe("Note on held coin");
    expect(note.payload.context.note).toBe("same wick as the one that ran yesterday");
  });

  it("keeps the held rail free of axe-detectable violations", async () => {
    const user = userEvent.setup();
    const { container } = render(<GlassApp dataSource={new OfflineFixtureDataSource()} pendingOperatorQueue={new MemoryPendingOperatorCommandQueue()} />);
    await screen.findByRole("heading", { name: /radon radon/i });
    await user.keyboard(";");
    await screen.findByRole("region", { name: /held coins/i });
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
