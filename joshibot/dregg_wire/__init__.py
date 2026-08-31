"""dregg_wire: the Daily PvP Wire — flagship holder content, composed from the desk's own data.

Three modules, one direction of flow:

    facts.py -> wire.py -> post.py
    (measure)   (render)   (approve + deliver)

`facts` reads the day's score ledger, the callout archive, and (for color only) the
stale wallet layer, and emits one deterministic dict where EVERY number carries its
source and window and every absence is stated as a fact. `wire` turns that dict into
the Telegram text and a fuller markdown artifact — pure templates, no model call in
v0. `post` runs the lifecycle: compose enqueues the full text for the operator's
approval through dregg_gate's approvals outbox; deliver polls the decision and, on
approve, posts to the gated group through the gate bot's outbox.

Nothing in this package posts anywhere without a recorded human approval.
"""
