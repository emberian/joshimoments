import { useMemo, useState, type FormEvent, type ReactNode } from "react";

import { BagCard, EmptyRoom, PageKicker, PageLede, PageTitle } from "@/components/desk";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { deletePolicy, savePolicy } from "@/lib/api";
import { bookTotalSol, deskBags, isFixedTrail, policyRuleLabel, shareOfBook, stopFiresAt } from "@/lib/desk";
import type { Policy, Snapshot } from "@/lib/types";
import { number, shortAddress } from "@/lib/utils";
import { UnmonitoredBanner } from "@/views/overview";

export function Positions({
  snapshot,
  policies,
  onChanged,
  onChart,
}: {
  snapshot: Snapshot | null;
  policies: Policy[];
  onChanged: () => void;
  onChart: (mint: string) => void;
}) {
  const [editing, setEditing] = useState<Policy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const byMint = useMemo(() => new Map(policies.map((policy) => [policy.mint, policy])), [policies]);
  const bags = deskBags(snapshot);
  const total = bookTotalSol(bags);

  const openNew = (mint: string, name: string, exitSol?: string | null) => {
    setError(null);
    const existing = byMint.get(mint);
    if (existing) {
      setEditing({ ...existing, exit_style: existing.exit_style ?? "runner" });
      return;
    }
    const quoted = exitSol == null || exitSol === "" ? Number.NaN : Number(exitSol);
    setEditing({
      mint,
      name,
      cost_basis_sol: Number.isFinite(quoted) ? quoted : null,
      stop_loss_pct: -30,
      take_profit_pct: 100,
      trailing_stop_pct: 20,
      rug_exit: true,
      dispose_after_break_even: false,
      exit_style: "runner",
      floor_confirm_quotes: 2,
      hold_trail_until_graduated: true,
    });
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setError(null);
    try {
      const { mint, ...body } = editing;
      await savePolicy(mint, body);
      setEditing(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "save failed");
    } finally {
      setSaving(false);
    }
  };

  const previewExit = editing ? bags.find((bag) => bag.mint === editing.mint)?.exit_sol : null;
  const fireAt = editing ? stopFiresAt(previewExit, editing.stop_loss_pct) : null;

  return (
    <div className="space-y-6">
      <div>
        <PageKicker>Positions</PageKicker>
        <PageTitle>Exit rules</PageTitle>
        <PageLede>
          Configure stop / runner floors / rug / dispose. Writes config.yaml only. Cannot execute. Cannot arm.
        </PageLede>
      </div>
      <UnmonitoredBanner snapshot={snapshot} onChanged={onChanged} />

      {bags.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {bags.map((bag) => {
            const policy = byMint.get(bag.mint);
            return (
              <BagCard
                key={bag.mint}
                bag={bag}
                share={shareOfBook(bag, total)}
                policy={policy}
                policyLabel={policyRuleLabel(policy, bag)}
                onChart={() => onChart(bag.mint)}
                onProtect={() => openNew(bag.mint, bag.name, bag.exit_sol)}
                onDelete={
                  policy
                    ? async () => {
                        setDeleting(bag.mint);
                        try {
                          await deletePolicy(bag.mint);
                          onChanged();
                        } finally {
                          setDeleting(null);
                        }
                      }
                    : undefined
                }
                deleting={deleting === bag.mint}
                limits={
                  policy ? (
                    <InlineLimits
                      key={`${policy.mint}-${policy.stop_loss_pct}-${policy.take_profit_pct}-${policy.trailing_stop_pct}-${policy.exit_style ?? "runner"}`}
                      policy={policy}
                      onCommit={async (next) => {
                        const { mint, ...body } = next;
                        await savePolicy(mint, body);
                        onChanged();
                      }}
                    />
                  ) : null
                }
              />
            );
          })}
        </div>
      ) : (
        <EmptyRoom title="No holdings." lede="When a bag lands on shitcoims it will appear here, unprotected, until you write a rule." />
      )}

      <Sheet open={Boolean(editing)} onOpenChange={(open) => !open && setEditing(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle className="font-display text-2xl font-medium">{editing?.name ?? "Policy"}</SheetTitle>
            <SheetDescription>Writes config.yaml only. Cannot execute. Cannot arm.</SheetDescription>
          </SheetHeader>
          {editing && (
            <form className="flex flex-1 flex-col gap-5 overflow-y-auto" onSubmit={submit}>
              <div className="rounded-lg border bg-muted/30 p-3 font-mono text-[11px] text-muted-foreground">
                {shortAddress(editing.mint)}
              </div>
              <Field label="Name">
                <Input value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} />
              </Field>
              <Field label="Cost basis SOL (total paid)">
                <Input
                  type="number"
                  step="0.0001"
                  value={editing.cost_basis_sol ?? ""}
                  onChange={(event) =>
                    setEditing({
                      ...editing,
                      cost_basis_sol: event.target.value === "" ? null : Number(event.target.value),
                      buy_price_sol: null,
                    })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Leave empty for rug-only. Defaults to this bag&apos;s quoted exit when present — never a fake 0.1.
                </p>
              </Field>
              <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                <div className="pr-3">
                  <Label htmlFor="exit-style">Runner lock-in floors</Label>
                  <p className="text-[11px] text-muted-foreground">
                    Off uses the old trail-%-of-peak leash.
                  </p>
                </div>
                <Switch
                  id="exit-style"
                  checked={!isFixedTrail(editing.exit_style)}
                  onCheckedChange={(on) =>
                    setEditing({ ...editing, exit_style: on ? "runner" : "fixed_trail" })
                  }
                />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Stop %">
                  <Input
                    type="number"
                    value={editing.stop_loss_pct}
                    onChange={(event) => setEditing({ ...editing, stop_loss_pct: Number(event.target.value) })}
                  />
                </Field>
                <Field label={isFixedTrail(editing.exit_style) ? "Take profit %" : "Arm runner at +%"}>
                  <Input
                    type="number"
                    value={editing.take_profit_pct}
                    onChange={(event) => setEditing({ ...editing, take_profit_pct: Number(event.target.value) })}
                  />
                </Field>
                <Field label={isFixedTrail(editing.exit_style) ? "Trail %" : "Tightness"}>
                  <Input
                    type="number"
                    value={editing.trailing_stop_pct}
                    onChange={(event) => setEditing({ ...editing, trailing_stop_pct: Number(event.target.value) })}
                  />
                </Field>
              </div>
              {!isFixedTrail(editing.exit_style) && (
                <p className="text-xs text-muted-foreground">
                  Tightness 20 = canonical floors; lower = tighter; not a % leash.
                </p>
              )}
              {fireAt != null && (
                <p className="text-xs text-muted-foreground">
                  From the current quote, a {editing.stop_loss_pct}% stop would fire near{" "}
                  <span className="font-mono tnum text-foreground">{number(fireAt, 4)} SOL</span>.
                  {editing.cost_basis_sol == null && " Empty basis means this stop will not arm — rug-only."}
                </p>
              )}
              <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                <Label htmlFor="rug">Rug exit</Label>
                <Switch id="rug" checked={editing.rug_exit} onCheckedChange={(rug_exit) => setEditing({ ...editing, rug_exit })} />
              </div>
              <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                <Label htmlFor="dispose">Dispose after break-even</Label>
                <Switch
                  id="dispose"
                  checked={editing.dispose_after_break_even}
                  onCheckedChange={(dispose_after_break_even) => setEditing({ ...editing, dispose_after_break_even })}
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <div className="mt-auto flex gap-2">
                <Button type="submit" disabled={saving}>
                  {saving ? "Saving…" : "Save policy"}
                </Button>
                {byMint.has(editing.mint) && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={async () => {
                      await deletePolicy(editing.mint);
                      setEditing(null);
                      onChanged();
                    }}
                  >
                    Remove
                  </Button>
                )}
              </div>
            </form>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function InlineLimits({
  policy,
  onCommit,
}: {
  policy: Policy;
  onCommit: (policy: Policy) => Promise<void>;
}) {
  const [draft, setDraft] = useState(policy);
  const [busy, setBusy] = useState(false);
  const fixed = isFixedTrail(policy.exit_style);
  const dirty =
    draft.stop_loss_pct !== policy.stop_loss_pct ||
    draft.take_profit_pct !== policy.take_profit_pct ||
    draft.trailing_stop_pct !== policy.trailing_stop_pct;
  return (
    <div className="space-y-2 rounded-lg border bg-muted/20 p-3">
      <div className="grid grid-cols-3 gap-2">
        <TinyField
          label="SL %"
          value={draft.stop_loss_pct}
          onChange={(stop_loss_pct) => setDraft({ ...draft, stop_loss_pct })}
        />
        <TinyField
          label={fixed ? "TP % (arms trail)" : "Arm at +%"}
          value={draft.take_profit_pct}
          onChange={(take_profit_pct) => setDraft({ ...draft, take_profit_pct })}
        />
        <TinyField
          label={fixed ? "Trail % of peak" : "Tightness"}
          value={draft.trailing_stop_pct}
          onChange={(trailing_stop_pct) => setDraft({ ...draft, trailing_stop_pct })}
        />
      </div>
      {!fixed && (
        <p className="text-[10px] text-muted-foreground">
          20 = canonical floors; lower = tighter; not a % leash.
        </p>
      )}
      {dirty && (
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void onCommit(draft).finally(() => setBusy(false));
          }}
        >
          {busy ? "Writing…" : "Save limits"}
        </Button>
      )}
    </div>
  );
}

function TinyField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="space-y-1">
      <span className="block font-mono text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <Input
        type="number"
        className="h-8 font-mono tnum text-xs"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
