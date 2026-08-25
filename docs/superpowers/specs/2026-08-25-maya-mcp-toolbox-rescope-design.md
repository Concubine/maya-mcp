# maya-mcp re-scope: a private agent toolbox

**Date:** 2026-08-25 · **Ticket:** #756 · **Status:** approved by the user

## Decision

maya-mcp's identity is a **private agent toolbox**: a reusable capability that lets any
agent of ours author 3D content in a live Maya — modelling, look-dev, rigging, skinning,
blend shapes, animation clips, gated FBX export. It is no longer evaluated through the
Demigol lens. Demigol was the requirements engine that got the toolset built; from here,
*any* real run of a future project plays that role.

Explicitly decided against (for now):

- **Public / open-source release — deferred.** Would demand an install story safe for
  strangers, user-facing docs, API stability promises, an engine-agnostic export lane,
  and de-localising the evals (hardcoded ports, machine-specific fixtures). Revisit only
  from a position of a toolbox hardened by real use.
- **Showcase / portfolio pass — optional, not scheduled.** The exhibits (golem arc,
  drifter fixture) already exist; a README/curation pass is cheap whenever wanted.

## The needs bar

The roadmap (rigging phases 1–6, multi-take FBX) is complete. "Good toolbox" now means
exactly three things:

1. **Tools survive agent-style use** — long sessions, repetition, odd editor states
   (open render views, multiple Mayas, standalone mode).
2. **Exports don't silently lose data.**
3. **The agent's eyes don't lie** — viewport/turntable/render capture is trustworthy,
   because agents correct what they *see*.

No new capabilities are owed. Anything new waits until a real run demands it (YAGNI).

## Ticket dispositions (executed with #756)

**Keep — the live backlog, ranked:**

| Rank | Tickets | Why |
|---|---|---|
| 1 | #721, #729, #731, #730, #732 — one "clip robustness" batch | The edges agents actually hit: IPR wedge with no timeout, fbxmaya reload crash under repetition, clip detection keying on attribute existence, residual rest-pin keys, per-joint warning spam |
| 2 | #714 — procedural textures silently dropped on export | Violates needs-bar (2); bake to file textures or warn with numbers |
| 3 | #670 near-plane clip, #669 thin-limb divisions | Eyes-defects tail; violates needs-bar (3), low priority |

**Hand off — consumer-side, closed here with pointer comments:** #737 (pose delivery
format; the tool-side fact stands — author_clip requires joints), #748 (Unity 8→4
influence truncation; the decisive rebind-at-4 test was never run). Re-file on the
Demigol board if the consumer still wants them; this repo does not push tickets onto
another project's board.

**Park as reference — stay New, no work owed:** #696 (glTF lane; unparks only if a web
consumer appears), #675 (in-Maya physics-sim scoping note; the data-not-simulation
boundary stands), #704 (blown-out preview cells; no mechanism found, revisit only if it
recurs).

**Close — board hygiene:** every Resolved ticket (21: #602 #604 #647 #665 #667 #668
#671 #676 #685 #691 #695 #703 #711 #712 #713 #718 #719 #720 #722 #728 #755), plus
#629 (Feedback; answered by #647's live consumer run) and #743 (In Progress; merged
2ba209d, fixture delivered). Closing approved explicitly by the user 2026-08-25.

End state: ~8 live tickets, all genuinely owed, ranked in #756.

## Testing / verification

This re-scope changes no code. Verification is that the board matches the table above
after execution, and #756 carries the ranking.
