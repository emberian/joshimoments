"""dregg_watch — personal alerts: a holder tells the bot what to watch, the bot DMs them.

Everything else the wire ships is broadcast; this is the first thing that is THEIRS.
Six subscription kinds (coin / deployer / crew / caller / clean, plus list+unwatch as
the management verbs), stored in this package's OWN sqlite and managed over DM by
verified members. A matcher service tails the three event surfaces the deputies
already ship — the screen's scores JSONL, the archive's callouts table, the feed's
alerts table — and enqueues plain-text DMs into the gate's durable outbox.

The module boundary is deliberate: dregg_gate imports ONE class from here
(commands.WatchCommands) and dispatches two commands to it; everything else runs in a
separate service process (dregg_watch.service) that touches the gate only through the
outbox-INSERT pattern dregg_screen.digest and dregg_feed established.
"""
