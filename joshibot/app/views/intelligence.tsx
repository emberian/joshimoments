import { Lamp, PageKicker, PageLede, PageTitle } from "@/components/desk";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { IntelligenceSnapshot } from "@/lib/types";
import { age, BASE58_ADDRESS, shortAddress } from "@/lib/utils";

export function Intelligence({ intel, now }: { intel: IntelligenceSnapshot | null; now: number }) {
  const kols = new Map<string, { handle: string; summary: string; cashtags: string[]; url: string | null; when: string | null }>();
  for (const item of intel?.inbox ?? []) {
    const handle = item.watched_handle || (item.kind === "x_kol_post" ? item.author : null);
    if (!handle || kols.has(handle)) continue;
    kols.set(handle, {
      handle,
      summary: item.summary,
      cashtags: item.cashtags,
      url: item.url,
      when: item.observed_at,
    });
  }
  const service = intel?.service;
  const tone = service?.status === "healthy" ? "ok" : "warn";

  return (
    <div className="space-y-6">
      <div>
        <PageKicker>Intelligence</PageKicker>
        <PageTitle>Observatory</PageTitle>
        <PageLede>
          Claims become hypotheses. None of it can touch the signer. CANNOT EXECUTE. KOL BOARD and X / APIFY TAPE live
          here. Watchlist x-kols is the configured handle set.
        </PageLede>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Lamp tone={tone} live={service?.cycle_in_progress} />
        <Badge>{service?.status ?? "offline"}</Badge>
        <Badge variant="outline">{service?.collectors_active ?? 0} collectors</Badge>
        <Badge variant="outline">{service?.x_items_today ?? 0} X items today</Badge>
        {service?.last_cycle_partial && <Badge variant="warning">partial cycle</Badge>}
        {service?.last_error && <span className="text-muted-foreground">{service.last_error}</span>}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Sieve</CardTitle>
          <CardDescription>
            pass = look. veto = serial/wash. watch_exit = KOL named a bag you hold. skip = not enough tape.
            Never a buy order. execution_effect none.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {(intel?.candidates ?? []).slice(0, 12).map((card) => (
            <div key={card.mint} className="flex items-start justify-between gap-3 border-b py-2 last:border-0">
              <div>
                <div className="flex items-center gap-2">
                  <Badge
                    variant={
                      card.verdict === "veto"
                        ? "destructive"
                        : card.verdict === "watch_exit"
                          ? "warning"
                          : card.verdict === "pass"
                            ? "default"
                            : "secondary"
                    }
                  >
                    {card.verdict}
                  </Badge>
                  <span className="font-mono text-xs">{card.name || shortAddress(card.mint)}</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{card.reasons[0]}</p>
              </div>
            </div>
          ))}
          {!intel?.candidates.length && (
            <p className="text-sm text-muted-foreground">No candidate cards this window.</p>
          )}
        </CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>KOL BOARD</CardTitle>
            <CardDescription>watched handles · cashtags stay labels</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {[...kols.values()].map((kol) => (
              <article key={kol.handle} className="rounded-lg border bg-muted/20 p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="font-mono text-sm text-primary">@{kol.handle}</div>
                  <span className="font-mono text-[10px] text-muted-foreground">{age(kol.when, now)}</span>
                </div>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{kol.summary}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {kol.cashtags.map((tag) => (
                    <Badge key={tag} variant="warning">
                      ${tag}
                    </Badge>
                  ))}
                </div>
              </article>
            ))}
            {!kols.size && <p className="text-sm text-muted-foreground">No watched handles in the current window.</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>X / APIFY TAPE</CardTitle>
            <CardDescription>Cashtags stay labels until a mint URL appears.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-0">
            {(intel?.x_tape ?? []).slice(0, 10).map((item) => (
              <article key={item.id} className="border-b py-3 last:border-0">
                <div className="flex justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
                  <span>{item.author ? `@${item.author}` : item.kind}</span>
                  <span>{age(item.observed_at, now)}</span>
                </div>
                <p className="mt-1 text-sm leading-relaxed">{item.summary}</p>
                <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
                  {item.mint_candidates
                    .filter((mint) => BASE58_ADDRESS.test(mint))
                    .map((mint) => (
                      <a
                        key={mint}
                        className="text-primary"
                        href={`https://solscan.io/token/${mint}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {shortAddress(mint)}
                      </a>
                    ))}
                </div>
              </article>
            ))}
            {!intel?.x_tape.length && <p className="py-6 text-sm text-muted-foreground">Tape is empty this window.</p>}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Evidence inbox</CardTitle>
          <CardDescription>fact / claim / speculation. Contradicting evidence is shown when present.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {(intel?.inbox ?? []).slice(0, 16).map((item) => (
            <div key={item.id} className="flex items-start justify-between gap-3 border-b py-2 last:border-0">
              <div>
                <div className="flex items-center gap-2">
                  <Badge
                    variant={
                      item.classification === "fact" ? "default" : item.classification === "claim" ? "warning" : "secondary"
                    }
                  >
                    {item.classification}
                  </Badge>
                  <span className="text-sm font-medium">{item.title}</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{item.summary}</p>
              </div>
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{age(item.observed_at, now)}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
