# BRIEF — build the golem

You are an artist with access to a live Autodesk Maya through an MCP tool
namespace. Build me a golem colossus for a game.

The creature itself — what it is, how it's proportioned, how it must move and
read — is specified in `DESIGN.md` beside this file. Read it fully before you
touch Maya. This file is about how to work and what to deliver.

## THE ASK

One articulated golem, game-asset quality, delivered ready for a game engine.
The engine team will make it move with physics — your job is to hand them
everything they need, in whatever form you judge best. That judgment is yours:
the design says what the creature is, not how you should realize it in Maya.

Deliver, in D:\devel\golem-rerun\out\ (create it):

  1. The Maya scene, saved.
  2. An FBX export the engine can ingest.
  3. A turntable contact sheet of the finished golem.
  4. One hero render — lit, textured, portfolio-grade.
  5. The five motion-state poses from DESIGN.md, each captured as a still,
     plus the pose data itself in whatever form your delivery carries poses.
  6. Whatever motion/physics data the engine needs to assemble the creature
     (see "The consumer" in DESIGN.md) — again, form is your call.
  7. NOTES.md and LEDGER.md (see below).

## YOUR MAYA

Use ONLY the tools in the mcp__maya9879__* namespace. They are pointed at a
disposable Maya that exists for this job — you can wipe the scene, you can
break things, nothing of value is in it.

If you see any other Maya tool namespace (mcp__maya__*, or anything else), do
not touch it. It is someone else's live session and destroying it is a real
cost.

### Verify before touching anything

1. mcp__maya9879__* tools are actually present. If they are not, STOP — the
   namespace cannot be added to a conversation after it starts; the only fix
   is a genuinely new conversation.
2. Make a READ-ONLY call first (e.g. the scene graph) and confirm the scene
   is EMPTY. The disposable Maya is fresh (maya.exe pid 7280, listening on
   127.0.0.1:9879). If real geometry comes back, you are on the wrong Maya —
   stop and say so.

## HOW TO WORK

You cannot see what you are making unless you ask. Capture the viewport or
render, look at the image, and fix what is actually wrong before adding more
detail. A golem that is right from one angle and wrong from three is a common
way to fail this.

Judge your own work honestly. If the render looks bad, say so and fix it — do
not hand me something you would not defend.

Build through the tools. If something seems impossible with them, write down
what you wanted and why you could not get it, then find another way or leave
it undone — do not silently substitute a different approach. The
execute-python tool exists: using it to MEASURE something costs nothing;
every use of it to BUILD something is a finding — record it in the ledger
with a reason.

## THE LEDGER

Keep LEDGER.md as you go, one row per build step: what you were doing, which
tool you used, roughly how many calls it took, whether you escaped to
execute-python, and why. Write rows when they happen, not from memory at the
end. This ledger is evidence, not paperwork — the run exists partly to learn
where the toolset fights this brief.

## CONSTRAINTS

Do not read, search, or open the maya-mcp source repository (D:\devel\maya-mcp),
its docs, its tests, its evals, or its plans. Everything you need to know
about a tool is in that tool's own description. If a tool's description does
not tell you what you need, that is information — note it and work it out
from what you have.

Everything you need about the creature is in DESIGN.md. Do not go looking for
other golem material on this machine — if it isn't in this directory, it
isn't yours to see.

## WHEN YOU ARE DONE

Write NOTES.md with:
  - What you built, how you chose to realize it, and why.
  - What fought you. Anything that took more attempts than it should have.
  - Anything you wanted to do and could not.
  - Anything that surprised you — a tool that did something other than what
    its description led you to expect.

Take the time it takes. Quality over speed.
