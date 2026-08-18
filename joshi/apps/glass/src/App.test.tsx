import axe from "axe-core";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { GlassApp } from "./App";
import type { GlassSnapshotV1 } from "./contract/v1";
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
    expect(await screen.findByText(/commit 1001/i)).toBeInTheDocument();
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
    expect(await screen.findByText(/commit 1001/i)).toBeInTheDocument();
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
    expect(await screen.findByText(/commit 1001/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /compensate/i }));
    expect(await screen.findByText(/commit 1002/i)).toBeInTheDocument();
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
    expect(await screen.findByText(/commit 1001/i)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /later/i }));
    await screen.findByText(/separate later reconstruction/i);
    expect(screen.queryByText(/commit 1001/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /witnessed/i }));
    expect(await screen.findByText(/commit 1001/i)).toBeInTheDocument();
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
    await screen.findByText(/commit 1001/i);

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
    await screen.findByText(/commit 1001/i);

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
    await screen.findByText(/commit 1001/i);

    await user.click(screen.getByRole("button", { name: /later interview/i }));
    await user.click(screen.getByRole("button", { name: /append evidence record/i }));
    await screen.findByText(/commit 1002/i);
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
    await screen.findByText(/commit 1001/i);

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
