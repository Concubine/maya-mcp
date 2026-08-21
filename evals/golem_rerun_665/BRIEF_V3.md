# BRIEF v3 — the golem learns to move

You are an artist with access to a live Autodesk Maya through an MCP tool
namespace. The golem exists — v2.1, polished, delivered. Now the engine team
has come back with a new requirement: **they have started importing baked
animation, and they want this creature to arrive already breathing.**

Read `DESIGN_V3.md` beside this file before touching Maya. It carries the
full creature spec plus what is new in v3.

## WHERE YOU START

This is an iteration, not a rebuild-from-nothing. In this directory:

- `out_v21/golem_v21.ma` — the current polished scene. Open it and build on
  it, or rebuild from scratch if your realization needs it: **your call**,
  but say why in NOTES.md.
- `out_v21/` — the delivered FBX, physics manifest, pose data, renders.
- `out/NOTES.md`, `out/LEDGER.md` — the previous builder's honest notes.
  Read them; they paid for their lessons (world-vs-local rotation semantics,
  the mirror double-scale trap, the hero-camera fight).

## THE ASK

The v2.1 delivery, plus **animation in the FBX**. Deliver, in
D:\devel\golem-rerun\out_v3\ (create it):

  1. The Maya scene, saved.
  2. An FBX export the engine can ingest — now carrying **named animation
     takes**, verified from the exported bytes, not the scene.
  3. The animation set from DESIGN_V3.md (idle loop + tracer scan at
     minimum), each also captured as a preview (frames or contact sheet) so
     the motion can be judged by eye.
  4. The physics manifest and pose data, updated if your realization moved
     anything (numbers re-measured, never carried forward on faith).
  5. A turntable contact sheet and one hero render.
  6. NOTES.md and LEDGER.md, same discipline as before: one ledger row per
     build step, escapes recorded with reasons, written as they happen.

## YOUR MAYA

Use ONLY the tools in the mcp__maya9879__* namespace — the disposable Maya.
If you see any other Maya tool namespace, do not touch it. Verify before
touching anything: the tools are present, and a read-only scene-graph call
shows either an empty scene or the golem — nothing else. If unrelated real
work comes back, you are on the wrong Maya: stop and say so.

## HOW TO WORK

Capture or render after each significant change and fix what you actually
see. Judge your own work honestly — especially the motion: a loop that pops
at the seam or an idle that reads as hovering is a failure to fix, not to
ship.

Build through the tools. The execute-python tool is free for MEASUREMENT;
every use of it to BUILD or ANIMATE something is a finding — record it in
the ledger with what you wanted and why the tools could not say it. If a
tool refuses you or a capability does not compose with your realization,
that refusal is valuable: write down exactly what you asked for and what
came back. Do not silently work around it.

## CONSTRAINTS

Do not read, search, or open the maya-mcp source repository
(D:\devel\maya-mcp), its docs, its tests, its evals, or its plans.
Everything you need to know about a tool is in that tool's own description.
Everything you need about the creature and this directory's history is IN
this directory.

## WHEN YOU ARE DONE

NOTES.md with: what you built and how you chose to realize the animation
(and why); what fought you; what you wanted and could not get; what
surprised you. Take the time it takes. Quality over speed.
