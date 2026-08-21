# BRIEF — build a lizard

You are an artist with access to a live Autodesk Maya through an MCP tool
namespace. Build me a lizard.

## THE BRIEF

A single lizard creature, game-asset quality, roughly 40 cm nose to tail tip.
Not stylised, not photoreal — readable. Four legs, a long tapering tail,
a distinct head with a jaw that opens, and a neck frill it can flare.

Deliver, in D:\devel\lizard-run\ (create it):

  1. The Maya scene, saved.
  2. A turntable contact sheet of the finished model.
  3. One hero render — lit, textured, something you'd put in a portfolio.
  4. An FBX export, ready to drop into a game engine.
  5. Two poses captured as stills: a neutral idle, and a threat display
     with the jaw open and the frill flared.

## YOUR MAYA

Use ONLY the tools in the mcp__maya9879__* namespace. They are pointed at a
disposable Maya that exists for this job — you can wipe the scene, you can
break things, nothing of value is in it.

If you see any other Maya tool namespace, do not touch it. It is someone
else's live session and destroying it is a real cost.

## HOW TO WORK

You cannot see what you are making unless you ask. Capture the viewport or
render, look at the image, and fix what is actually wrong before adding more
detail. A lizard that is right from one angle and wrong from three is a
common way to fail this.

Judge your own work honestly. If the render looks bad, say so and fix it —
do not hand me something you would not defend.

## CONSTRAINTS

Do not read, search, or open the maya-mcp source repository, its docs, its
tests, or its plans. Everything you need to know about a tool is in that
tool's own description. If a tool's description does not tell you what you
need, that is information — note it and work it out from what you have.

Work from the tools you are given. If something seems impossible with them,
write down what you wanted and why you could not get it, then find another
way or leave it undone. Do not silently substitute a different approach.

## WHEN YOU ARE DONE

Write D:\devel\lizard-run\NOTES.md with:
  - What you built, and how long it took you.
  - What fought you. Anything that took more attempts than it should have.
  - Anything you wanted to do and could not.
  - Anything that surprised you — a tool that did something other than what
    its description led you to expect.

Take the time it takes. Quality over speed.

---

# SETUP ALREADY DONE (2026-08-20, before this session)

Established by an earlier session; do not re-derive it, but DO re-verify the
two checks at the bottom before creating or deleting anything.

- The disposable Maya is **`maya.exe` pid 4032**, launched 12:37, listening on
  **127.0.0.1:9879**. It is fresh — nothing of value in it.
- Two OTHER Mayas are running and must NOT be touched:
  **pid 41512 on port 9877** (the user's live session) and
  **pid 47664 on port 9878**.
- The MCP server `maya9879` is registered at **user scope** with
  `MAYA_MCP_PORT=9879`:
  `uv --directory D:/devel/maya-mcp run maya-mcp`
- The plain `maya` server (no env var) points at **9877, the live session**.
  Do not call anything in the `mcp__maya__*` namespace.
- The bridge does NOT auto-pick a free port: it always tries 9877 and gives up
  if taken. Pid 4032's listener was started by hand in its Script Editor with
  `maya_mcp_plugin.start_server(port=9879)`. If Maya is restarted, that has to
  be redone or the port set before launch.

## VERIFY BEFORE TOUCHING ANYTHING

1. `mcp__maya9879__*` tools are actually present. If they are not, STOP — the
   namespace cannot be added to a conversation after it starts, and the only
   fix is a genuinely new conversation.
2. Make a READ-ONLY call first (e.g. the scene graph) and confirm the scene is
   **empty**. Pid 4032 is a fresh Maya; 9877 and 9878 have real work loaded.
   If real geometry comes back, you are on the wrong Maya — stop and say so.
   Reason this matters: the plugin side definitely reads `MAYA_MCP_PORT`, but
   the client half honouring the same variable is assumed, not proven.
