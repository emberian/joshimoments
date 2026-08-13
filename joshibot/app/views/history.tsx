import { useEffect, useState } from "react";

import { Lamp, PageKicker, PageLede, PageTitle } from "@/components/desk";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { loadEvents, loadTrades } from "@/lib/api";
import { age, number, shortAddress } from "@/lib/utils";

export function History({ now }: { now: number }) {
  const [events, setEvents] = useState<{ timestamp: string; severity: string; category: string; message: string }[]>([]);
  const [trades, setTrades] = useState<
    { timestamp: string; mint: string; name: string; reason: string; output_lamports: string; signature: string }[]
  >([]);

  useEffect(() => {
    void loadEvents()
      .then((payload) => setEvents(payload.items))
      .catch(() => setEvents([]));
    void loadTrades()
      .then((payload) => setTrades(payload.items))
      .catch(() => setTrades([]));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <PageKicker>History</PageKicker>
        <PageTitle>Tape</PageTitle>
        <PageLede>Local event journal and trade CSV. Empty trades means no live exit has landed yet.</PageLede>
      </div>
      <Tabs defaultValue="events">
        <TabsList>
          <TabsTrigger value="events">Events</TabsTrigger>
          <TabsTrigger value="trades">Trades</TabsTrigger>
        </TabsList>
        <TabsContent value="events">
          <Card>
            <CardHeader>
              <CardTitle>Event journal</CardTitle>
              <CardDescription>{events.length} recent rows</CardDescription>
            </CardHeader>
            <CardContent className="space-y-0">
              {events.map((event, index) => (
                <div
                  key={`${event.timestamp}-${index}`}
                  className="grid grid-cols-[16px_72px_96px_1fr] items-start gap-3 border-b py-2.5 text-sm last:border-0"
                >
                  <Lamp
                    tone={event.severity === "critical" ? "bad" : event.severity === "warning" ? "warn" : "idle"}
                    className="mt-1.5"
                  />
                  <span className="font-mono text-[10px] text-muted-foreground">{age(event.timestamp, now)}</span>
                  <Badge
                    variant={
                      event.severity === "critical" ? "destructive" : event.severity === "warning" ? "warning" : "outline"
                    }
                  >
                    {event.category}
                  </Badge>
                  <span>{event.message}</span>
                </div>
              ))}
              {!events.length && <p className="py-8 text-center text-sm text-muted-foreground">No events persisted yet.</p>}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="trades">
          <Card>
            <CardHeader>
              <CardTitle>Executed exits</CardTitle>
              <CardDescription>Only rows after a live sell lands</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {trades.map((trade, index) => {
                const lamports = Number(trade.output_lamports);
                const sol = Number.isFinite(lamports) ? lamports / 1_000_000_000 : null;
                return (
                  <div key={`${trade.signature}-${index}`} className="flex justify-between border-b py-2 text-sm last:border-0">
                    <div>
                      <div className="font-medium">
                        {trade.name} · {trade.reason}
                      </div>
                      <div className="font-mono text-[10px] text-muted-foreground">{shortAddress(trade.mint)}</div>
                    </div>
                    <div className="text-right font-mono tnum text-xs">
                      {sol != null ? `${number(sol, 4)} SOL` : `${trade.output_lamports} lamports`}
                      {trade.signature && <div className="text-muted-foreground">{shortAddress(trade.signature)}</div>}
                    </div>
                  </div>
                );
              })}
              {!trades.length && (
                <p className="py-8 text-center text-sm text-muted-foreground">No trades recorded. Dry-run does not write fills.</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
