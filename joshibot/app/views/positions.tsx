import { useMemo, useState, type FormEvent } from "react";

import { Explain, Figure } from "@/components/figure";
import {
  Absent,
  Copyable,
  Field,
  FieldGrid,
  Panel,
  Scroller,
  StatusPill,
  Table,
  Td,
  Th,
} from "@/components/instrument";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { deletePolicy, savePolicy, type Loaded, type PolicyWrite } from "@/lib/api";
import {
  entryUnitPrice,
  originOf,
  policiesOf,
  policyRuleLabel,
  snapshotClock,
  snapshotOf,
} from "@/lib/desk";
import { cn, decimals, shortAddress, sol } from "@/lib/format";
import { clockOf, fromDecimalString, unobserved, type Measured } from "@/lib/measure";
import type { Policy, PositionRow, Snapshot } from "@/lib/types";
import { UnmonitoredBanner } from "@/views/overview";

/**
 * The rule an operator can edit.
 *
 * `cost_basis_sol` and `buy_price_sol` are STRUCTURALLY ABSENT from this type.
 *
 * The previous editor pre-filled `cost_basis_sol` with the bag's CURRENT EXIT
 * QUOTE and PUT it unmodified. That makes PnL start at 0% by construction, so a
 * "-30% stop" fires 30% below wherever the coin had already fallen to — the
 * mechanism that cost this desk 7.47 SOL on 2026-08-12. The engine now derives
 * basis from observed chain history, but a policy PUT carries origin="operator"
 * and the claim path preserves `needs_basis`, so an operator-supplied number can
 * be trusted without re-observation. The front end must therefore never be the
 * thing standing between a fabricated number and the money path.
 *
 * Keeping the fields off this type means no market value can reach a basis by
 * construction: a draft has nowhere to put one. Basis travels separately, in
 * `Basis` below, and can only originate from the engine (round-tripped verbatim)
 * or from a string a human deliberately typed.
 */
type RuleDraft = {
  name: string;
  /**
   * Three states, and they are all different rules:
   *   `undefined` — not stated. The field is omitted from the PUT and the sentinel's own
   *                 PolicyDefaults decide. The browser holds NO copy of those numbers.
   *   `null`      — switched off. This exit never fires, at any price.
   *   a number    — this threshold.
   */
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
  runner_tightness?: number | null;
  rug_exit?: boolean;
  dispose_after_break_even?: boolean;
  floor_confirm_quotes?: number;
  hold_trail_until_graduated?: boolean;
};

/**
 * Where a cost basis is allowed to come from. There is deliberately no variant
 * that derives one from a quote, a mark, or any other live market value.
 */
type Basis =
  /** New rule: send nothing. The engine observes the real basis from chain. */
  | { kind: "unset" }
  /** Existing rule: pass the engine's own observed value straight back. */
  | { kind: "engine"; cost_basis_sol: number | null; buy_price_sol: number | null }
  /** An override a human typed into an empty field, on purpose. */
  | { kind: "operator"; text: string };

/**
 * A new rule states NOTHING. Every threshold is left out of the request and filled in by the
 * sentinel, which is the only place a policy default is written down. The browser used to
 * carry its own -30/100/20 here; that was one of six copies of the same rule in this repo,
 * and they had already drifted apart.
 */
const DEFAULT_DRAFT: Omit<RuleDraft, "name"> = {};

type Editing = {
  mint: string;
  draft: RuleDraft;
  basis: Basis;
  /** The basis as opened, so cancelling an override restores it rather than nulling it. */
  original: Basis;
  existing: boolean;
};

export function Positions({
  snapshot: loaded,
  policies: policyLoad,
  now,
  onChanged,
  onChart,
}: {
  snapshot: Loaded<Snapshot>;
  policies: Loaded<{ items: Policy[]; can_execute: false }>;
  now: number;
  onChanged: () => void;
  onChart: (mint: string) => void;
}) {
  const snapshot = snapshotOf(loaded);
  const policies = policiesOf(policyLoad);
  const clock = snapshotClock(loaded);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const byMint = useMemo(() => new Map(policies.map((policy) => [policy.mint, policy])), [policies]);

  const openEditor = (mint: string, name: string) => {
    setError(null);
    const existing = byMint.get(mint);
    if (existing) {
      const loadedBasis: Basis = {
        kind: "engine",
        cost_basis_sol: existing.cost_basis_sol ?? null,
        buy_price_sol: existing.buy_price_sol ?? null,
      };
      setEditing({
        mint,
        existing: true,
        original: loadedBasis,
        draft: {
          name: existing.name,
          stop_loss_pct: existing.stop_loss_pct,
          take_profit_pct: existing.take_profit_pct,
          runner_tightness: existing.runner_tightness,
          rug_exit: existing.rug_exit,
          dispose_after_break_even: existing.dispose_after_break_even,
          floor_confirm_quotes: existing.floor_confirm_quotes,
          hold_trail_until_graduated: existing.hold_trail_until_graduated,
        },
        // Round-trip the engine's own basis verbatim. Omitting it on a PUT would
        // null an observed basis, which is its own kind of damage.
        basis: loadedBasis,
      });
      return;
    }
    setEditing({
      mint,
      existing: false,
      draft: { name, ...DEFAULT_DRAFT },
      // No basis is sent for a new rule. The rule is rug-only until the engine
      // reconstructs the real basis from observed buys.
      basis: { kind: "unset" },
      original: { kind: "unset" },
    });
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setError(null);
    try {
      // `undefined` entries are dropped by JSON.stringify, which is exactly the "let the
      // sentinel decide" semantics. `null` survives and means the exit is switched off.
      const body: PolicyWrite = { ...editing.draft };
      const basis = editing.basis;
      if (basis.kind === "engine") {
        // Exactly one of the two may be set; the server rejects both.
        if (basis.buy_price_sol != null) body.buy_price_sol = basis.buy_price_sol;
        else if (basis.cost_basis_sol != null) body.cost_basis_sol = basis.cost_basis_sol;
      } else if (basis.kind === "operator") {
        const typed = basis.text.trim();
        if (typed !== "") {
          const parsed = Number(typed);
          if (!Number.isFinite(parsed) || parsed <= 0) {
            throw new Error("cost basis must be a positive number of SOL, or left empty");
          }
          body.cost_basis_sol = parsed;
        }
      }
      await savePolicy(editing.mint, body);
      setEditing(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loaded.state === "error") {
    return (
      <Panel title="Positions" source={loaded.source} tone="alert">
        <Absent reason="error" detail={<p className="font-mono">{loaded.error}</p>} />
      </Panel>
    );
  }
  if (!snapshot) {
    return (
      <Panel title="Positions" source="/api/snapshot">
        <Absent reason="loading" />
      </Panel>
    );
  }

  return (
    <div className="space-y-3">
      <UnmonitoredBanner snapshot={snapshot} onChanged={onChanged} />

      <Panel
        title={`Positions (${snapshot.positions.length})`}
        source="/api/snapshot → positions[]"
        clock={clock}
        now={now}
        note={
          <>
            Rules live in config.yaml. Editing one writes that file; the sentinel reads it on its own
            cycle and decides for itself. This console holds no key and submits no transaction.
          </>
        }
      >
        {snapshot.positions.length === 0 ? (
          <Absent reason="no-rows" detail="No configured positions." />
        ) : (
          <Scroller>
            <Table>
              <thead>
                <tr>
                  <Th>position</Th>
                  <Th>decision</Th>
                  <Th align="right" hint="Wallet balance in UI units.">amount</Th>
                  <Th align="right" hint="Full-balance Jupiter exit quote.">exit quote</Th>
                  <Th align="right" hint="Requires an observed cost basis. Absent basis means no PnL, not 0%.">
                    pnl
                  </Th>
                  <Th hint="The engine's observed basis. Never derived from a quote.">basis</Th>
                  <Th>rule</Th>
                  <Th>flags</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {snapshot.positions.map((row) => (
                  <PositionTableRow
                    key={row.mint}
                    row={row}
                    policy={byMint.get(row.mint)}
                    loaded={loaded}
                    clock={clock}
                    onEdit={() => openEditor(row.mint, row.name)}
                    onChart={() => onChart(row.mint)}
                    onDelete={
                      byMint.has(row.mint)
                        ? async () => {
                            setDeleting(row.mint);
                            try {
                              await deletePolicy(row.mint);
                              onChanged();
                            } finally {
                              setDeleting(null);
                            }
                          }
                        : undefined
                    }
                    deleting={deleting === row.mint}
                  />
                ))}
              </tbody>
            </Table>
          </Scroller>
        )}
      </Panel>

      <Sheet open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <SheetContent className="max-w-xl overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="font-mono text-sm uppercase tracking-wider">
              {editing?.existing ? "Edit rule" : "New rule"} · {editing?.draft.name}
            </SheetTitle>
          </SheetHeader>
          {editing && (
            <RuleEditor
              editing={editing}
              onChange={setEditing}
              onSubmit={submit}
              saving={saving}
              error={error}
            />
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function PositionTableRow({
  row,
  policy,
  loaded,
  clock,
  onEdit,
  onChart,
  onDelete,
  deleting,
}: {
  row: PositionRow;
  policy: Policy | undefined;
  loaded: Loaded<Snapshot>;
  clock: ReturnType<typeof snapshotClock>;
  onEdit: () => void;
  onChart: () => void;
  onDelete?: () => void;
  deleting: boolean;
}) {
  const quoteClock = clockOf(row.quote_received_at ?? null, clock.ingest);
  const exitSol = fromDecimalString(
    row.exit_sol,
    originOf(loaded, `positions[${row.mint}].exit_sol`, quoteClock, {
      note: "Full-balance Jupiter exit quote for this position.",
    }),
  );

  const basisSol = policy?.cost_basis_sol ?? null;
  const buyPrice = policy?.buy_price_sol ?? null;
  const hasBasis = basisSol != null || buyPrice != null;

  /**
   * PnL requires a basis. Without one it is UNOBSERVED, not 0%. This is the
   * distinction the fabricated-basis defect erased.
   */
  const pnl: Measured<number> = hasBasis
    ? fromDecimalString(
        row.pnl_pct,
        originOf(loaded, `positions[${row.mint}].pnl_pct`, quoteClock, {
          kind: "derived",
          note: "Exit quote measured against the engine's observed cost basis.",
        }),
      )
    : unobserved(
        originOf(loaded, `positions[${row.mint}].pnl_pct`, quoteClock, {
          kind: "derived",
          note: "No cost basis has been observed for this position, so there is no reference to measure PnL against. This is not 0%.",
          caveats: [
            {
              kind: "unbounded",
              note: "A basis stamped from the current exit quote would make this read 0% by construction and put every stop below an already-fallen price. It is left unobserved instead.",
            },
          ],
        }),
      );

  const entry = entryUnitPrice(policy, row.ui_amount);

  return (
    <tr className="hover:bg-muted/30">
      <Td>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onChart} className="font-mono text-xs hover:text-primary">
            {row.name}
          </button>
        </div>
        <Copyable
          value={row.mint}
          display={<span className="text-[10px] text-muted-foreground">{shortAddress(row.mint)}</span>}
        />
      </Td>
      <Td>
        <Explain of={<span className="font-mono text-[11px]">{row.decision}</span>}>
          {row.decision_reason || "no reason published"}
        </Explain>
        {row.confirmed_slot != null && (
          <div className="font-mono text-[10px] text-muted-foreground">slot {row.confirmed_slot}</div>
        )}
      </Td>
      <Td align="right">
        <span className="font-mono text-[11px]">{row.ui_amount}</span>
      </Td>
      <Td align="right">
        <Figure m={exitSol} format={(value) => sol(value)} />
      </Td>
      <Td align="right">
        <Figure
          m={pnl}
          format={(value) => `${decimals(value, 2)}%`}
          className={
            pnl.state === "observed" ? (pnl.value >= 0 ? "text-lamp-ok" : "text-destructive") : undefined
          }
        />
      </Td>
      <Td>
        {hasBasis ? (
          <Explain
            of={
              <span className="font-mono text-[11px]">
                {buyPrice != null ? `${decimals(buyPrice, 9)}/u` : sol(basisSol ?? 0)}
              </span>
            }
          >
            <p>
              The engine&apos;s observed basis, read from config.yaml via /api/policies. Derived from
              observed chain history, not from any quote.
            </p>
            {entry != null && (
              <p className="mt-1 font-mono">entry unit price {entry.toExponential(4)} SOL</p>
            )}
          </Explain>
        ) : (
          <StatusPill
            label="not observed"
            tone="warn"
            help="No basis. The rule behaves as rug-only until the engine reconstructs one from observed buys. It is deliberately not filled in from the current quote."
          />
        )}
      </Td>
      <Td>
        <span className="font-mono text-[10px] text-muted-foreground">{policyRuleLabel(policy)}</span>
      </Td>
      <Td>
        <div className="flex flex-wrap gap-1">
          {row.rug?.emergency && <StatusPill label="rug" tone="bad" help={row.rug.reason ?? undefined} />}
          {row.trailing_active && <StatusPill label="trailing" tone="info" />}
          {row.stop_live === false && (
            <StatusPill
              label="stop not live"
              tone="warn"
              help={row.sl_live_after ? `Stop arms after ${row.sl_live_after}` : undefined}
            />
          )}
          {row.mint_safety && row.mint_safety.mint_authority == null && (
            <StatusPill label="mint revoked" tone="ok" help="Mint authority is null: no further supply can be minted." />
          )}
          {row.errors.map((err) => (
            <StatusPill key={err} label="error" tone="bad" help={err} />
          ))}
        </div>
      </Td>
      <Td align="right">
        <div className="flex justify-end gap-1">
          <button
            type="button"
            onClick={onEdit}
            className="rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider hover:bg-muted"
          >
            rule
          </button>
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              disabled={deleting}
              className="rounded border border-destructive/50 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-destructive hover:bg-destructive/10 disabled:opacity-50"
            >
              {deleting ? "…" : "drop"}
            </button>
          )}
        </div>
      </Td>
    </tr>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step = 1,
  hint,
}: {
  label: string;
  value: number | undefined;
  onChange: (value: number) => void;
  step?: number;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        type="number"
        step={step}
        value={value ?? ""}
        placeholder="default"
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full rounded border bg-background px-2 py-1 font-mono text-xs"
      />
    </Field>
  );
}

type ThresholdState = "default" | "off" | "set";

/**
 * A price threshold that can be absent, switched OFF, or set.
 *
 * "off" is a rule, not a missing value, and it is deliberately not reachable by typing a
 * very large negative number: the sentinel treats -95 as a stop that still fires at -96.
 */
function ThresholdField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (value: number | null | undefined) => void;
  hint?: string;
}) {
  const state: ThresholdState = value === undefined ? "default" : value === null ? "off" : "set";
  return (
    <Field label={label} hint={hint}>
      <div className="flex gap-1">
        <select
          value={state}
          onChange={(event) => {
            const next = event.target.value as ThresholdState;
            onChange(next === "default" ? undefined : next === "off" ? null : (value ?? 0));
          }}
          className="rounded border bg-background px-2 py-1 font-mono text-xs"
        >
          <option value="default">default</option>
          <option value="off">off</option>
          <option value="set">set</option>
        </select>
        {state === "set" && (
          <input
            type="number"
            step={1}
            value={value ?? 0}
            onChange={(event) => onChange(Number(event.target.value))}
            className="w-full rounded border bg-background px-2 py-1 font-mono text-xs"
          />
        )}
      </div>
    </Field>
  );
}

function Toggle({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={cn(
          "rounded border px-2 py-1 font-mono text-[10px] uppercase tracking-wider",
          checked ? "border-primary/60 bg-primary/15 text-primary" : "text-muted-foreground",
        )}
      >
        {checked ? "on" : "off"}
      </button>
    </Field>
  );
}

function RuleEditor({
  editing,
  onChange,
  onSubmit,
  saving,
  error,
}: {
  editing: Editing;
  onChange: (next: Editing) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  saving: boolean;
  error: string | null;
}) {
  const { draft, basis } = editing;
  const set = (patch: Partial<RuleDraft>) => onChange({ ...editing, draft: { ...draft, ...patch } });
  const overriding = basis.kind === "operator";

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="rounded border border-border/70">
        <p className="border-b border-border/70 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          thresholds
        </p>
        <FieldGrid columns={3}>
          <ThresholdField
            label="stop loss %"
            value={draft.stop_loss_pct}
            onChange={(value) => set({ stop_loss_pct: value })}
            hint="Negative, or off. Off means this bag is never sold for falling — the measured variance ratios say a price stop on these pools is negative-expectation."
          />
          <ThresholdField
            label="take profit %"
            value={draft.take_profit_pct}
            onChange={(value) => set({ take_profit_pct: value })}
            hint="With a runner this ARMS the lock-in floors. With the runner off it sells outright."
          />
          <ThresholdField
            label="runner tightness"
            value={draft.runner_tightness}
            onChange={(value) => set({ runner_tightness: value })}
            hint="Knob on the lock-rung table (20 = canonical), NOT a percent off the peak. Off means no trailing behaviour at all."
          />
          <NumberField
            label="floor confirm quotes"
            value={draft.floor_confirm_quotes}
            onChange={(value) => set({ floor_confirm_quotes: value })}
            hint="Consecutive quotes past the threshold before it fires, on both sides. Guards against a single bad quote."
          />
        </FieldGrid>
        <FieldGrid columns={3} className="border-t border-border/70">
          <Toggle
            label="rug exit"
            checked={draft.rug_exit ?? true}
            onChange={(value) => set({ rug_exit: value })}
            hint="Exit on a detected liquidity collapse. Works without a cost basis."
          />
          <Toggle
            label="dispose after break-even"
            checked={draft.dispose_after_break_even ?? false}
            onChange={(value) => set({ dispose_after_break_even: value })}
          />
          <Toggle
            label="hold trail until graduated"
            checked={draft.hold_trail_until_graduated ?? true}
            onChange={(value) => set({ hold_trail_until_graduated: value })}
          />
        </FieldGrid>
      </div>

      <BasisEditor editing={editing} onChange={onChange} />

      {error && <p className="font-mono text-xs text-destructive">{error}</p>}

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded border border-primary/60 bg-primary/15 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-primary disabled:opacity-50"
        >
          {saving ? "writing config.yaml…" : "write rule"}
        </button>
        <p className="text-[11px] text-muted-foreground">
          Writes config.yaml. No key, no signature, no submission.
          {overriding && basis.text.trim() !== "" && " Includes a manual basis override."}
        </p>
      </div>
    </form>
  );
}

/**
 * Basis is presented as two clearly separated things: what the engine observed
 * (read-only) and an override a human may deliberately type (empty by default).
 * Nothing here reads a quote.
 */
function BasisEditor({
  editing,
  onChange,
}: {
  editing: Editing;
  onChange: (next: Editing) => void;
}) {
  const { basis } = editing;
  const engineBasis = basis.kind === "engine" ? basis : null;
  const observedBasis =
    engineBasis && (engineBasis.cost_basis_sol != null || engineBasis.buy_price_sol != null);

  return (
    <div className="rounded border border-border/70">
      <p className="border-b border-border/70 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        cost basis
      </p>
      <div className="space-y-3 p-3">
        <div className="space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            engine-observed
          </p>
          {observedBasis && engineBasis ? (
            <div className="font-mono text-xs">
              {engineBasis.buy_price_sol != null
                ? `${decimals(engineBasis.buy_price_sol, 9)} SOL / unit`
                : sol(engineBasis.cost_basis_sol ?? 0)}
              <span className="ml-2 text-[10px] text-muted-foreground">
                round-tripped unchanged on save
              </span>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              {basis.kind === "unset"
                ? "None sent. The engine reconstructs the real basis from observed buys on chain; until it does, the rule is rug-only."
                : "The engine has not observed a basis for this position yet."}
            </p>
          )}
        </div>

        <div className="space-y-2 border-t border-border/70 pt-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() =>
                onChange({
                  ...editing,
                  basis:
                    basis.kind === "operator"
                      ? engineBasisFallback(editing)
                      : // Starts EMPTY. Never seeded from a quote, a mark, or the
                        // engine's own value.
                        { kind: "operator", text: "" },
                })
              }
              className={cn(
                "rounded border px-2 py-1 font-mono text-[10px] uppercase tracking-wider",
                basis.kind === "operator"
                  ? "border-destructive/60 bg-destructive/10 text-destructive"
                  : "text-muted-foreground",
              )}
            >
              {basis.kind === "operator" ? "override on" : "override basis"}
            </button>
            <span className="text-[11px] text-muted-foreground">
              Manual entry. Leave this alone unless you know the SOL you actually paid.
            </span>
          </div>

          {basis.kind === "operator" && (
            <div className="space-y-2">
              <input
                type="text"
                inputMode="decimal"
                placeholder="total SOL paid for this position"
                value={basis.text}
                onChange={(event) =>
                  onChange({ ...editing, basis: { kind: "operator", text: event.target.value } })
                }
                className="w-full rounded border border-destructive/50 bg-background px-2 py-1 font-mono text-xs"
              />
              <p className="text-[11px] leading-relaxed text-destructive">
                A typed basis overrides chain observation and becomes the reference every stop on
                this position is measured against. A wrong number silently mis-prices all of them.
                Entering the position&apos;s current value makes PnL read 0% by construction and puts
                the stop below an already-fallen price — that is the mechanism that cost 7.47 SOL on
                2026-08-12. Leave it empty to let the engine observe the truth.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Cancelling an override returns the basis to exactly what was loaded. */
function engineBasisFallback(editing: Editing): Basis {
  return editing.original;
}
