import axe from "axe-core";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { GlassApp } from "./App";
import { OfflineFixtureDataSource } from "./data/client";
import { mockSnapshots } from "./data/mockSnapshot";
import { INSPECT_ASSERTION_UI_LABEL, isViewportAssertion, POINTED_ASSERTION_UI_LABEL, VIEWPORT_ASSERTION_UI_LABEL } from "./operator/attention";
import type { OperatorCommandV1 } from "./operator/contract";
import { OfflineFixtureOperatorSink } from "./operator/client";
import { MemoryPendingOperatorCommandQueue } from "./operator/pendingQueue";

const FOCUSABLE =
  'a[href]:not([tabindex="-1"]), button:not([disabled]):not([tabindex="-1"]), '
  + 'input:not([disabled]):not([tabindex="-1"]), select:not([disabled]):not([tabindex="-1"]), '
  + 'textarea:not([disabled]):not([tabindex="-1"]), summary:not([tabindex="-1"]), '
  + '[tabindex]:not([tabindex="-1"])';

function renderHunt(sink?: OfflineFixtureOperatorSink) {
  return render(
    <GlassApp
      dataSource={new OfflineFixtureDataSource()}
      initialSurface="hunt"
      {...(sink ? { operatorSink: sink, pendingOperatorQueue: new MemoryPendingOperatorCommandQueue() } : {})}
    />,
  );
}

async function boardSettled(container: HTMLElement): Promise<void> {
  await screen.findByRole("region", { name: /hunt board/i });
  await waitFor(() => expect(container.querySelectorAll("[data-candidate-id]").length).toBeGreaterThan(0));
}

/**
 * The hunt lens: the dense scannable board Ember asked for after sitting in the evidence
 * cockpit — "i don't see a feed... this is overwhelming". One board, tight rows, the truth
 * in chips instead of paragraphs, and the workbench one gesture away instead of on top of
 * everything.
 */
describe("hunt surface", () => {
  it("opens into one dense board — no workbench, no rails — with the facts on every row", async () => {
    const { container } = renderHunt();
    await boardSettled(container);

    // The board leads; the inspect furniture does not compete for the glance.
    expect(screen.queryByRole("heading", { name: /radon radon/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /witnessed replay/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /operator evidence/i })).not.toBeInTheDocument();

    // One honest scene line remains.
    expect(screen.getByText(new RegExp(`Scene ${mockSnapshots.witnessed.view.sceneId}`))).toBeInTheDocument();
    expect(screen.getByText(/witnessed · rendered/i)).toBeInTheDocument();

    // The Movers default leads the board with coins that carry data (which rows jsdom's
    // window mounts is a virtualizer artifact, but the selected row is always pinned
    // mounted): by claimed 24h volume radon (x3) sits 3rd behind fable (x9) and moss (x6),
    // and the basis line states the applied default. And a row is a one-line read: ticker,
    // name, mcap, signed 5m move, age, and a sparkline for a carried path.
    const radonRow = screen.getByRole("option", { name: /\$RADON/ });
    expect(radonRow).toHaveAttribute("aria-posinset", "3");
    expect(screen.getByText(/movers: largest claimed 24h volume first/i)).toBeInTheDocument();
    expect(radonRow).toHaveAttribute("aria-setsize", "9");
    expect(within(radonRow).getByText("Radon")).toBeInTheDocument();
    expect(within(radonRow).getByText("$168.4K")).toBeInTheDocument();
    expect(within(radonRow).getByText("+3.12%")).toBeInTheDocument();
    expect(within(radonRow).getByText("1h 5m")).toBeInTheDocument();
    expect(radonRow.querySelector(".sparkline")).not.toBeNull();

    // The board panel costs exactly five tab stops, every multi-control strip collapsed to a
    // roving tabindex: the table/grid layout toggle, the trending strip, the filter tabs, the
    // sort-header toolbar, and the listbox — which is still the same single listbox with the
    // same channels, so density did not buy a tab-stop tax or new attention semantics.
    const board = screen.getByRole("region", { name: /hunt board/i });
    const boardStops = [...container.querySelectorAll<HTMLElement>(FOCUSABLE)]
      .filter((stop) => board.contains(stop))
      .map((stop) => stop.getAttribute("role") ?? `${stop.tagName.toLowerCase()}:${stop.className.split(" ")[0]}`);
    expect(boardStops).toEqual([
      "radio",
      "button:trending-item",
      "radio",
      "radio",
      "button:board-sort-button",
      "listbox",
    ]);
  });

  /**
   * The venue scope: pump went multichain, every JOSHI instrument is Solana-only, and Ember
   * hunts Solana — so a coin POSITIVELY claimed on another chain does not lead the default
   * board. It is never silently gone (the basis counts it, "All chains" is one click), an
   * unknown chain is never assumed foreign or Solana, and under "All chains" the foreign
   * coin wears its loud chain chip so it reads as a different venue, not a broken mint.
   */
  it("scopes the hunt to her venue by default, other chains one explicit click away", async () => {
    const user = userEvent.setup();
    const { container } = renderHunt();
    await boardSettled(container);

    expect(screen.queryByRole("option", { name: /\$ZORB/ })).not.toBeInTheDocument();
    expect(screen.getByText(/solana venue \(1 other-chain hidden\)/i)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /^all chains$/i }));
    const zorbit = await screen.findByRole("option", { name: /\$ZORB/ });
    const chip = within(zorbit).getByText("eip155");
    expect(chip.getAttribute("title")).toContain("eip155:8453");
    expect(chip.getAttribute("title")).toContain("Solana-only");
    // A Solana claim wears the subtle mark; an unknown chain wears nothing at all.
    expect(within(screen.getByRole("option", { name: /\$RADON/ })).getByText("sol")).toBeInTheDocument();
    const orbitfan = screen.getByRole("option", { name: /\$ORBITFAN/ });
    expect(within(orbitfan).queryByText("sol")).not.toBeInTheDocument();
    expect(within(orbitfan).queryByText(/eip155/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /^solana$/i }));
    await waitFor(() => expect(screen.queryByRole("option", { name: /\$ZORB/ })).not.toBeInTheDocument());
  });

  /**
   * The channel-preservation claim: the board feeds the SAME attention channels through the
   * SAME shell accumulators as the inspect feed, so a hold from the board carries the same
   * honest viewport and pointed assertions the selection instrument pre-registered.
   */
  it("holds from the board with one keystroke and carries the same attention assertions", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    const { container } = renderHunt(sink);
    await boardSettled(container);

    // She hovers a row she never selected: pointer is its own channel and moves nothing.
    const board = screen.getByRole("region", { name: /hunt board/i });
    await user.hover(await within(board).findByRole("option", { name: /\$MOSS/ }));
    expect(screen.getByRole("option", { name: /\$RADON/ })).toHaveAttribute("aria-selected", "true");

    await user.keyboard(";");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(
      sink.attemptBodies.map((body) => {
        const command = JSON.parse(body) as OperatorCommandV1;
        return command.commandKind === "record_choice_set"
          ? (command.payload as { context: { uiLabel: string } }).context.uiLabel
          : command.commandKind;
      }),
    ).toEqual(["record_focus", VIEWPORT_ASSERTION_UI_LABEL, POINTED_ASSERTION_UI_LABEL]));

    const hold = JSON.parse(sink.attemptBodies[0] ?? "{}") as OperatorCommandV1;
    expect(hold.commandKind).toBe("record_focus");
    expect(hold.subject).toEqual({ kind: "candidate", key: "radon" });
    expect(hold.scene.sceneId).toBe(mockSnapshots.witnessed.view.sceneId);

    const viewport = JSON.parse(sink.attemptBodies[1] ?? "{}") as OperatorCommandV1;
    if (viewport.commandKind !== "record_choice_set") throw new Error("expected a viewport assertion");
    expect(viewport.payload.choiceSet.subjects.map((subject) => subject.key)).toEqual(["moss", "radon"]);
    const pointed = JSON.parse(sink.attemptBodies[2] ?? "{}") as OperatorCommandV1;
    if (pointed.commandKind !== "record_choice_set") throw new Error("expected a pointed assertion");
    expect(pointed.payload.choiceSet.subjects.map((subject) => subject.key)).toEqual(["moss"]);
    expect(isViewportAssertion(viewport)).toBe(true);

    // The held rail is on the hunt surface too: the hold is visible where she is racing.
    const rail = await screen.findByRole("region", { name: /held coins/i });
    expect(await within(rail).findByRole("heading", { name: /\$RADON/ })).toBeInTheDocument();
  });

  /**
   * The grid keeps the sacred invariant: it is the SAME listbox, virtualizer, and channels —
   * only what a row paints changed — so a hover and a hold in grid layout land the exact
   * same durable records a table hold lands, and the gesture binds the same selected coin.
   */
  it("keeps every attention channel and the hold binding identical under the grid layout", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    const { container } = renderHunt(sink);
    await boardSettled(container);

    await user.click(screen.getByRole("radio", { name: /^grid$/i }));
    await waitFor(() => expect(container.querySelector(".grid-card")).not.toBeNull());
    // Same single listbox; the cards are still its options.
    expect(container.querySelectorAll("[role='listbox']")).toHaveLength(1);

    const board = screen.getByRole("region", { name: /hunt board/i });
    await user.hover(await within(board).findByRole("option", { name: /\$MOSS/ }));
    // Pointer still moves nothing: the selection (and therefore the `;` target) stays radon.
    expect(screen.getByRole("option", { name: /\$RADON/ })).toHaveAttribute("aria-selected", "true");

    await user.keyboard(";");
    await waitFor(() => expect(
      sink.attemptBodies.map((body) => {
        const command = JSON.parse(body) as OperatorCommandV1;
        return command.commandKind === "record_choice_set"
          ? (command.payload as { context: { uiLabel: string } }).context.uiLabel
          : command.commandKind;
      }),
    ).toEqual(["record_focus", VIEWPORT_ASSERTION_UI_LABEL, POINTED_ASSERTION_UI_LABEL]));
    const hold = JSON.parse(sink.attemptBodies[0] ?? "{}") as OperatorCommandV1;
    expect(hold.subject).toEqual({ kind: "candidate", key: "radon" });
    const pointed = JSON.parse(sink.attemptBodies[2] ?? "{}") as OperatorCommandV1;
    if (pointed.commandKind !== "record_choice_set") throw new Error("expected a pointed assertion");
    expect(pointed.payload.choiceSet.subjects.map((subject) => subject.key)).toEqual(["moss"]);
  });

  it("gives the tabs real data semantics and states each tab's basis", async () => {
    const user = userEvent.setup();
    const { container } = renderHunt();
    await boardSettled(container);

    // The selected radon row is always pinned mounted, so its stated set position is the
    // jsdom-stable witness of each tab's ordering: 3rd mover under All (the default sort,
    // stated), 4th-largest |5m| move under Trending, 7th-youngest age under New — the sort
    // tabs keep their own rank because the Movers default never shadows a tab that IS a rank.
    const radonRow = () => screen.getByRole("option", { name: /\$RADON/ });
    expect(radonRow()).toHaveAttribute("aria-posinset", "3");
    expect(screen.getByText(/movers: largest claimed 24h volume first/i)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /^trending$/i }));
    await waitFor(() => expect(radonRow()).toHaveAttribute("aria-posinset", "4"));
    // The venue clause prefixes every basis, so the tab sentence is matched inside it.
    expect(screen.getByText(/largest 5-minute move first, either direction\./i)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /^new$/i }));
    await waitFor(() => expect(radonRow()).toHaveAttribute("aria-posinset", "7"));
    expect(screen.getByText(/youngest observed age first\./i)).toBeInTheDocument();

    // A category tab: only the coin the scene marks live remains, and it says so.
    await user.click(screen.getByRole("radio", { name: /^live$/i }));
    const mossRow = await screen.findByRole("option", { name: /\$MOSS/ });
    await waitFor(() => expect(mossRow).toHaveAttribute("aria-setsize", "1"));
    expect(mossRow).toHaveAttribute("aria-posinset", "1");
    // The category filter clause stays in front of the default's own sentence.
    expect(screen.getByText(/marks live · movers: largest claimed 24h volume first/i)).toBeInTheDocument();
  });

  it("switches lenses cheaply both ways, keeping selection, holds, and the scene", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    const { container } = renderHunt(sink);
    await boardSettled(container);

    await user.keyboard("j");
    await waitFor(() => expect(screen.getByRole("option", { name: /\$WETPAINT/ })).toHaveAttribute("aria-selected", "true"));
    await user.keyboard(";");
    await screen.findByRole("region", { name: /held coins/i });

    // Keyboard to inspect: the full evidence workbench, on the SAME selected coin, with the
    // hold still held — even though the inspect column keeps served order (the Movers
    // default is the hunt board's), because selection binds by id, never by position.
    await user.keyboard("'");
    expect(await screen.findByRole("heading", { name: /wetpaint wet paint/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /witnessed replay/i })).toBeInTheDocument();
    const rail = screen.getByRole("region", { name: /held coins/i });
    expect(within(rail).getByRole("heading", { name: /\$WETPAINT/ })).toBeInTheDocument();

    // Pointer back to hunt: the header button is the same act.
    await user.click(screen.getByRole("button", { name: /switch to the hunt lens/i }));
    await screen.findByRole("region", { name: /hunt board/i });
    expect(screen.getByRole("option", { name: /\$WETPAINT/ })).toHaveAttribute("aria-selected", "true");
    expect(within(screen.getByRole("region", { name: /held coins/i })).getByRole("heading", { name: /\$WETPAINT/ })).toBeInTheDocument();
  });

  /**
   * Focusing in is a sensing request: entering the inspect lens on a coin emits the automatic
   * hot-scope assertion so the keeper starts tapping its candles while attention is on it.
   * Scene-subject on purpose — the selection instrument scores candidate-named acts as picks,
   * and an automatic record must never mark a coin chosen — and debounced per (scene, coin)
   * exactly like the viewport assertion's unchanged-set skip.
   */
  it("entering inspect emits one scene-subject hot-scope assertion per coin per scene", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    const { container } = renderHunt(sink);
    await boardSettled(container);

    const posted = () => sink.attemptBodies
      .map((body) => JSON.parse(body) as OperatorCommandV1)
      .filter((command) => command.commandKind === "request_hot_scope");

    await user.keyboard("'");
    await screen.findByRole("heading", { name: /radon radon/i });
    await waitFor(() => expect(posted().length).toBe(1));
    const inspect = posted()[0]!;
    expect(inspect.subject).toEqual({ kind: "scene", key: mockSnapshots.witnessed.view.sceneId });
    if (inspect.commandKind !== "request_hot_scope") throw new Error("expected the inspect assertion");
    expect(inspect.payload.scope.subject).toEqual({ kind: "mint", key: "RADON9BkJ3Wj5mT8p2Qx7sV4nL6cH1fZ" });
    expect(inspect.payload.context.uiLabel).toBe(INSPECT_ASSERTION_UI_LABEL);
    expect(isViewportAssertion(inspect)).toBe(true);

    // Out and straight back in on the same coin in the same scene: debounced, not re-posted.
    await user.keyboard("'");
    await screen.findByRole("region", { name: /hunt board/i });
    await user.keyboard("'");
    await screen.findByRole("heading", { name: /radon radon/i });
    expect(posted().length).toBe(1);

    // A different coin is fresh attention: back to the board, move, inspect again.
    await user.keyboard("'");
    await screen.findByRole("region", { name: /hunt board/i });
    await user.keyboard("j");
    await user.keyboard("'");
    await waitFor(() => expect(posted().length).toBe(2));
    const second = posted()[1]!;
    if (second.commandKind !== "request_hot_scope") throw new Error("expected the inspect assertion");
    expect(second.payload.scope.subject.key).toBe("WETPT6NcQ3vM9sL2pT8kR5bD1jHxZaF");
  });

  /**
   * The click-through: pump.fun's board is one click from any coin's page, and so is this
   * one. A row click (or Enter on the active row) opens the coin page — the inspect lens led
   * by the coin — recording the SAME focus-in assertion the `'` switch records, debounced per
   * (scene, coin) across both entry paths. Space stays selection-only, so the keyboard keeps
   * a way to mark a row without leaving the board; pointer motion still moves nothing.
   */
  it("opens the coin page from a board row with one click, sharing the focus-in assertion", async () => {
    const sink = new OfflineFixtureOperatorSink();
    const user = userEvent.setup();
    const { container } = renderHunt(sink);
    await boardSettled(container);

    const posted = () => sink.attemptBodies
      .map((body) => JSON.parse(body) as OperatorCommandV1)
      .filter((command) => command.commandKind === "request_hot_scope");

    // One click: the page opens on the clicked coin — not on whatever was selected — with the
    // coin page's own furniture (the acts, the microstructure slots) present.
    await user.click(await screen.findByRole("option", { name: /\$MOSS/ }));
    expect(await screen.findByRole("heading", { level: 1, name: /\$MOSS/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /hold/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /venue & instruments/i })).toBeInTheDocument();
    await waitFor(() => expect(posted().length).toBe(1));
    const inspect = posted()[0]!;
    if (inspect.commandKind !== "request_hot_scope") throw new Error("expected the inspect assertion");
    expect(inspect.subject.kind).toBe("scene");

    // Back to the board and straight back in on the same coin: the assertion is debounced
    // across entry paths, exactly as it is across repeated `'` flips.
    await user.keyboard("'");
    await screen.findByRole("region", { name: /hunt board/i });
    const listbox = screen.getByRole("listbox");
    listbox.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { level: 1, name: /\$MOSS/ })).toBeInTheDocument();
    expect(posted().length).toBe(1);

    // Space on the board selects without navigating: the board is still the page.
    await user.keyboard("'");
    await screen.findByRole("region", { name: /hunt board/i });
    screen.getByRole("listbox").focus();
    await user.keyboard(" ");
    expect(screen.getByRole("region", { name: /hunt board/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: /\$MOSS/ })).not.toBeInTheDocument();
  });

  it("has no automatically detectable accessibility violations on the hunt surface", async () => {
    const { container } = renderHunt();
    await boardSettled(container);
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});
