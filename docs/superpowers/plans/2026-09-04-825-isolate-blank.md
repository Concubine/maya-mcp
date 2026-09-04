# #825 — isolate captures blank on some agent Mayas

2026-09-04. Redmine: http://localhost:3000/issues/825 (left OPEN — the race is
not explained).

## What the ticket claimed, and what measurement did to it

#825 was spun off #824 with two suspects: the minimized launch, and VP2
drawing an isolate view on a panel whose window was never realized. Both are
refuted.

**Five agent Maya processes on 2026-09-04**, Maya 2027, all launched
`-WindowStyle Minimized` from the repo cwd on 9879 — the ticket's exact
configuration. Probes `evals/isolate_blank_probe_825{,b,c}.py`.

| Claim in the ticket | Measured |
|---|---|
| The minimized launch causes it | 5 of 5 processes drew the isolate view. `isMinimized()` is **False** in every one — `-WindowStyle Minimized` does not leave the window minimized |
| `show()` is queued, not applied | `w.show()` sets `isVisible()` True **synchronously**, in the same command |
| A never-realized window cannot draw an isolate view | In probe 825c the window went back to `hidden=True / visible=False` immediately after `show()` and stayed there through six idle gaps out to 20 s **and through a capture** — and every isolate capture drew 14884 red px anyway |

So `visible=False` is the **normal steady state** of an agent Maya here, not
the anomaly, and the ticket's correlation between it and the blank frames was
coincidental. What is constant in every drawing process is that the main
window has a **native surface** (`windowHandle()` is not None) from launch
onward, even while invisible. That, not visibility, is the plausible
requirement — and it is present here, which is why nothing fails. It is the
thing to measure first if a failing process ever appears again.

A sixth data point, naturalistic: a fresh subagent was given an ordinary
"model a desk lamp, check each part on its own" brief through the MCP, told
nothing about this ticket. Five captures, three of them isolate, all legible.
It independently flagged the "never been shown" note as inconsistent.

## The defect that fell out

`ensure_viewport_realized` says *"this call showed it. That is a visible
change to the screen and the only one a capture makes."* In processes where
`show()` does not stick, that is false in both directions — the window was not
visible before and is not visible after — and it repeats on every capture.
Recorded on the ticket; not changed here, because the `show()` is load-bearing
for #765 on states this machine did not reproduce, and removing it on the
strength of five good processes would be trading a measured protection for an
unmeasured one.

## What was built instead

Not reproducible on demand means the honest move is to make the condition
legible, not to guess at a fix. A blank ISOLATE frame now gets a **control
shot**: the same camera, view-selected switched off, nothing else touched
(`capture._isolate_blank_control`). The warning then reports the answer rather
than listing possibilities:

- control drew → *"the SAME frame drawn without isolate was not [blank] … what
  drew nothing is the isolated view"*, naming both causes it could be
  (everything isolated is hidden, or #825) and what to do instead.
- control also blank → *"there was nothing to draw"* — the scene really is
  empty or unframed.
- control unmeasurable → the old hedge, unchanged. "I did not check" and "I
  checked" must not look alike.

Costs one extra playblast, only on a frame that already came back blank.

## Verification

- `evals/isolate_blank_live.py` — **11/11** live on 9879. Both blank branches
  are reachable on demand (isolate a hidden object with, and without, another
  object in the scene), plus a regression check that the control shot puts
  view-selected back: a second isolate still shows red and **zero blue**.
- Headless suite **3173 / 0 failures / 0 errors**.
- `evals/occlusion_live.py` **13/13**, unchanged.

Note for whoever writes the next gate here: opaque pixel count cannot tell you
whether isolate is still isolating. A non-isolate frame fits both cubes, so
each draws smaller, and the two together covered FEWER pixels than one
isolated cube (11608 vs 15372). Count colour, not coverage.

## Still open

`occlusion_live.py` check 6b still passes on a blank frame by design and names
this ticket. Tighten it to require red unconditionally only once the race is
understood.
