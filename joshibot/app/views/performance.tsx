import { useEffect, useState } from "react";

import { PageKicker, PageLede, PageTitle } from "@/components/desk";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { loadPerformance } from "@/lib/api";
import type { Performance as PerformanceModel } from "@/lib/types";
import { number } from "@/lib/utils";

export function Performance() {
  const [stats, setStats] = useState<PerformanceModel | null>(null);
  useEffect(() => {
    void loadPerformance()
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <PageKicker>Performance</PageKicker>
        <PageTitle>Desk statistics</PageTitle>
        <PageLede>Realized SOL only counts landed exits. Unrealized is the current full-balance quote.</PageLede>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <Stat label="Unrealized (quoted)" value={`${number(stats?.portfolio_exit_sol, 4)} SOL`} />
        <Stat label="Realized exits" value={`${number(stats?.realized_sol, 4)} SOL`} />
        <Stat label="Fills" value={String(stats?.trade_count ?? 0)} />
        <Stat label="Protected policies" value={String(stats?.protected_positions ?? 0)} />
        <Stat label="Observe-only" value={String(stats?.observe_only ?? 0)} />
        <Stat label="Last exit" value={stats?.last_exit_at ?? "never"} />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Event mix</CardTitle>
          <CardDescription>Severity counts from the local journal</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4 text-sm">
          {Object.entries(stats?.event_counts ?? {}).map(([key, count]) => (
            <div key={key} className="rounded-lg border px-3 py-2">
              <span className="text-muted-foreground">{key}</span> <strong className="font-mono tnum">{count}</strong>
            </div>
          ))}
          {!stats && <p className="text-muted-foreground">Performance API unavailable.</p>}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="font-mono tnum text-xl">{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}
