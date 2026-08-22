# Multiple Named Takes in One FBX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One skeleton carries N named clips laid end to end on one timeline, and `export_fbx` writes all of them into a single FBX as N named takes — so an animated asset ships one file instead of one file per take (#718).

**Architecture:** The metadata attr `mcp_clip` on the skeleton root becomes a JSON **list** of clip records, each owning a frame range. `author_clip` auto-appends after the last record (never takes a start frame from the caller) and pads every clip's boundary frames so a take can never be contaminated by a neighbour's held curve values — the correctness rule this whole change turns on. `delete_clip` gains an optional `name`. `preview_clip` renders a named clip's absolute frame range while reporting clip-relative times. `export_fbx` bakes the whole span once and emits one `FBXExportSplitAnimationIntoTakes` per clip. Pure layout/record math goes in `clipmath.py` with plain-Python tests; the Maya-touching half goes in `clip.py` against the repo's `FakeCmds` pattern; the byte gate stays in `export.anim_violations` fed by `fbxbytes.anim_facts`, which learns each take's start/stop.

**Tech Stack:** Python 3, `maya.cmds` inside the plugin, `mel` for the FBX exporter, pytest with the repo's fake-`cmds` pattern (`tests/test_clip.py`), `mayapy -m pytest` for the real-Maya battery, `uv run` for everything, unityMCP tools for the consumer gate.

**Spec:** `docs/superpowers/specs/2026-08-22-multi-take-fbx-design.md`. It supersedes decision 1 of `2026-08-20-rigging-p6-clips-design.md` ("one clip at a time"). Read the spec before Task 1; every decision below traces to it.

## Global Constraints

- **Report measured, never echoed (#636).** `duration_s`, `end_frame`, displacements and curve counts are re-read from the scene or the bytes after the change, never echoed from the input.
- **Silence is never an answer.** Every pad, back-fill, replace and refusal names the clips and channels involved, with numbers.
- **A refusal beats a silent drop.** A second fps on one rig refuses. A second SKELETON carrying clips still refuses at export, with the corrected message ("multi-CLIP is supported, multi-RIG is not").
- **Takes are self-contained.** At its own first and last frame, every clip keys EVERY channel any clip on that rig touches; channels it does not mention are keyed at rest. This is the rule the whole design turns on — a violation is invisible in the bytes.
- **Authoring may never change another clip's MOTION.** The only permitted touch is adding rest-value keys on a channel that clip never declared (the back-fill), which *restores* what that clip measured when it was authored.
- **No explicit start frames, ever.** The layout is derived and reported; a caller-supplied start frame would hand the caller collision avoidance.
- **Backwards compatible on disk.** A scene whose `mcp_clip` is a bare object (every scene authored before this change) reads as a one-element list. Nothing migrates on disk; the next write emits the list form. An unparseable value is still reported name-only, never a crash.
- Every task ends with `uv run pytest tests/ --junitxml=<tmp>.xml -q` green. **The pytest summary line is lost to stdout buffering on this machine — read the junit XML**, e.g. `uv run python -c "import xml.etree.ElementTree as E;r=E.parse('<tmp>.xml').getroot();print(r.attrib)"`.
- Baseline suite counts at branch point: **headless 1332 + 1 skip**, **mayapy 154 + 1 skip**. A drop is a regression, not an update.
- Commit per task, message form `feat(#718): <what>` (or `fix(#718):` / `test(#718):` / `docs(#718):`).
- Branch: `multi-take-fbx`, cut from `main`.

---

### Task 1: `clipmath` — the timeline layout math

Pure functions, no Maya: normalizing both metadata shapes, deriving where the next clip goes, the channel union across records, dropping a record by name, and the overlap/uniqueness check the byte gate reuses.

**Files:**
- Modify: `maya_plugin/handlers/clipmath.py` (append after `fractional_frame_times`, before `loop_violations`)
- Test: `tests/test_clipmath.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces, all pure:
  - `GAP_FRAMES = 1`
  - `normalized_records(raw) -> List[Dict[str, Any]]` — `raw` is whatever `json.loads` gave for `mcp_clip` (a list, a bare dict, or `None`); returns records in timeline order, each carrying `name, fps, start_frame, end_frame, duration_s, loop, interpolation, joints, weight_channels, root_position_used`.
  - `next_start_frame(records) -> int`
  - `fps_conflict(records, fps) -> Optional[str]` — the refusal message, or None.
  - `channel_union(records) -> Dict[str, Any]` — `{"joints": [short names], "weight_channels": [aliases], "root_position_used": bool}`
  - `drop_record(records, name) -> Tuple[Optional[Dict], List[Dict]]`
  - `overlap_violations(records) -> List[str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_clipmath.py`:

```python
class TestRecords:
    def _records(self):
        return [
            {"name": "idle", "fps": 30, "start_frame": 0, "end_frame": 60,
             "duration_s": 2.0, "loop": True, "interpolation": "smooth",
             "joints": ["chest"], "weight_channels": ["blink"],
             "root_position_used": False},
            {"name": "walk", "fps": 30, "start_frame": 62, "end_frame": 98,
             "duration_s": 1.2, "loop": True, "interpolation": "linear",
             "joints": ["L_hip"], "weight_channels": [],
             "root_position_used": True},
        ]

    def test_a_bare_object_reads_as_one_record(self):
        """Every scene authored before #718 carries a bare object with no
        frame range: it is clip one, starting at frame 0."""
        out = clipmath.normalized_records(
            {"name": "sway", "fps": 30, "duration_s": 1.5, "loop": False,
             "interpolation": "linear", "joints": ["mid"],
             "weight_channels": [], "root_position_used": False})
        assert len(out) == 1
        assert out[0]["start_frame"] == 0 and out[0]["end_frame"] == 45
        assert out[0]["name"] == "sway"

    def test_a_nameless_value_survives_as_one_record(self):
        """clip_meta reports an unparseable attr as name-only; that must not
        crash the layout math either."""
        out = clipmath.normalized_records({"name": "junk"})
        assert out[0]["name"] == "junk" and out[0]["fps"] == 30
        assert out[0]["start_frame"] == 0 and out[0]["end_frame"] == 0
        assert clipmath.normalized_records(None) == []
        assert clipmath.normalized_records("not json at all") == []

    def test_records_come_back_in_timeline_order(self):
        out = clipmath.normalized_records(list(reversed(self._records())))
        assert [r["name"] for r in out] == ["idle", "walk"]

    def test_next_start_leaves_exactly_one_gap_frame(self):
        assert clipmath.next_start_frame([]) == 0
        # idle ends at 60, frame 61 is the gap, walk starts at 62
        assert clipmath.next_start_frame(self._records()[:1]) == 62
        assert clipmath.next_start_frame(self._records()) == 100

    def test_fps_conflict_names_the_fps_in_use_and_its_clips(self):
        assert clipmath.fps_conflict([], 24) is None
        assert clipmath.fps_conflict(self._records(), 30) is None
        message = clipmath.fps_conflict(self._records(), 24)
        assert "30" in message and "idle" in message and "walk" in message

    def test_channel_union_is_every_channel_any_clip_touches(self):
        union = clipmath.channel_union(self._records())
        assert union["joints"] == ["L_hip", "chest"]
        assert union["weight_channels"] == ["blink"]
        assert union["root_position_used"] is True
        empty = clipmath.channel_union([])
        assert empty == {"joints": [], "weight_channels": [],
                         "root_position_used": False}

    def test_drop_record_returns_the_record_and_the_rest(self):
        dropped, kept = clipmath.drop_record(self._records(), "idle")
        assert dropped["start_frame"] == 0 and dropped["end_frame"] == 60
        assert [r["name"] for r in kept] == ["walk"]
        missing, kept = clipmath.drop_record(self._records(), "nope")
        assert missing is None and len(kept) == 2

    def test_overlaps_and_duplicate_names_are_violations(self):
        assert clipmath.overlap_violations(self._records()) == []
        bad = self._records()
        bad[1]["start_frame"] = 60
        out = clipmath.overlap_violations(bad)
        assert any("overlap" in v and "idle" in v and "walk" in v
                   for v in out)
        dupe = self._records()
        dupe[1]["name"] = "idle"
        assert any("more than one take named 'idle'" in v
                   for v in clipmath.overlap_violations(dupe))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_clipmath.py::TestRecords -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'normalized_records'`.

- [ ] **Step 3: Write the implementation**

Append to `maya_plugin/handlers/clipmath.py`, after `fractional_frame_times`:

```python
# One unowned frame between clips. That frame is where the interpolation
# from one clip's last pose to the next clip's first pose lives, and no
# take's range includes it (#718 design). Zero would make two takes share
# a frame; more would only pad the file.
GAP_FRAMES = 1


def _record(raw, start_frame):
    """One clip record, with its frame range filled in when the stored
    shape predates #718 (a bare object, no range: it is clip one)."""
    fps = raw.get("fps") or 30
    duration_s = float(raw.get("duration_s") or 0.0)
    start = int(raw.get("start_frame", start_frame))
    end = int(raw.get("end_frame", start + round(duration_s * fps)))
    return {"name": raw.get("name"), "fps": int(fps),
            "start_frame": start, "end_frame": end,
            "duration_s": duration_s,
            "loop": bool(raw.get("loop", False)),
            "interpolation": raw.get("interpolation", "linear"),
            "joints": list(raw.get("joints") or []),
            "weight_channels": list(raw.get("weight_channels") or []),
            "root_position_used": bool(raw.get("root_position_used", False))}


def normalized_records(raw):
    """Clip records in timeline order, from either stored shape.

    A bare object is every scene authored before #718: read as a
    one-element list whose record starts at frame 0 (the design's
    compatibility rule - nothing migrates on disk). Anything else that is
    not a list or dict carries no clips.
    """
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw:
        if isinstance(entry, dict):
            out.append(_record(entry, 0))
    out.sort(key=lambda r: r["start_frame"])
    return out


def next_start_frame(records) -> int:
    """Where a new clip goes: after the last clip's end, past the gap
    frame. The first clip on a rig starts at 0."""
    if not records:
        return 0
    return max(r["end_frame"] for r in records) + GAP_FRAMES + 1


def fps_conflict(records, fps) -> Optional[str]:
    """Why this fps cannot join these clips, or None.

    Not a compromise: a take IS a frame range on one timeline, so one file
    cannot carry two frame rates."""
    others = sorted({r["fps"] for r in records})
    if not others or others == [fps]:
        return None
    return ("this rig's clips are %s fps (%s); a clip at %s fps cannot join "
            "them - one file is one timeline, so one rig is one frame rate"
            % (", ".join(str(f) for f in others),
               ", ".join(repr(r["name"]) for r in records), fps))


def channel_union(records):
    """Every channel ANY clip on the rig touches - the set each clip must
    key at its own boundary frames to stay self-contained."""
    joints, weights = set(), set()
    root = False
    for r in records:
        joints.update(r["joints"])
        weights.update(r["weight_channels"])
        root = root or r["root_position_used"]
    return {"joints": sorted(joints), "weight_channels": sorted(weights),
            "root_position_used": root}


def drop_record(records, name):
    """(the record named `name` or None, the records without it)."""
    found = None
    kept = []
    for r in records:
        if found is None and r["name"] == name:
            found = r
        else:
            kept.append(r)
    return found, kept


def overlap_violations(records) -> List[str]:
    """Ranges that share a frame, and names that repeat. A take is a range
    over one timeline: two takes claiming one frame are two readings of the
    same keys, and a consumer looks a take up BY NAME."""
    out = []
    ordered = sorted(records, key=lambda r: r["start_frame"])
    for prev, cur in zip(ordered, ordered[1:]):
        if cur["start_frame"] <= prev["end_frame"]:
            out.append(
                "takes %r (%d-%d) and %r (%d-%d) overlap"
                % (prev["name"], prev["start_frame"], prev["end_frame"],
                   cur["name"], cur["start_frame"], cur["end_frame"]))
    seen = set()
    for r in ordered:
        if r["name"] in seen:
            out.append("more than one take named %r" % r["name"])
        seen.add(r["name"])
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_clipmath.py -q`
Expected: PASS, every pre-existing test in the file still green.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/clipmath.py tests/test_clipmath.py && git commit -m "feat(#718): clipmath learns the multi-clip timeline layout"
```

---

### Task 2: `clip_meta` returns a LIST, and every consumer reads it

Pure plumbing, zero behaviour change: with one clip per rig everything still behaves exactly as today. This task exists so Tasks 3-8 never have to touch two shapes at once.

**Files:**
- Modify: `maya_plugin/handlers/clip.py` (`clip_meta` ~line 53, `guard_static_pose` ~line 82, `delete_clip` ~line 364, `preview_clip` ~line 433)
- Modify: `maya_plugin/handlers/export.py` (`_scene_clip` ~line 325, its caller ~line 543)
- Test: `tests/test_clip.py`, `tests/test_export_fbx.py`

**Interfaces:**
- Consumes: `clipmath.normalized_records` (Task 1).
- Produces: `clip.clip_meta(cmds, root_long) -> List[Dict]` — **empty list** when the rig carries no clip metadata (never `None`). Records are `clipmath` records. Every other module reads clips through this.

- [ ] **Step 1: Write the failing test**

In `tests/test_clip.py`, add to the end of `class TestAuthor`:

```python
    def test_clip_meta_reads_both_stored_shapes(self, fake):
        """#718: the attr is a LIST now, and a bare object (every scene
        authored before this change) reads as one record at frame 0."""
        _author(fake, name="idle")
        records = clip.clip_meta(fake, "|root")
        assert [r["name"] for r in records] == ["idle"]
        assert records[0]["start_frame"] == 0
        assert records[0]["end_frame"] == 30
        # the legacy shape, written by hand the way an old scene holds it
        fake.string_attrs["|root"]["mcp_clip"] = json.dumps(
            {"name": "old", "fps": 30, "duration_s": 1.0, "loop": False,
             "interpolation": "linear", "joints": ["mid"],
             "weight_channels": [], "root_position_used": False})
        records = clip.clip_meta(fake, "|root")
        assert [r["name"] for r in records] == ["old"]
        assert records[0]["start_frame"] == 0 and records[0]["end_frame"] == 30
        # unparseable is still name-only, still never a crash
        fake.string_attrs["|root"]["mcp_clip"] = "{not json"
        assert [r["name"] for r in clip.clip_meta(fake, "|root")] == ["{not json"]
        # no attr at all is an empty list, not None
        fake.string_attrs["|root"].pop("mcp_clip")
        assert clip.clip_meta(fake, "|root") == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_clip.py::TestAuthor::test_clip_meta_reads_both_stored_shapes -q`
Expected: FAIL — `clip_meta` returns a dict, so `[r["name"] for r in records]` yields the dict's keys.

- [ ] **Step 3: Change `clip_meta` and its four consumers**

In `maya_plugin/handlers/clip.py`, replace `clip_meta` entirely:

```python
def clip_meta(cmds, root_long: str) -> List[Dict[str, Any]]:
    """The clips this tool authored on `root_long`, in timeline order.

    An empty list when the rig carries none. Reads BOTH stored shapes: the
    #718 list, and the bare object every scene authored before it (read as
    one record starting at frame 0 - nothing migrates on disk). A value
    that fails to parse is reported as name only rather than crashing a
    guard.
    """
    if not cmds.attributeQuery(CLIP_ATTR, node=root_long, exists=True):
        return []
    raw = cmds.getAttr("%s.%s" % (root_long, CLIP_ATTR))
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return clipmath.normalized_records(
            {"name": str(raw)} if raw else None)
    return clipmath.normalized_records(parsed)
```

In `guard_static_pose`, replace the two label lines:

```python
    records = clip_meta(cmds, root_long)
    label = ((" (clip%s %s)" % ("s" if len(records) > 1 else "",
                                ", ".join(repr(r["name"]) for r in records)))
             if records else "")
```

In `delete_clip`, replace `meta = clip_meta(cmds, root_long)` with `records = clip_meta(cmds, root_long)` and every later use:
- `if not driven and meta is None:` → `if not driven and not records:`
- `if meta is None and driven:` → `if not records and driven:`
- the return's `"clip": meta.get("name") if meta else None` → `"clip": records[0]["name"] if records else None`

In `preview_clip`, replace the metadata lookup block:

```python
    records = clip_meta(cmds, root_long)
    if not records or not records[0].get("name"):
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; preview_clip renders it")
    meta = records[0]
```

and leave the rest of `preview_clip` untouched (Task 6 rewrites its frame selection).

In `maya_plugin/handlers/export.py`, `_scene_clip`, replace the last two lines:

```python
    records = clip_mod.clip_meta(cmds, roots[0])
    if not records:
        return None
    meta = dict(records[0])
    meta["root"] = roots[0].split("|")[-1]
    return meta
```

- [ ] **Step 4: Run the suite to verify nothing else moved**

Run: `uv run pytest tests/ --junitxml=%TEMP%\t2.xml -q`
Expected: 1333 passed + 1 skipped (the baseline 1332 plus this task's new test), 0 failures.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/clip.py maya_plugin/handlers/export.py tests/test_clip.py && git commit -m "feat(#718): clip_meta reads both stored shapes and returns a list"
```

---

### Task 3: `author_clip` appends instead of replacing

Layout, fps refusal, the list metadata, the re-author-at-the-tail rule, the reported range, the full-span playback range, and the other-rig warning. Padding is Task 4 — this task deliberately ships the contaminated version, and Task 4's tests are what prove the rule.

**Files:**
- Modify: `maya_plugin/handlers/clip.py` (`author_clip`, ~lines 158-350)
- Test: `tests/test_clip.py`

**Interfaces:**
- Consumes: `clipmath.next_start_frame`, `clipmath.fps_conflict`, `clipmath.drop_record` (Task 1); `clip.clip_meta` (Task 2).
- Produces: `author_clip` result gains `start_frame: int`, `end_frame: int`, `clips: List[str]` (every clip on the rig, in timeline order). `replaced` keeps its meaning: the name this call re-authored, or None. Module-level helper `_clips_elsewhere(cmds, root_long) -> List[str]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_clip.py`, REPLACE `TestAuthor::test_replacing_warns_and_deletes_the_old_curves` (it asserts the withdrawn one-clip-at-a-time contract) with:

```python
    def test_a_second_clip_appends_after_the_first(self, fake):
        first = _author(fake, name="idle")
        assert (first["start_frame"], first["end_frame"]) == (0, 30)
        assert first["clips"] == ["idle"] and first["replaced"] is None
        second = _author(fake, name="walk")
        # frame 31 is the gap; walk owns 32..62
        assert (second["start_frame"], second["end_frame"]) == (32, 62)
        assert second["clips"] == ["idle", "walk"]
        assert second["replaced"] is None
        # idle's keys are untouched
        assert sorted(fake.keys["|root|mid.rotateZ"]) == [0.0, 30.0, 32.0, 62.0]
        # the playback range spans everything
        assert fake.playback["maxTime"] == 62

    def test_re_authoring_a_name_moves_it_to_the_tail(self, fake):
        _author(fake, name="idle")
        _author(fake, name="walk")
        again = _author(fake, name="idle")
        assert again["replaced"] == "idle"
        assert (again["start_frame"], again["end_frame"]) == (64, 94)
        assert again["clips"] == ["walk", "idle"]
        assert any("vacated" in w and "0-30" in w and "64-94" in w
                   for w in again["warnings"]), again["warnings"]
        # the vacated range holds no keys any more, walk's are untouched
        times = sorted(fake.keys["|root|mid.rotateZ"])
        assert 0.0 not in times and 30.0 not in times
        assert 32.0 in times and 62.0 in times

    def test_a_second_fps_refuses_and_names_the_one_in_use(self, fake):
        _author(fake, name="idle", fps=30)
        with pytest.raises(HandlerError, match="one rig is one frame rate"):
            _author(fake, name="walk", fps=24)
        # the refusal cost nothing: no checkpoint beyond the first author
        assert fake.checkpoints == ["author_clip"]

    def test_a_clip_on_another_rig_warns_because_export_will_refuse(self, fake):
        fake.string_attrs["|other_root"] = {"mcp_clip": "[]"}
        fake.joints.append("|other_root")
        out = _author(fake, name="idle")
        assert any("other_root" in w and "export_fbx" in w
                   for w in out["warnings"]), out["warnings"]
```

`FakeCmds` needs `cutKey` for the re-author path. Add it beside `keyframe` in `tests/test_clip.py`:

```python
    def cutKey(self, plug, time=None, clear=False, **kw):
        keys = self.keys.get(plug)
        if not keys:
            return 0
        lo, hi = time
        doomed = [t for t in keys if lo <= t <= hi]
        for t in doomed:
            del keys[t]
        if not keys:
            curve = self.curves.pop(plug, None)
            if curve:
                self.deleted.append(curve)
            self.keys.pop(plug, None)
        return len(doomed)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_clip.py::TestAuthor -q`
Expected: FAIL — `KeyError: 'start_frame'` on the first, and the second clip's keys landing at 0..30 on top of the first.

- [ ] **Step 3: Rework `author_clip`**

In `maya_plugin/handlers/clip.py`, add the helper above `author_clip`:

```python
def _clips_elsewhere(cmds, root_long: str) -> List[str]:
    """Short names of OTHER skeleton roots carrying clips. export_fbx
    refuses such a scene (a take is a frame range over the whole file, so a
    multi-rig file needs a timeline policy of its own) - and that ceiling
    should be discovered while authoring, not at write time (#718)."""
    return [_short(j) for j in cmds.ls(type="joint", long=True) or []
            if j != root_long
            and cmds.attributeQuery(CLIP_ATTR, node=j, exists=True)]
```

Replace the block from `meta = clip_meta(cmds, root_long)` down to (and including) the `cmds.playbackOptions(...)` call with:

```python
    records = clip_meta(cmds, root_long)
    conflict = clipmath.fps_conflict(records, fps)
    if conflict:
        raise HandlerError(
            conflict,
            hint="delete_clip the clips at the other rate, or author this "
                 "one at theirs")

    weight_plugs = ["%s.%s" % (alias_map[a], a) for a in alias_map
                    if not isinstance(alias_map[a], HandlerError)]
    existing = _anim_curves(cmds, _joint_plugs(joints) + weight_plugs)
    if existing and not records:
        raise HandlerError(
            "this skeleton carries %d hand-authored animation curve "
            "channel(s) this tool did not author (e.g. %s)"
            % (len(existing), sorted(existing)[0]),
            hint="replacing hand-authored animation silently would destroy "
                 "work; delete_clip removes it if that is intended")

    warnings: List[str] = []
    fractional = clipmath.fractional_frame_times(
        [k["time_s"] for k in resolved_keys], fps)
    if fractional:
        warnings.append(
            "key time(s) %s land between frames at %d fps - the baked "
            "export samples integer frames, so these keys are between "
            "samples" % (", ".join("%g" % t for t in fractional), fps))
    if not meshes:
        warnings.append(
            "this skeleton moves no mesh (no skinned bind, no mesh parented "
            "under its joints) - the clip moves bare joints only; the "
            "displacement below is measured against nothing")
    elsewhere = _clips_elsewhere(cmds, root_long)
    if elsewhere:
        warnings.append(
            "another skeleton carries clips (%s) - export_fbx REFUSES a "
            "scene where two rigs carry clips, because a take is a frame "
            "range over the whole file; delete_clip the rig not being "
            "exported" % ", ".join(elsewhere))

    session.auto_checkpoint("author_clip")

    # Re-authoring a name RE-APPENDS it at the tail (#718 decision 4): its
    # old range is cut, and no other clip's motion moves. Take ORDER in the
    # file changes; each take is still independently named, which is all a
    # consumer reads.
    replaced, kept = clipmath.drop_record(records, name)
    if replaced is not None:
        for plug in sorted(set(_joint_plugs(joints) + weight_plugs)):
            cmds.cutKey(plug, time=(replaced["start_frame"],
                                    replaced["end_frame"]), clear=True)

    start_frame = clipmath.next_start_frame(kept)

    prev_unit = cmds.currentUnit(query=True, time=True)
    unit = clipmath.FPS_UNITS[fps]
    if prev_unit != unit:
        cmds.currentUnit(time=unit)
        warnings.append("scene time unit changed %r -> %r so a frame is "
                        "1/%d s" % (prev_unit, unit, fps))

    keyed: List[tuple] = []   # (node, attr) pairs, for tangents
    for key in resolved_keys:
        frame = start_frame + key["time_s"] * fps
        for joint, triple in key["rotations"].items():
            for attr, value in zip(ROTATE_ATTRS, triple):
                cmds.setKeyframe(joint, attribute=attr, time=frame,
                                 value=units.degrees_to_ui(cmds, value))
                keyed.append((joint, attr))
        if key["root_position"] is not None:
            cmds.xform(root_long, worldSpace=True,
                       translation=key["root_position"])
            local = [float(v) for v in cmds.xform(
                root_long, query=True, translation=True)]
            for attr, value in zip(TRANSLATE_ATTRS, local):
                cmds.setKeyframe(root_long, attribute=attr, time=frame,
                                 value=value)
                keyed.append((root_long, attr))
        for alias, value in key["blend_weights"].items():
            cmds.setKeyframe(alias_map[alias], attribute=alias, time=frame,
                             value=value)
            keyed.append((alias_map[alias], alias))

    # MEASURED end frame (#636): the latest key at or after this clip's
    # start, re-read from the curves. Nothing above start_frame can belong
    # to another clip - this clip is always appended at the tail, and a
    # re-author cut its old range first.
    end_frame = start_frame
    for node, attr in set(keyed):
        times = cmds.keyframe("%s.%s" % (node, attr), query=True) or []
        later = [t for t in times if t >= start_frame]
        if later:
            end_frame = max(end_frame, max(later))
    end_frame = int(round(end_frame))
    duration_s = (end_frame - start_frame) / float(fps)
    frames = end_frame - start_frame + 1
    if replaced is not None:
        warnings.append(
            "re-authored clip %r: vacated frames %d-%d and re-appended it "
            "at %d-%d - no other clip's motion changed"
            % (name, replaced["start_frame"], replaced["end_frame"],
               start_frame, end_frame))

    tangent = INTERPOLATIONS[interpolation]
    for node, attr in sorted(set(keyed)):
        cmds.keyTangent(node, attribute=attr, edit=True,
                        inTangentType=tangent, outTangentType=tangent)

    new_record = {
        "name": name, "fps": fps, "start_frame": start_frame,
        "end_frame": end_frame, "duration_s": duration_s, "loop": loop,
        "interpolation": interpolation,
        "joints": sorted({_short(j) for key in resolved_keys
                          for j in key["rotations"]}),
        "weight_channels": weight_channels,
        "root_position_used": any(k["root_position"] is not None
                                  for k in resolved_keys),
    }
    all_records = kept + [new_record]
    span_end = max(r["end_frame"] for r in all_records)
    # The playback range is the FULL span, so opening the .ma and scrubbing
    # shows every clip - not just the one authored last.
    cmds.playbackOptions(edit=True, minTime=0, maxTime=span_end,
                         animationStartTime=0, animationEndTime=span_end)
```

Then, in the per-key measurement block below it, drive time from this clip's own start rather than 0 — replace the four lines that set up baselines and the loop's `currentTime`:

```python
    cmds.currentTime(start_frame)
    for mesh in meshes:
        baselines[mesh] = _points(mesh)
    for key in resolved_keys:
        cmds.currentTime(start_frame + key["time_s"] * fps)
```

Replace the metadata write with the list form:

```python
    if not cmds.attributeQuery(CLIP_ATTR, node=root_long, exists=True):
        cmds.addAttr(root_long, longName=CLIP_ATTR, dataType="string")
    cmds.setAttr("%s.%s" % (root_long, CLIP_ATTR), json.dumps(all_records),
                 type="string")
```

And add three fields to the return dict, beside `replaced`:

```python
        "start_frame": start_frame,
        "end_frame": end_frame,
        "clips": [r["name"] for r in all_records],
        "replaced": name if replaced is not None else None,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_clip.py -q`
Expected: PASS. `test_keys_land_measured_and_metadata_written` needs one edit — `meta = json.loads(...)` now parses a list, so change it to `meta = json.loads(fake.string_attrs["|root"]["mcp_clip"])[0]`.

Then: `uv run pytest tests/ --junitxml=%TEMP%\t3.xml -q`
Expected: no failures. `tests/test_export_fbx.py` and `tests/test_rigging.py` must be untouched.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/clip.py tests/test_clip.py && git commit -m "feat(#718): author_clip appends a named clip after the last one"
```

---

### Task 4: takes are self-contained — boundary padding and back-fill

The correctness core. All clips share ONE curve per channel, so a joint keyed in `idle` and never mentioned in `walk` holds `idle`'s last value throughout `walk` — and nothing in the bytes looks wrong. Contamination runs backwards too: a curve holds its first key's value backwards in time, so a channel a LATER clip introduces silently changes an EARLIER clip that was already judged.

**Files:**
- Modify: `maya_plugin/handlers/clip.py` (`author_clip`; new module helpers `REST_ATTR`, `_rest_key`, `_rest_map`, `_write_rest`, `_capture_rest`, `_rest_value`)
- Test: `tests/test_clip.py`

**Interfaces:**
- Consumes: `clipmath.channel_union` (Task 1), everything Task 3 produced.
- Produces: `author_clip` result gains `padded_channels: List[str]` (channels this clip pinned at rest at its own boundaries) and `back_filled: Dict[str, List[str]]` — `{"clips": [names], "channels": [names]}`. A new string attr `mcp_clip_rest` on the root holds `{"<shortNode>.<attr>": value}`.

**Why a rest record at all:** the rest value of a channel is only readable while that channel is still curve-free. Once a clip keys it, `getAttr` returns the curve's value at the current time. So the value is captured the moment the channel becomes driven, and stored. Weight channels are recorded as `0.0` by rule (weights-all-zero IS the reset, the phase-5 rule), never captured.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_clip.py`, after `class TestAuthor`:

```python
class TestSelfContainedTakes:
    """#718's correctness rule: at its own first and last frame, every clip
    keys EVERY channel any clip on the rig touches, at rest for the ones it
    does not mention. Both contamination directions are under test."""

    def _idle(self):
        return [{"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}]

    def _walk(self):
        return [{"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"tip": [0, 0, 20]}}]

    def test_a_clip_pins_the_channels_it_does_not_mention(self, fake):
        _author(fake, name="idle", keys=self._idle())
        out = _author(fake, name="walk", keys=self._walk())
        assert out["padded_channels"] == ["mid"]
        # mid is keyed at BOTH of walk's boundary frames, at rest (0.0)
        keys = fake.keys["|root|mid.rotateZ"]
        assert keys[32.0] == 0.0 and keys[62.0] == 0.0

    def test_a_new_channel_back_fills_rest_at_every_earlier_boundary(self, fake):
        _author(fake, name="idle", keys=self._idle())
        out = _author(fake, name="walk", keys=self._walk())
        assert out["back_filled"] == {"clips": ["idle"], "channels": ["tip"]}
        # tip is pinned at rest across idle's whole range: idle measures
        # exactly what it measured before walk existed
        keys = fake.keys["|root|mid|tip.rotateZ"]
        assert keys[0.0] == 0.0 and keys[30.0] == 0.0

    def test_weight_channels_pin_at_zero_and_the_root_at_its_rest(self, fake):
        _author(fake, name="blinky", keys=[
            {"time_s": 0.0, "blend_weights": {"blink": 0.0},
             "root_position": [0.0, 1.0, 0.0]},
            {"time_s": 1.0, "blend_weights": {"blink": 1.0},
             "root_position": [0.0, 1.4, 0.0]}])
        _author(fake, name="still", keys=self._idle())
        assert fake.keys["body_shapes.blink"][32.0] == 0.0
        assert fake.keys["body_shapes.blink"][62.0] == 0.0
        # the root's rest translate is the bind position, captured before
        # the first clip keyed it
        assert fake.keys["|root.translateY"][32.0] == pytest.approx(1.0)

    def test_a_clip_that_mentions_a_channel_is_never_padded_over_it(self, fake):
        _author(fake, name="idle", keys=self._idle())
        out = _author(fake, name="more", keys=self._idle())
        assert out["padded_channels"] == []
        assert out["back_filled"] == {"clips": [], "channels": []}
        # the second clip's own motion survives at its own frames
        assert fake.keys["|root|mid.rotateZ"][62.0] == pytest.approx(45.0)

    def test_a_vanished_joint_warns_instead_of_crashing(self, fake):
        _author(fake, name="idle", keys=self._walk())      # keys 'tip'
        fake.joints.remove("|root|mid|tip")
        # renaming/deleting a keyed joint out of tool is not this tool's
        # problem to fix, but it must be SAID
        out = _author(fake, name="walk", keys=self._idle())
        assert any("tip" in w and "not under this root any more" in w
                   for w in out["warnings"]), out["warnings"]
        assert out["padded_channels"] == []

    def test_a_scene_with_no_rest_record_infers_it_and_says_so(self, fake):
        """The compatibility case: a clip authored before #718 left curves
        but no rest record, so the rest value is inferred from the earliest
        keyed value - WARNED, never silent."""
        _author(fake, name="old", keys=self._idle())
        fake.string_attrs["|root"].pop("mcp_clip_rest")
        out = _author(fake, name="new", keys=self._walk())
        assert any("no rest value was recorded" in w and "mid.rotateZ" in w
                   for w in out["warnings"]), out["warnings"]
        assert fake.keys["|root|mid.rotateZ"][32.0] == pytest.approx(0.0)
```

`FakeCmds.getAttr` must accept the `time` keyword the inference path uses — replace its signature and add the branch:

```python
    def getAttr(self, key, time=None):
        if key.endswith(".mcp_clip") or key.endswith(".mcp_clip_rest"):
            node, attr = key.rsplit(".", 1)
            return self.string_attrs[node][attr]
        if time is not None:
            return self.keys.get(key, {}).get(float(time), 0.0)
        return self.attrs.get(key, 0.0)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_clip.py::TestSelfContainedTakes -q`
Expected: FAIL with `KeyError: 'padded_channels'`, and `keys[32.0]` missing entirely.

- [ ] **Step 3: Implement rest capture and padding**

In `maya_plugin/handlers/clip.py`, beside `CLIP_ATTR`:

```python
REST_ATTR = "mcp_clip_rest"
```

Add these helpers above `author_clip`:

```python
def _rest_key(plug: str) -> str:
    """The rest record's key for a plug: short node name plus attribute.
    Long names carry the DAG path, which a reparent would invalidate."""
    node, attr = plug.rsplit(".", 1)
    return "%s.%s" % (_short(node), attr)


def _rest_map(cmds, root_long: str) -> Dict[str, float]:
    if not cmds.attributeQuery(REST_ATTR, node=root_long, exists=True):
        return {}
    try:
        value = json.loads(cmds.getAttr("%s.%s" % (root_long, REST_ATTR)))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_rest(cmds, root_long: str, rest: Dict[str, float]) -> None:
    if not cmds.attributeQuery(REST_ATTR, node=root_long, exists=True):
        cmds.addAttr(root_long, longName=REST_ATTR, dataType="string")
    cmds.setAttr("%s.%s" % (root_long, REST_ATTR), json.dumps(rest),
                 type="string")


def _capture_rest(cmds, plug: str, rest: Dict[str, float]) -> None:
    """Record a channel's rest value the moment it becomes curve-driven.

    Read it later and a curve answers instead of the rest pose - which is
    why this is captured here, before the keying, and not derived on
    demand. A channel already driven (and already recorded) is left alone.
    """
    key = _rest_key(plug)
    if key in rest:
        return
    if cmds.listConnections(plug, source=True, destination=False,
                            type="animCurve"):
        return
    rest[key] = float(cmds.getAttr(plug))


def _rest_value(cmds, plug: str, rest: Dict[str, float],
                warnings: List[str]) -> float:
    """The value to pin a channel at outside the clips that declare it.

    Recorded at first touch (above). A scene authored before #718 has no
    record, so the value is inferred from the existing clip's FIRST key -
    for a self-contained clip that key IS its rest pose - and the
    inference is WARNED, never silent.
    """
    key = _rest_key(plug)
    if key in rest:
        return float(rest[key])
    times = cmds.keyframe(plug, query=True) or []
    if times:
        value = float(cmds.getAttr(plug, time=times[0]))
        warnings.append(
            "no rest value was recorded for %s (this scene predates the "
            "multi-clip metadata) - pinned at %g, its earliest keyed value"
            % (key, value))
        rest[key] = value
        return value
    value = float(cmds.getAttr(plug))
    rest[key] = value
    return value
```

In `author_clip`, immediately after `session.auto_checkpoint("author_clip")` and BEFORE the re-author cut, capture rest for every channel this call introduces:

```python
    by_short: Dict[str, str] = {}
    for j in joints:
        by_short.setdefault(_short(j), j)

    def _rot_plugs(short: str) -> List[str]:
        long_name = by_short.get(short)
        if long_name is None:
            return []
        return ["%s.%s" % (long_name, a) for a in ROTATE_ATTRS]

    root_translate_plugs = ["%s.%s" % (root_long, a) for a in TRANSLATE_ATTRS]
    mine = {
        "joints": sorted({_short(j) for key in resolved_keys
                          for j in key["rotations"]}),
        "weight_channels": list(weight_channels),
        "root_position_used": any(k["root_position"] is not None
                                  for k in resolved_keys),
    }
    rest = _rest_map(cmds, root_long)
    for short in mine["joints"]:
        for plug in _rot_plugs(short):
            _capture_rest(cmds, plug, rest)
    if mine["root_position_used"]:
        for plug in root_translate_plugs:
            _capture_rest(cmds, plug, rest)
    for alias in mine["weight_channels"]:
        # By rule, not by capture: weights-all-zero IS the reset (phase 5).
        rest.setdefault(_rest_key("%s.%s" % (alias_map[alias], alias)), 0.0)
```

Then, after the tangent pass and before `new_record` is built, pad and back-fill:

```python
    # --- the self-contained rule (#718) --------------------------------
    # All clips share ONE curve per channel, so a channel this clip never
    # mentions would hold whatever a neighbour left on it - forwards from
    # the previous clip's last key, and BACKWARDS from a later clip's
    # first key. Both are pinned here, at rest, and both are reported.
    theirs = clipmath.channel_union(kept)
    padded_channels: List[str] = []
    back_filled_channels: List[str] = []

    def _pin(plug: str, frames: List[int]) -> None:
        node, attr = plug.rsplit(".", 1)
        value = _rest_value(cmds, plug, rest, warnings)
        for frame in frames:
            cmds.setKeyframe(node, attribute=attr, time=frame, value=value)
        cmds.keyTangent(node, attribute=attr, edit=True,
                        inTangentType=tangent, outTangentType=tangent)

    mine_frames = [start_frame, end_frame]
    for short in theirs["joints"]:
        if short in mine["joints"]:
            continue
        plugs = _rot_plugs(short)
        if not plugs:
            warnings.append(
                "a clip declares joint %r, which is not under this root any "
                "more - it cannot be pinned at rest, so takes that do not "
                "declare it may inherit a neighbour's value" % short)
            continue
        for plug in plugs:
            _pin(plug, mine_frames)
        padded_channels.append(short)
    for alias in theirs["weight_channels"]:
        if alias in mine["weight_channels"]:
            continue
        node = alias_map.get(alias)
        if node is None or isinstance(node, HandlerError):
            warnings.append(
                "a clip declares weight channel %r, which no mesh bound to "
                "this skeleton carries any more - it cannot be pinned at "
                "rest" % alias)
            continue
        _pin("%s.%s" % (node, alias), mine_frames)
        padded_channels.append(alias)
    if theirs["root_position_used"] and not mine["root_position_used"]:
        for plug in root_translate_plugs:
            _pin(plug, mine_frames)
        padded_channels.append("root_position")

    # BACKWARDS contamination: a curve holds its FIRST key's value
    # backwards in time, so a channel this clip introduces would rewrite
    # every earlier clip's pose for it. Pinning at rest across their
    # ranges RESTORES what each of them measured when it was authored.
    their_frames = [f for r in kept
                    for f in (r["start_frame"], r["end_frame"])]
    if their_frames:
        for short in mine["joints"]:
            if short in theirs["joints"]:
                continue
            for plug in _rot_plugs(short):
                _pin(plug, their_frames)
            back_filled_channels.append(short)
        for alias in mine["weight_channels"]:
            if alias in theirs["weight_channels"]:
                continue
            _pin("%s.%s" % (alias_map[alias], alias), their_frames)
            back_filled_channels.append(alias)
        if mine["root_position_used"] and not theirs["root_position_used"]:
            for plug in root_translate_plugs:
                _pin(plug, their_frames)
            back_filled_channels.append("root_position")
    back_filled = {
        "clips": [r["name"] for r in kept] if back_filled_channels else [],
        "channels": back_filled_channels,
    }
    if back_filled_channels:
        warnings.append(
            "pinned %d channel(s) (%s) at rest across %s so their motion is "
            "unchanged by this clip"
            % (len(back_filled_channels), ", ".join(back_filled_channels),
               ", ".join(back_filled["clips"])))
    _write_rest(cmds, root_long, rest)
```

Add the two fields to the return dict beside `clips`:

```python
        "padded_channels": padded_channels,
        "back_filled": back_filled,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_clip.py -q`
Expected: PASS, including `TestSelfContainedTakes`.

Then: `uv run pytest tests/ --junitxml=%TEMP%\t4.xml -q`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/clip.py tests/test_clip.py && git commit -m "feat(#718): every take keys every channel the rig touches, at rest"
```

---

### Task 5: `delete_clip` takes an optional `name`

**Files:**
- Modify: `maya_plugin/handlers/clip.py` (`delete_clip`)
- Test: `tests/test_clip.py` (`class TestDelete`)

**Interfaces:**
- Consumes: `clip.clip_meta` (Task 2), `clipmath.drop_record` (Task 1).
- Produces: `delete_clip({"root": ..., "name": Optional[str]})`; result gains `clips: List[str]` (what is left, in timeline order). Without `name`, today's behaviour is unchanged for existing callers.

- [ ] **Step 1: Write the failing tests**

Add to `class TestDelete` in `tests/test_clip.py`:

```python
    def test_a_named_delete_removes_one_clip_and_leaves_the_others(self, fake):
        _author(fake, name="idle")
        _author(fake, name="walk")
        out = clip.delete_clip({"root": "root", "name": "idle"})
        assert out["clip"] == "idle" and out["clips"] == ["walk"]
        assert out["deleted_curves"] >= 0
        times = sorted(fake.keys["|root|mid.rotateZ"])
        assert 0.0 not in times and 30.0 not in times   # idle's range
        assert 32.0 in times and 62.0 in times          # walk's, untouched
        meta = json.loads(fake.string_attrs["|root"]["mcp_clip"])
        assert [r["name"] for r in meta] == ["walk"]
        # gaps are NOT re-packed: walk keeps the range it was authored at
        assert meta[0]["start_frame"] == 32

    def test_an_unknown_name_refuses_and_lists_what_is_there(self, fake):
        _author(fake, name="idle")
        with pytest.raises(HandlerError, match="no clip named 'nope'"):
            clip.delete_clip({"root": "root", "name": "nope"})
        assert fake.checkpoints == ["author_clip"]

    def test_deleting_the_last_named_clip_completes_the_teardown(self, fake):
        _author(fake, name="idle")
        out = clip.delete_clip({"root": "root", "name": "idle"})
        assert out["clips"] == []
        assert "mcp_clip" not in fake.string_attrs.get("|root", {})
        assert any("last clip" in w for w in out["warnings"])

    def test_deleting_without_a_name_still_removes_everything(self, fake):
        _author(fake, name="idle")
        _author(fake, name="walk")
        out = clip.delete_clip({"root": "root"})
        assert out["clips"] == []
        assert not any(p.startswith("|root|mid.rotate") for p in fake.curves)
        assert "mcp_clip" not in fake.string_attrs.get("|root", {})
        assert "mcp_clip_rest" not in fake.string_attrs.get("|root", {})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_clip.py::TestDelete -q`
Expected: FAIL — `name` is ignored, so the first test finds every curve gone.

- [ ] **Step 3: Rework `delete_clip`**

Replace the body of `delete_clip` in `maya_plugin/handlers/clip.py` from the `records = clip_meta(...)` line through the return with:

```python
    records = clip_meta(cmds, root_long)
    meshes = rigging._bound_meshes(cmds, set(joints))
    alias_map = _weight_alias_map(cmds, meshes)
    weight_plugs = ["%s.%s" % (node, a) for a, node in alias_map.items()
                    if not isinstance(node, HandlerError)]
    driven = _anim_curves(cmds, _joint_plugs(joints) + weight_plugs)
    if not driven and not records:
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; this tool removes it")

    name = params.get("name")
    if name is not None and not isinstance(name, str):
        raise HandlerError("name must be a string, or omitted to delete "
                           "every clip on this rig")
    doomed_record = None
    kept: List[Dict[str, Any]] = []
    if name is not None:
        doomed_record, kept = clipmath.drop_record(records, name)
        if doomed_record is None:
            raise HandlerError(
                "no clip named %r on %s (has: %s)"
                % (name, _short(root_long),
                   ", ".join(repr(r["name"]) for r in records) or "none"),
                hint="omit `name` to delete every clip and return the "
                     "skeleton to static posing")

    warnings: List[str] = []
    if not records and driven:
        warnings.append(
            "no clip metadata on %s - deleting %d hand-authored curve "
            "channel(s)" % (_short(root_long), len(driven)))

    session.auto_checkpoint("delete_clip")
    before = {m: _points(m) for m in meshes}

    deleted_curves = 0
    if kept:
        # ONE clip out of several: cut its range only. Gaps are NOT
        # re-packed (#718 decision 5) - a take is an explicit range, so a
        # gap costs nothing, and re-packing would move keys the caller did
        # not touch.
        for plug in sorted(driven):
            cmds.cutKey(plug, time=(doomed_record["start_frame"],
                                    doomed_record["end_frame"]), clear=True)
        remaining = _anim_curves(cmds, _joint_plugs(joints) + weight_plugs)
        deleted_curves = len({c for curves in driven.values() for c in curves}
                             - {c for curves in remaining.values()
                                for c in curves})
        cmds.setAttr("%s.%s" % (root_long, CLIP_ATTR), json.dumps(kept),
                     type="string")
        span_end = max(r["end_frame"] for r in kept)
        cmds.playbackOptions(edit=True, minTime=0, maxTime=span_end,
                             animationStartTime=0, animationEndTime=span_end)
    else:
        if name is not None:
            warnings.append(
                "%r was the last clip on this rig - the full teardown ran: "
                "weight channels zeroed, bind pose restored" % name)
        doomed = sorted({c for curves in driven.values() for c in curves})
        if doomed:
            cmds.delete(*doomed)
        deleted_curves = len(doomed)
        # Weights back to 0 (weights-all-0 IS the reset, the P5 rule), then
        # the skeleton back to bind - reset_pose's exact logic inline so
        # this call holds ONE checkpoint.
        for plug in weight_plugs:
            if plug in driven:
                cmds.setAttr(plug, 0.0)
        poses = cmds.dagPose(root_long, query=True, bindPose=True) or []
        if poses:
            cmds.dagPose(poses[0], restore=True, g=True)
            if len(poses) > 1:
                warnings.append("%d bind poses exist; restored %s"
                                % (len(poses), poses[0]))
        else:
            for joint in joints:
                cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)
            warnings.append(
                "no bind pose exists (nothing is bound); rotations zeroed, "
                "which is the create_skeleton rest pose")
        for attr in (CLIP_ATTR, REST_ATTR):
            if cmds.attributeQuery(attr, node=root_long, exists=True):
                cmds.deleteAttr("%s.%s" % (root_long, attr))

    max_disp = 0.0
    for mesh in meshes:
        max_disp = max(max_disp, sculpt_math.max_displacement(
            before[mesh], _points(mesh)))
    return {
        "root": root_long,
        "clip": (doomed_record["name"] if doomed_record
                 else (records[0]["name"] if records else None)),
        "clips": [r["name"] for r in kept],
        "deleted_curves": deleted_curves,
        "max_displacement": max_disp,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_clip.py::TestDelete -q`
Expected: PASS.

Then: `uv run pytest tests/ --junitxml=%TEMP%\t5.xml -q`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/clip.py tests/test_clip.py && git commit -m "feat(#718): delete_clip removes one named clip or all of them"
```

---

### Task 6: `preview_clip` renders a named clip's own range

**Files:**
- Modify: `maya_plugin/handlers/clip.py` (`preview_clip`)
- Test: `tests/test_clip.py` (`class TestPreviewClip`)

**Interfaces:**
- Consumes: `clip.clip_meta` (Task 2).
- Produces: `preview_clip` result gains `start_frame`, `end_frame`; `frames` entries stay `{frame, time_s}` where `frame` is the ABSOLUTE timeline frame and `time_s` is relative to the clip's own start, so a preview reads the same whether the clip is first or fourth.

- [ ] **Step 1: Write the failing tests**

In `tests/test_clip.py`, replace the `match="live clip is 'idle'"` assertion inside `TestPreviewClip::test_refusals` with:

```python
        with pytest.raises(HandlerError, match="no clip named 'walk'"):
            clip.preview_clip({"root": "root", "name": "walk"})
```

and add to `class TestPreviewClip`:

```python
    def test_a_later_clip_renders_its_own_absolute_frames(self, fake,
                                                          monkeypatch):
        calls = self._wire(fake, monkeypatch)      # authors 'idle', 0..60
        _author(fake, name="walk", fps=30, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 20]}}])
        out = clip.preview_clip({"root": "root", "name": "walk"})
        assert (out["start_frame"], out["end_frame"]) == (62, 92)
        # absolute frames drive the scene...
        assert [s["time"] for s in calls["shots"]][0] == 62
        assert [s["time"] for s in calls["shots"]][-1] == 92
        # ...clip-relative seconds are what the caller reads
        assert out["frames"][0] == {"frame": 62, "time_s": 0.0}
        assert out["frames"][-1]["time_s"] == pytest.approx(1.0)
        assert calls["shots"][0]["label"] == "t=0.00s"
        assert out["clip"] == "walk"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_clip.py::TestPreviewClip -q`
Expected: FAIL — the refusal still says "the live clip is", and the shots start at frame 0.

- [ ] **Step 3: Rewrite `preview_clip`'s lookup and frame list**

In `maya_plugin/handlers/clip.py`, replace the metadata/duration block at the top of `preview_clip` (from `records = clip_meta(...)` through the `duration_frames <= 0` refusal) with:

```python
    records = clip_meta(cmds, root_long)
    if not records:
        raise HandlerError(
            "no clip exists on %s" % root_long,
            hint="author_clip creates one; preview_clip renders it")
    name = params.get("name")
    meta = next((r for r in records if r["name"] == name), None)
    if meta is None:
        raise HandlerError(
            "no clip named %r on %s (has: %s)"
            % (name, _short(root_long),
               ", ".join(repr(r["name"]) for r in records)),
            hint="a rig carries several clips now - pass the one to judge")
    fps = int(meta.get("fps", 30))
    start_frame = int(meta["start_frame"])
    duration_frames = int(meta["end_frame"]) - start_frame
    if duration_frames <= 0:
        raise HandlerError("the clip has zero duration",
                           hint="re-author it; this is a broken metadata "
                                "state, not a render problem")
```

Then, where the shots are built, offset the driven time and keep the reported seconds clip-relative:

```python
    shots = []
    for i, offset in enumerate(frames):
        shots.append({
            "label": "t=%.2fs" % (offset / float(fps)),
            "angle": angle,
            "isolate": None,
            "frame_on": meshes,
            "time": start_frame + offset,
            "reuse_camera": i > 0,
        })
    result = render._run_shots(cmds, shots, render_params)
    result["clip"] = meta["name"]
    result["fps"] = fps
    result["start_frame"] = start_frame
    result["end_frame"] = start_frame + duration_frames
    result["frames"] = [{"frame": start_frame + f, "time_s": f / float(fps)}
                        for f in frames]
    return result
```

(`frames` stays the list of clip-relative offsets `0 .. duration_frames` the existing `every_nth` logic builds — do not change that logic.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_clip.py -q`
Expected: PASS.

Then: `uv run pytest tests/ --junitxml=%TEMP%\t6.xml -q`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/clip.py tests/test_clip.py && git commit -m "feat(#718): preview_clip renders the named clip's own range"
```

---

### Task 7: the byte reader learns each take's start and stop

`anim_facts` reports a take's duration but not WHERE it sits. The multi-take gate has to check each take's range against the range the clip declared, so the reader must expose it.

**Files:**
- Modify: `maya_plugin/handlers/fbxbytes.py` (`anim_facts`, ~line 708)
- Test: `tests/test_fbxbytes.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: every entry of `anim_facts(facts)["takes"]` becomes `{"name": str, "start_s": Optional[float], "stop_s": Optional[float], "duration_s": Optional[float]}`. Seconds, converted through the pinned `KTIME_PER_SECOND`; `None` when the file carries no `LocalTime` for that take. Reading, not policy — the comparison lives in `export.anim_violations`.

- [ ] **Step 1: Write the failing test**

In `tests/test_fbxbytes.py`, update `test_a_healthy_file_reads_clean`'s take assertion and add a second test:

```python
    def test_a_healthy_file_reads_clean(self):
        out = fbxbytes.anim_facts(self._facts())
        assert out["stacks"] == 1 and out["layers"] == 1
        assert out["curves"] == 3 and out["curve_nodes"] == 1
        assert out["takes"] == [{"name": "walk", "start_s": 0.0,
                                 "stop_s": 1.0, "duration_s": 1.0}]
        assert out["targets"] == [{"target": "L_hip",
                                   "property": "Lcl Rotation", "curves": 3,
                                   "key_count": 31, "duration_s": 1.0}]
        assert out["unavailable_reason"] is None

    def test_a_take_reports_where_it_sits_not_only_how_long_it_is(self):
        """#718: several takes share one timeline, so the gate needs each
        take's own start and stop, not just its length."""
        facts = self._facts()
        tick = fbxbytes.KTIME_PER_SECOND
        facts.takes = [
            {"name": "idle", "start_tick": 0, "stop_tick": 2 * tick},
            {"name": "walk", "start_tick": 62 * tick // 30,
             "stop_tick": 98 * tick // 30},
            {"name": "nolocaltime", "start_tick": None, "stop_tick": None},
        ]
        takes = {t["name"]: t for t in fbxbytes.anim_facts(facts)["takes"]}
        assert takes["idle"]["start_s"] == 0.0
        assert takes["idle"]["stop_s"] == 2.0
        assert takes["walk"]["start_s"] == pytest.approx(62 / 30.0, abs=1e-6)
        assert takes["walk"]["duration_s"] == pytest.approx(36 / 30.0,
                                                            abs=1e-6)
        assert takes["nolocaltime"] == {"name": "nolocaltime",
                                        "start_s": None, "stop_s": None,
                                        "duration_s": None}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_fbxbytes.py -k "anim or take" -q`
Expected: FAIL — `KeyError: 'start_s'`.

- [ ] **Step 3: Extend the reader**

In `maya_plugin/handlers/fbxbytes.py`, replace the `takes` loop in `anim_facts`:

```python
    takes = []
    for take in facts.takes:
        start = stop = duration = None
        if take["start_tick"] is not None:
            start = take["start_tick"] / float(KTIME_PER_SECOND)
        if take["stop_tick"] is not None:
            stop = take["stop_tick"] / float(KTIME_PER_SECOND)
        if start is not None and stop is not None:
            duration = stop - start
        takes.append({"name": take["name"], "start_s": start,
                      "stop_s": stop, "duration_s": duration})
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest tests/test_fbxbytes.py -q`
Expected: PASS.

Then: `uv run pytest tests/ --junitxml=%TEMP%\t7.xml -q`
Expected: `tests/test_export_fbx.py::TestAnimViolations` may fail if it compares whole take dicts — it does not (it reads `["duration_s"]`), so expect no failures.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/fbxbytes.py tests/test_fbxbytes.py && git commit -m "feat(#718): anim_facts reports where each take sits on the timeline"
```

---

### Task 8: `export_fbx` writes one take per clip, and the gate checks all of them

**Files:**
- Modify: `maya_plugin/handlers/export.py` (`_scene_clip` → `_scene_clips` ~line 325, `anim_violations` ~line 343, `export_fbx`'s bake/split block ~line 584, the result's `animation` field)
- Test: `tests/test_export_fbx.py`

**Interfaces:**
- Consumes: `clip.clip_meta` (Task 2), `clipmath.overlap_violations` (Task 1), `fbxbytes.anim_facts` take ranges (Task 7).
- Produces:
  - `export._scene_clips(cmds) -> Optional[Dict]` returning `{"root": <short name>, "fps": int, "span_frames": int, "clips": [record, ...]}` — `span_frames` is the last `end_frame` (the bake range is `0 .. span_frames`). Still refuses when **two skeletons** carry clips, with the corrected message.
  - `export.anim_violations(afacts, declared)` where `declared` is that dict or `None`.
  - `export.anim_clip_facts(afacts, declared) -> List[Dict]` — the per-clip block the result grows: `{"name", "start_frame", "end_frame", "duration_s", "curves"}`, every value read back from the BYTES (frames converted from the take's own `start_s`/`stop_s`, `curves` summed over the curve records driving the channels that clip declared). `export_fbx` sets `animation["clips"]` from it.

**The measured truths this rests on** (phase 6, `TestClipExportInMaya`): `FBXExportSplitAnimationIntoTakes` ADDS a take alongside Maya's own always-present `Take 001`, so takes are looked up BY NAME and extras are never violations; `FBXExportBakeResampleAnimation -v true` is required or curves keep raw keys instead of one key per frame; the bundled `fbxmaya` caches the scene fps at plugin LOAD, so an animated export reloads it first. All three stay exactly as they are. What is NOT yet measured is whether a per-take split segments the curve records or leaves one curve per plug spanning the whole bake range — this task assumes ONE curve per plug over the full span (`span_frames + 1` keys), and **Task 10 measures it and corrects whatever reality contradicts.**

- [ ] **Step 1: Write the failing tests**

Replace `class TestAnimViolations`'s `_declared` / `_clean` helpers in `tests/test_export_fbx.py` and add the multi-take cases (keep every existing test in the class, updating them to the new `declared` shape):

```python
class TestAnimViolations:
    """#695/#718: the include_animation contract, judged from the BYTES
    against what the SCENE's clip metadata declared - now per clip."""

    def _record(self, name, start, end, **kw):
        record = {"name": name, "fps": 30, "start_frame": start,
                  "end_frame": end, "duration_s": (end - start) / 30.0,
                  "loop": False, "interpolation": "linear",
                  "joints": ["L_hip"], "weight_channels": [],
                  "root_position_used": False}
        record.update(kw)
        return record

    def _declared(self):
        return {"root": "pelvis", "fps": 30, "span_frames": 62,
                "clips": [
                    self._record("idle", 0, 30, weight_channels=["blink"]),
                    self._record("walk", 32, 62, root_position_used=True),
                ]}

    def _take(self, name, start, stop):
        return {"name": name, "start_s": start / 30.0,
                "stop_s": stop / 30.0, "duration_s": (stop - start) / 30.0}

    def _clean(self):
        return {"stacks": 1, "layers": 1, "curves": 7, "curve_nodes": 3,
                "takes": [self._take("Take 001", 0, 62),
                          self._take("idle", 0, 30),
                          self._take("walk", 32, 62)],
                "targets": [
                    {"target": "L_hip", "property": "Lcl Rotation",
                     "curves": 3, "key_count": 63, "duration_s": 2.0666},
                    {"target": "pelvis", "property": "Lcl Translation",
                     "curves": 3, "key_count": 63, "duration_s": 2.0666},
                    {"target": "blink", "property": "DeformPercent",
                     "curves": 1, "key_count": 63, "duration_s": 2.0666},
                ],
                "unavailable_reason": None}

    def test_a_matching_file_passes(self):
        assert export.anim_violations(self._clean(), self._declared()) == []

    def test_every_declared_clip_needs_its_own_take(self):
        afacts = self._clean()
        afacts["takes"] = [t for t in afacts["takes"] if t["name"] != "walk"]
        out = export.anim_violations(afacts, self._declared())
        assert any("no take named 'walk'" in v for v in out)
        assert not any("idle" in v for v in out)

    def test_a_take_at_the_wrong_place_on_the_timeline_fails(self):
        afacts = self._clean()
        afacts["takes"][2] = self._take("walk", 0, 30)
        out = export.anim_violations(afacts, self._declared())
        assert any("'walk'" in v and "frames 32-62" in v for v in out)

    def test_overlapping_or_repeated_declarations_fail(self):
        declared = self._declared()
        declared["clips"][1]["start_frame"] = 30
        out = export.anim_violations(self._clean(), declared)
        assert any("overlap" in v for v in out)

    def test_extra_takes_are_not_violations(self):
        # Maya's own default take ("Take 001") rides along with every
        # animated export this tool makes - MEASURED in phase 6.
        assert export.anim_violations(self._clean(), self._declared()) == []

    def test_curves_are_required_for_every_channel_any_clip_declared(self):
        afacts = self._clean()
        afacts["targets"] = [t for t in afacts["targets"]
                             if t["target"] != "blink"]
        out = export.anim_violations(afacts, self._declared())
        assert any("blink" in v for v in out)
        afacts = self._clean()
        afacts["targets"] = [t for t in afacts["targets"]
                             if t["target"] != "pelvis"]
        out = export.anim_violations(afacts, self._declared())
        assert any("root translation" in v for v in out)

    def test_keys_are_counted_over_the_whole_span(self):
        afacts = self._clean()
        afacts["targets"][0]["key_count"] = 31    # one clip's worth
        out = export.anim_violations(afacts, self._declared())
        assert any("L_hip" in v and "63" in v for v in out)

    def test_include_animation_false_asserts_zero_curves(self):
        empty = {"stacks": 0, "layers": 0, "curves": 0, "curve_nodes": 0,
                 "takes": [], "targets": [], "unavailable_reason": None}
        assert export.anim_violations(empty, None) == []
        out = export.anim_violations(self._clean(), None)
        assert any("include_animation" in v for v in out)

    def test_the_per_clip_block_is_read_back_from_the_bytes(self):
        """#718: the result grows a per-clip list - name, the frame range
        the FILE says the take spans, its duration and the curve count
        measured back from the records, never echoed from the scene."""
        clips = export.anim_clip_facts(self._clean(), self._declared())
        assert [c["name"] for c in clips] == ["idle", "walk"]
        assert (clips[0]["start_frame"], clips[0]["end_frame"]) == (0, 30)
        assert (clips[1]["start_frame"], clips[1]["end_frame"]) == (32, 62)
        assert clips[0]["duration_s"] == pytest.approx(1.0)
        # idle declares L_hip (3 curves) and blink (1)
        assert clips[0]["curves"] == 4
        # walk declares L_hip (3) and the root's translation (3)
        assert clips[1]["curves"] == 6
        # a take the file does not carry reports its range as None, and
        # says so rather than inventing one
        afacts = self._clean()
        afacts["takes"] = [t for t in afacts["takes"] if t["name"] != "walk"]
        clips = export.anim_clip_facts(afacts, self._declared())
        assert clips[1]["start_frame"] is None
        assert clips[1]["curves"] == 6
```

Add, beside the existing `_scene_clip` tests in the same file:

```python
class TestSceneClips:
    def test_two_rigs_carrying_clips_refuse_with_the_corrected_message(self):
        import json

        from maya_plugin.dispatcher import HandlerError

        class Cmds:
            def ls(self, type=None, long=False):
                return ["|rig_a", "|rig_b"]

            def attributeQuery(self, attr, node=None, exists=False):
                return True

            def getAttr(self, plug):
                return json.dumps([{"name": "idle", "fps": 30,
                                    "start_frame": 0, "end_frame": 30,
                                    "duration_s": 1.0}])

        with pytest.raises(HandlerError) as excinfo:
            export._scene_clips(Cmds())
        message = str(excinfo.value)
        assert "rig_a" in message and "rig_b" in message
        assert "several clips" in message and "two skeletons" in message
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_export_fbx.py -k "AnimViolations or SceneClips" -q`
Expected: FAIL — `_scene_clips` does not exist and `anim_violations` reads `declared["name"]`.

- [ ] **Step 3: Rework `export.py`**

Replace `_scene_clip` with:

```python
def _scene_clips(cmds):
    """The clips maya_author_clip stamped, and the span they occupy.

    Multi-CLIP is supported (#718): one rig, N takes on one timeline. Two
    SKELETONS carrying clips still refuses - a take is a frame range over
    the WHOLE file, so a multi-rig file needs a timeline policy of its own.
    """
    roots = [j for j in cmds.ls(type="joint", long=True) or []
             if cmds.attributeQuery(clip_mod.CLIP_ATTR, node=j, exists=True)]
    if not roots:
        return None
    if len(roots) > 1:
        raise HandlerError(
            "%d skeletons carry clips (%s) - one rig may carry several "
            "clips and they all export as named takes, but two skeletons "
            "cannot: a take is a frame range over the whole file"
            % (len(roots), ", ".join(r.split("|")[-1] for r in roots)),
            hint="delete_clip the skeletons not being exported")
    records = clip_mod.clip_meta(cmds, roots[0])
    if not records:
        return None
    return {"root": roots[0].split("|")[-1],
            "fps": records[0]["fps"],
            "span_frames": max(r["end_frame"] for r in records),
            "clips": records}
```

Replace `anim_violations`'s body after the `declared is None` early return with:

```python
    if afacts["unavailable_reason"]:
        out.append("animation records unreadable: %s"
                   % afacts["unavailable_reason"])
    out += clipmath.overlap_violations(declared["clips"])
    fps = float(declared["fps"])
    tol = 1.0 / fps
    by_take = {}
    for take in afacts["takes"]:
        by_take.setdefault(take["name"], take)
    for record in declared["clips"]:
        take = by_take.get(record["name"])
        if take is None:
            # MEASURED under mayapy (phase 6): the exporter's own default
            # take ("Take 001") is always present alongside the ones
            # FBXExportSplitAnimationIntoTakes names, so takes are looked
            # up BY NAME and extras are not violations - the same rule
            # shape_violations applies to undeclared blendShape channels.
            out.append(
                "the file carries no take named %r (has: %s)"
                % (record["name"],
                   ", ".join(repr(t["name"]) for t in afacts["takes"])
                   or "none"))
            continue
        want_start = record["start_frame"] / fps
        want_stop = record["end_frame"] / fps
        if (take["start_s"] is None or take["stop_s"] is None
                or abs(take["start_s"] - want_start) > tol
                or abs(take["stop_s"] - want_stop) > tol):
            out.append(
                "the take %r spans %s..%s s, the clip declares frames "
                "%d-%d (%g..%g s)"
                % (record["name"], take["start_s"], take["stop_s"],
                   record["start_frame"], record["end_frame"],
                   want_start, want_stop))
    # One curve per plug spans the WHOLE bake range, so the key count is
    # the span's, not any single clip's, and the channel set is the union
    # of every clip's declarations - which is exactly what the
    # self-contained rule keys at every clip boundary.
    expected = int(declared["span_frames"]) + 1
    union = clipmath.channel_union(declared["clips"])
    by = {}
    for t in afacts["targets"]:
        by.setdefault((t["target"], t["property"]), t)
    for joint in union["joints"]:
        t = by.get((joint, "Lcl Rotation"))
        if t is None:
            out.append("joint %r has no rotation curves in the file" % joint)
            continue
        if t["curves"] != 3:
            out.append("joint %r carries %d curve(s), expected 3 (X, Y, Z)"
                       % (joint, t["curves"]))
        if t["key_count"] != expected:
            out.append("joint %r bakes %s keys, expected %d"
                       % (joint, t["key_count"], expected))
    if union["root_position_used"]:
        t = by.get((declared["root"], "Lcl Translation"))
        if t is None:
            out.append("a clip keys the root's position but the file "
                       "carries no root translation curves")
        elif t["key_count"] != expected:
            out.append("root translation bakes %s keys, expected %d"
                       % (t["key_count"], expected))
    for alias in union["weight_channels"]:
        t = by.get((alias, "DeformPercent"))
        if t is None:
            out.append("weight channel %r has no curves in the file" % alias)
        elif (t["key_count"] or 0) < 2:
            out.append("weight channel %r carries %s key(s), expected at "
                       "least 2" % (alias, t["key_count"]))
    return out
```

Add `anim_clip_facts` immediately after `anim_violations` — reading, not policy: it says what the file holds per clip, and never decides whether that is allowed:

```python
def anim_clip_facts(afacts, declared) -> List[Dict[str, Any]]:
    """Per declared clip, what the FILE holds for it: the frame range its
    take spans (converted back from the take's own LocalTime, not echoed
    from the scene), its duration, and the curve records driving the
    channels that clip declared. A clip whose take is absent reports a
    null range rather than an invented one - anim_violations is what
    fails the export for it."""
    fps = float(declared["fps"])
    by_take = {}
    for take in afacts["takes"]:
        by_take.setdefault(take["name"], take)
    by_target = {}
    for t in afacts["targets"]:
        by_target.setdefault((t["target"], t["property"]), t)
    out = []
    for record in declared["clips"]:
        take = by_take.get(record["name"])
        start = end = duration = None
        if take and take["start_s"] is not None and take["stop_s"] is not None:
            start = int(round(take["start_s"] * fps))
            end = int(round(take["stop_s"] * fps))
            duration = take["duration_s"]
        curves = 0
        for joint in record["joints"]:
            entry = by_target.get((joint, "Lcl Rotation"))
            curves += entry["curves"] if entry else 0
        for alias in record["weight_channels"]:
            entry = by_target.get((alias, "DeformPercent"))
            curves += entry["curves"] if entry else 0
        if record["root_position_used"]:
            entry = by_target.get((declared["root"], "Lcl Translation"))
            curves += entry["curves"] if entry else 0
        out.append({"name": record["name"], "start_frame": start,
                    "end_frame": end, "duration_s": duration,
                    "curves": curves})
    return out
```

Then, in `export_fbx`, where `anim_block` is composed, attach the per-clip list:

```python
    anim_block = fbxbytes.anim_facts(facts)
    if include_animation:
        anim_block["clips"] = anim_clip_facts(anim_block, declared_clip)
```

(placed immediately after the existing `anim_block = ...` line and before `anim_violations` is called).

Add the import at the top of `export.py`, beside `from . import clip as clip_mod`:

```python
from . import clipmath
```

In `export_fbx`, rename the variable and rewrite the bake/split block:

```python
    declared_clip = _scene_clips(cmds) if include_animation else None
    if include_animation and declared_clip is None:
        raise HandlerError(
            "include_animation=true but no clip exists",
            hint="author_clip keys the motion first; a static export needs "
                 "no flag at all")
```

and:

```python
    if include_animation:
        span = int(declared_clip["span_frames"])
        mel.eval("FBXExportBakeComplexStart -v 0")
        mel.eval("FBXExportBakeComplexEnd -v %d" % span)
        # One take per clip, all on ONE baked timeline (#718). The split
        # ADDS takes alongside the exporter's own default "Take 001"
        # (MEASURED, phase 6) - a correct multi-take file therefore carries
        # len(clips) + 1 takes, and the gate looks each declared one up by
        # name.
        mel.eval("FBXExportSplitAnimationIntoTakes -clear")
        for record in declared_clip["clips"]:
            mel.eval('FBXExportSplitAnimationIntoTakes -v "%s" %d %d'
                     % (record["name"], record["start_frame"],
                        record["end_frame"]))
```

Leave the long `FBX_ANIM_MEL` comment, the fbxmaya reload, and the violation/unlink machinery untouched.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_export_fbx.py -q`
Expected: PASS — including the pre-existing `_validate`, unit-gate and skin tests.

Then: `uv run pytest tests/ --junitxml=%TEMP%\t8.xml -q`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/export.py tests/test_export_fbx.py && git commit -m "feat(#718): export_fbx writes one named take per clip"
```

---

### Task 9: the MCP surface and the protocol doc

**Files:**
- Modify: `src/maya_mcp/schemas.py` (`AuthorClipResult` ~line 737, `DeleteClipResult` ~line 758, `TakeRecord` ~line 768)
- Modify: `src/maya_mcp/server.py` (`maya_author_clip` ~line 2295, `maya_delete_clip` ~line 2349, `maya_preview_clip` ~line 2366)
- Modify: `docs/protocol.md` (the "rigging phase 6 / clips" section, ~lines 497-560, and the Delivery table's `export_fbx` row)
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Consumes: the handler returns from Tasks 3-8.
- Produces: `schemas.ClipRecord`; `AuthorClipResult` with `start_frame`, `end_frame`, `clips`, `padded_channels`, `back_filled`; `DeleteClipResult` with `clips`; `TakeRecord` with `start_s`, `stop_s`; `maya_delete_clip(root, name=None, timeout_s=...)`.
- The tool COUNT does not change (56). `tests/test_server_tools.py` pins the exact tool set — do not add or remove a tool here.

- [ ] **Step 1: Write the failing tests**

In `tests/test_server_tools.py`, beside the existing schema tests:

```python
class TestMultiTakeSurface:
    """#718: one rig carries N clips, and the surface has to say so."""

    def test_delete_clip_takes_an_optional_name(self):
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        schema = tools["maya_delete_clip"].input_schema
        assert "name" in schema["properties"]
        assert "name" not in schema.get("required", [])
        assert "every clip" in schema["properties"]["name"]["description"]

    def test_author_clip_says_clips_no_longer_replace_each_other(self):
        mcp = server_mod.create_server(FakeConn())
        tools = {t.name: t for t in run(mcp.list_tools())}
        desc = tools["maya_author_clip"].description
        assert "APPENDED" in desc or "appended" in desc
        assert "ONE file" in desc or "one file" in desc

    def test_author_clip_result_reports_the_range_it_took(self):
        from maya_mcp.schemas import AuthorClipResult

        fields = AuthorClipResult.model_fields
        for name in ("start_frame", "end_frame", "clips", "padded_channels",
                     "back_filled"):
            assert name in fields, sorted(fields)

    def test_take_records_carry_their_place_on_the_timeline(self):
        from maya_mcp.schemas import AnimFacts, DeleteClipResult, TakeRecord

        assert "start_s" in TakeRecord.model_fields
        assert "stop_s" in TakeRecord.model_fields
        assert "clips" in AnimFacts.model_fields
        assert "clips" in DeleteClipResult.model_fields
```

(`server_mod`, `FakeConn` and `run` are `tests/test_server_tools.py`'s own module-level helpers — the idiom every schema test in that file uses.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_server_tools.py -k "delete_clip or author_clip_result or take_records" -q`
Expected: FAIL — `name` absent, `start_frame` absent.

- [ ] **Step 3: Update the schemas, the tools and the doc**

In `src/maya_mcp/schemas.py`, add above `AuthorClipResult`:

```python
class ClipRecord(BaseModel):
    """One clip on a rig: a named frame range on the shared timeline."""

    model_config = ConfigDict(extra="ignore")

    name: str
    fps: int
    start_frame: int
    end_frame: int
    duration_s: float
    loop: bool = False
    interpolation: str = "linear"
    joints: List[str] = Field(default_factory=list)
    weight_channels: List[str] = Field(default_factory=list)
    root_position_used: bool = False


class BackFillReport(BaseModel):
    """Channels this clip introduced, pinned at rest across the clips that
    predate them - so those clips measure exactly what they measured when
    they were authored."""

    model_config = ConfigDict(extra="ignore")

    clips: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)
```

Add to `AuthorClipResult`, after `replaced`:

```python
    start_frame: int = Field(description=(
        "First frame of the range this clip took. Derived and REPORTED - "
        "the caller never computes frames."))
    end_frame: int = Field(description=(
        "Last frame of the range, MEASURED back from the curves."))
    clips: List[str] = Field(default_factory=list, description=(
        "Every clip on this rig now, in timeline order. All of them export "
        "as named takes into one FBX."))
    padded_channels: List[str] = Field(default_factory=list, description=(
        "Channels other clips touch that this one does not - keyed at rest "
        "at this clip's own boundary frames so the take is self-contained."))
    back_filled: BackFillReport = Field(default_factory=BackFillReport,
                                        description=(
        "Channels this clip introduced, pinned at rest across earlier "
        "clips. Never a change to their motion - a restoration of it."))
```

and change `replaced`'s description to `"The clip this call re-authored (same name), re-appended at the tail. None for a new name."`.

Add to `DeleteClipResult`:

```python
    clips: List[str] = Field(default_factory=list, description=(
        "The clips left on the rig, in timeline order."))
```

Add to `TakeRecord`:

```python
    start_s: Optional[float] = Field(default=None, description=(
        "Where the take starts on the file's timeline, from its LocalTime "
        "ticks. Several takes share one timeline (#718)."))
    stop_s: Optional[float] = None
```

Add `AnimClipFacts` above `AnimFacts`, and a `clips` field to `AnimFacts`:

```python
class AnimClipFacts(BaseModel):
    """One declared clip as the FILE holds it - the frame range read back
    from its take, not echoed from the scene."""

    model_config = ConfigDict(extra="ignore")

    name: str
    start_frame: Optional[int] = None
    end_frame: Optional[int] = None
    duration_s: Optional[float] = None
    curves: int = Field(description=(
        "Curve records driving the channels this clip declared."))
```

```python
    clips: List[AnimClipFacts] = Field(default_factory=list, description=(
        "Per declared clip, what the file carries for it. One rig may hold "
        "several clips and they all export as named takes into this one "
        "file (#718)."))
```

In `src/maya_mcp/server.py`:

- `maya_delete_clip` gains a parameter and passes it through:

```python
    def maya_delete_clip(
        root: Annotated[str, Field(description="Skeleton root joint.")],
        name: Annotated[Optional[str], Field(description=(
            "Delete just this clip, leaving every other clip on the rig "
            "untouched. Omit to delete them ALL and return the skeleton to "
            "static posing. Gaps left behind are not re-packed - a take is "
            "an explicit frame range."
        ))] = None,
    ) -> DeleteClipResult:
        """Remove one clip's curves, or every clip's - the skeleton returns
        to static posing when the last one goes. Reports the measured
        displacement of the return and the clips left."""
        return DeleteClipResult.model_validate(
            maya.request("delete_clip", {"root": root, "name": name},
                         timeout_s=BOOL_TIMEOUT_S)
        )
```

- `maya_author_clip`'s docstring first paragraph becomes:

```python
        """Key the pose map over time - one rig carries as many named clips
        as the asset needs, and they all export as takes into ONE file.

        A new clip is APPENDED after the last one (its range is derived and
        reported, never passed); re-authoring a name re-appends it at the
        tail, and no other clip's motion changes. One fps per rig. Every
        clip keys every channel the rig touches at its own boundary frames,
        so a take can never inherit a neighbour's pose. While clips exist,
        static pose tools refuse; maya_delete_clip removes one or all.
        Every key's displacement is MEASURED by evaluating the scene at
        that frame. Export with maya_export_fbx include_animation=true."""
```

- `maya_preview_clip`'s `name` description becomes:

```python
        name: Annotated[str, Field(description=(
            "Which clip to render - a rig carries several. Refused with "
            "the names present if it carries no clip by this name."
        ))],
```

In `docs/protocol.md`, rewrite the clips section: the three command rows (`author_clip` result gains `start_frame, end_frame, clips, padded_channels, back_filled`; `delete_clip` params gain `name?` and its result `clips`; `preview_clip` result gains `start_frame, end_frame`), replace the "**One clip exists per skeleton at a time**" paragraph with the #718 contract (auto-append, the gap frame, re-author at the tail, one fps per rig, `delete_clip` with and without a name, the full-span playback range), add a paragraph for the self-contained rule and its back-fill, and correct the export paragraph: the bake spans `0..last end_frame`, one `FBXExportSplitAnimationIntoTakes` per clip, the file carries `len(clips) + 1` takes because Maya's own `Take 001` always rides along, and the gate checks each declared take by NAME plus its start/stop against the declared frame range. Say that `animation` now carries a per-clip `clips` list read back from the bytes, and update the Delivery table's `export_fbx` row accordingly. Note that multi-CLIP is supported and multi-RIG refuses.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_server_tools.py -q`
Expected: PASS, and the exact-tool-set test still green at 56 tools.

Then: `uv run pytest tests/ --junitxml=%TEMP%\t9.xml -q`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add src/maya_mcp/schemas.py src/maya_mcp/server.py docs/protocol.md tests/test_server_tools.py && git commit -m "feat(#718): the MCP surface and protocol carry N takes per file"
```

---

### Task 10: the mayapy measurement battery

Everything above about the FBX exporter's multi-take behaviour is inference from phase 6's single-take measurements. This task MEASURES it in a real Maya and corrects whatever reality contradicts. **On failure, fix the READER or the VIOLATION to the measured truth and record the measured value in a comment — never force the literal.**

**Files:**
- Modify: `tests/test_handlers_mayapy.py` (new `class TestMultiTakeExportInMaya`, after `TestClipExportInMaya`)
- Possibly modify: `maya_plugin/handlers/export.py`, `maya_plugin/handlers/fbxbytes.py` (only to match measurement)

**Interfaces:**
- Consumes: everything from Tasks 3-8.
- Produces: measured answers to five questions, pinned as assertions and recorded in the class docstring:
  1. how many takes a two-clip file carries and what they are named;
  2. each take's `start_s`/`stop_s` vs the declared frame ranges;
  3. whether curve records are per-take or one-per-plug over the whole span, and their key counts;
  4. what `Take 001` spans;
  5. that a channel keyed in clip A and padded in clip B holds its REST value throughout B's frames, read back from the scene at B's frames.

- [ ] **Step 1: Write the battery**

Append to `tests/test_handlers_mayapy.py`:

```python
class TestMultiTakeExportInMaya:
    """#718's measurement battery. Same reset-per-test-scene,
    persistent-process rule as TestClipExportInMaya: one prefix per test.

    Every assertion here pins a literal the byte gate rests on. On failure,
    read the raw facts (facts.takes / facts.anim_nodes), fix the READER or
    the VIOLATION to the measured truth, and record the measured value in a
    comment here - never force the literal.
    """

    def _two_clip_scene(self, cmds, prefix):
        from maya_plugin.handlers import clip, rigging

        base = cmds.ls(cmds.polyCube(name=prefix + "_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        skeleton = rigging.create_skeleton({"joints": [
            {"name": prefix + "_root", "position": [0.0, -1.0, 0.0]},
            {"name": prefix + "_mid", "position": [0.0, 0.0, 0.0],
             "parent": prefix + "_root"},
            {"name": prefix + "_tip", "position": [0.0, 1.0, 0.0],
             "parent": prefix + "_mid"}]})
        rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
        idle = clip.author_clip({
            "root": skeleton["root"], "name": "idle", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {prefix + "_mid": [0, 0, 0]}},
                {"time_s": 0.5, "rotations": {prefix + "_mid": [0, 0, 30]}},
                {"time_s": 1.0, "rotations": {prefix + "_mid": [0, 0, 0]}}]})
        walk = clip.author_clip({
            "root": skeleton["root"], "name": "walk", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {prefix + "_tip": [0, 0, 0]}},
                {"time_s": 0.5, "rotations": {prefix + "_tip": [0, 0, 25]}},
                {"time_s": 1.0, "rotations": {prefix + "_tip": [0, 0, 0]}}]})
        return base, skeleton["root"], idle, walk

    def test_the_layout_is_what_the_tool_reported(self):
        import maya.cmds as cmds

        base, root, idle, walk = self._two_clip_scene(cmds, "mt")
        assert (idle["start_frame"], idle["end_frame"]) == (0, 30)
        assert (walk["start_frame"], walk["end_frame"]) == (32, 62)
        assert walk["clips"] == ["idle", "walk"]
        assert walk["padded_channels"] == ["mt_mid"]
        assert walk["back_filled"]["channels"] == ["mt_tip"]
        assert cmds.playbackOptions(query=True, maxTime=True) == 62

    def test_a_padded_channel_holds_rest_through_the_other_clip(self):
        """THE contamination check, in the scene: mt_mid is keyed in idle
        and never mentioned in walk, so without the pad it would hold
        idle's last value through every frame of walk."""
        import maya.cmds as cmds

        base, root, idle, walk = self._two_clip_scene(cmds, "mu")
        mid = cmds.ls("mu_mid", long=True)[0]
        for frame in (32, 47, 62):
            cmds.currentTime(frame)
            assert abs(cmds.getAttr(mid + ".rotateZ")) < 1e-4, frame
        # ...and idle still measures what it measured before walk existed
        tip = cmds.ls("mu_tip", long=True)[0]
        for frame in (0, 15, 30):
            cmds.currentTime(frame)
            assert abs(cmds.getAttr(tip + ".rotateZ")) < 1e-4, frame

    def test_the_measurements(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import export, fbxbytes

        base, root, idle, walk = self._two_clip_scene(cmds, "mv")
        path = str(tmp_path / "two.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                    "nodes": [base, root],
                                    "include_skins": True,
                                    "include_animation": True})
        anim = result["animation"]
        names = [t["name"] for t in anim["takes"]]
        # (1) MEASURED: the exporter's own default take rides along with
        # the two named ones.
        assert "idle" in names and "walk" in names
        assert len(names) == 3, names
        by = {t["name"]: t for t in anim["takes"]}
        # (2) MEASURED: each split take carries its OWN LocalTime range.
        assert abs(by["idle"]["start_s"] - 0.0) < 1e-3
        assert abs(by["idle"]["stop_s"] - 1.0) < 1e-3
        assert abs(by["walk"]["start_s"] - 32 / 30.0) < 1e-3
        assert abs(by["walk"]["stop_s"] - 62 / 30.0) < 1e-3
        # (4) MEASURED: Take 001 spans the whole bake range.
        assert abs(by["Take 001"]["stop_s"] - 62 / 30.0) < 1e-3
        # (3) MEASURED: one curve record per plug, baked over the WHOLE
        # span - 63 keys at 30 fps for frames 0..62, not one record per
        # take.
        targets = {(t["target"], t["property"]): t for t in anim["targets"]}
        for joint in ("mv_mid", "mv_tip"):
            entry = targets[(joint, "Lcl Rotation")]
            assert entry["curves"] == 3
            assert entry["key_count"] == 63, entry
        # the per-clip block reads the ranges back OUT of the file
        clips = {c["name"]: c for c in anim["clips"]}
        assert (clips["idle"]["start_frame"],
                clips["idle"]["end_frame"]) == (0, 30)
        assert (clips["walk"]["start_frame"],
                clips["walk"]["end_frame"]) == (32, 62)
        assert clips["idle"]["curves"] == 3 and clips["walk"]["curves"] == 3
        # the gate agrees with the bytes
        assert export.anim_violations(anim, export._scene_clips(cmds)) == []

    def test_a_named_delete_leaves_the_other_take_exportable(self, tmp_path):
        import maya.cmds as cmds

        from maya_plugin.handlers import clip, export

        base, root, idle, walk = self._two_clip_scene(cmds, "mw")
        out = clip.delete_clip({"root": root, "name": "idle"})
        assert out["clips"] == ["walk"]
        path = str(tmp_path / "one.fbx").replace("\\", "/")
        result = export.export_fbx({"path": path, "metres_per_unit": 1.0,
                                    "nodes": [base, root],
                                    "include_skins": True,
                                    "include_animation": True})
        names = [t["name"] for t in result["animation"]["takes"]]
        assert "walk" in names and "idle" not in names
```

- [ ] **Step 2: Run the battery**

Run: `mayapy -m pytest tests/test_handlers_mayapy.py::TestMultiTakeExportInMaya -q --junitxml=%TEMP%\mt.xml`

(`mayapy` lives in Maya's `bin` directory; the repo's earlier phases ran it directly. If `maya` is not importable the whole file skips, which is NOT a pass — the battery must actually run.)

Expected on the first run: possibly FAIL on items (2) or (3). That is the point of the task.

- [ ] **Step 3: Reconcile the code with the measurement**

For each failing assertion:
1. Print the raw facts — `facts = fbxbytes.read_fbx(path)`, then `facts.takes` and `facts.anim_nodes` — and record the ACTUAL numbers.
2. Decide whether the reader (`fbxbytes.anim_facts`) or the policy (`export.anim_violations`) is wrong, and fix that.
3. Write the measured value into a comment in this test, prefixed `MEASURED:`, saying what was expected and what the file actually holds.
4. Re-run the headless suite — a policy change must keep `tests/test_export_fbx.py` honest; update those tests to the measured truth in the same commit.

Specifically, if curve records turn out to be per-take rather than one-per-plug, `anim_violations`'s `expected` becomes per-clip (`end_frame - start_frame + 1`) and the channel loop moves inside the per-clip loop — make that change and say so in the commit message.

- [ ] **Step 4: Run both suites**

Run: `mayapy -m pytest tests/test_handlers_mayapy.py -q --junitxml=%TEMP%\mayapy.xml`
Expected: 154 + this task's 4 new tests, 0 failures.

Run: `uv run pytest tests/ --junitxml=%TEMP%\t10.xml -q`
Expected: no failures.

- [ ] **Step 5: Commit**

```bash
git add tests/test_handlers_mayapy.py maya_plugin/handlers/ && git commit -m "test(#718): measure the multi-take export in a real Maya"
```

---

### Task 11: `evals/clip_live.py` asserts the NEW contract

The phase-6 gate asserts `walk["replaced"] == "idle"` and a `"replaced clip 'idle'"` warning — the contract #718 withdrew. Left alone it is a gate that fails for being right.

**Files:**
- Modify: `evals/clip_live.py` (docstring lines 1-40, the replace check at ~line 446, the take-name reports at ~lines 416 and 519)

**Interfaces:**
- Consumes: the live plugin, deployed from this branch.
- Produces: a re-run of the phase-6 gate against the new behaviour, with its own count reported.

- [ ] **Step 1: Deploy this branch's plugin into the disposable Maya**

Launch the disposable Maya on port 9878 with a NEUTRAL cwd (a repo cwd makes Maya import the repo copy and bypass the deploy), then confirm the live copy is this working tree:

```bash
uv run python -c "from evals.live_call import call; print(call('ping', {}))"
```

Expected: a `ping` result whose `loaded_digest` matches this tree and `restart_required` is false. If it does not, redeploy and restart that Maya before going further — a green gate from stale code is worse than no gate.

- [ ] **Step 2: Update the assertions**

In `evals/clip_live.py`, replace the replace-contract check:

```python
    # #718: authoring a second name APPENDS - it no longer replaces. The
    # phase-6 assertion (walk["replaced"] == "idle") tested a contract that
    # has been withdrawn; what must hold now is that idle survives and walk
    # takes the range after it.
    check("walk appends after idle instead of replacing it",
          walk["replaced"] is None
          and walk["clips"] == ["idle", "walk"]
          and walk["start_frame"] == idle["end_frame"] + 2)
```

Update the module docstring's line 9 (`the one-clip-at-a-time contract, asserted`) and line 34 (`author walk (replaces, warning asserted)`) to say what the gate now checks: *walk APPENDS after idle (#718), both takes export from one file*.

Where the gate exports and reports take names (~lines 407-420 and 505-520), assert both take names are present by NAME lookup in the second export rather than only the latest clip's.

- [ ] **Step 3: Run the gate**

Run: `uv run python evals/clip_live.py`
Expected: exit 0, every check green, and the printed count reported in the commit message. Judge the rendered sheets it writes into `evals/clip_live/` — a green count with unreadable motion is not a pass.

- [ ] **Step 4: Confirm the user's Maya was untouched**

The gate targets port 9878 and calls `new_scene`. Confirm `MAYA_MCP_PORT`/`MAYA_MCP_EXPECT_PID` pointed at the disposable instance for the whole run, and say so in the commit message.

- [ ] **Step 5: Commit**

```bash
git add evals/clip_live.py && git commit -m "test(#718): clip_live asserts the append contract, not the withdrawn replace"
```

---

### Task 12: `evals/multi_take_live.py` — the live gate

Three clips on ONE rig, deliberately keying DIFFERENT channel sets, so the self-contained rule is what is under test.

**Files:**
- Create: `evals/multi_take_live.py`
- Create (by running it): `evals/multi_take_live/` (renders, the exported FBX, `baseline.json`)

**Interfaces:**
- Consumes: `evals/live_call.py` (`call`, `structured_result`), `evals/humanoid_live.py` (`JOINTS`, `MESH`, `PARTS`), `maya_plugin.handlers.fbxbytes` for the byte read — the same imports `evals/clip_live.py` uses.
- Produces: an executable gate. `uv run python evals/multi_take_live.py`; exit 0 pass, 1 fail, 2 no connection. DESTRUCTIVE (calls `new_scene`), port 9878 per the two-Maya policy.

The five measured checks, from the spec:

1. each clip's reported range is contiguous-with-a-gap and non-overlapping;
2. re-authoring the MIDDLE clip moves it to the tail and leaves the other two clips' keys byte-identical (measured by reading key times and values back, not asserted by construction);
3. contamination, BOTH directions — inside clip B's range every joint B did not declare sits at rest; and clip A's measured per-frame displacement is IDENTICAL before and after clip C introduces a channel A never used;
4. `delete_clip` with a name removes one clip and leaves the others measurable;
5. the export carries three takes with the right spans, and previews of each clip render its own motion (judged, not just counted).

- [ ] **Step 1: Write the gate**

Create `evals/multi_take_live.py` following `evals/clip_live.py`'s structure exactly — same header, same `check(label, ok)` counter, same `ok(cmd, params)` wrapper around `call`, same PNG-writing helper, same `baseline.json` dump at the end. **`baseline.json` must carry the three clip RECORDS** (`name, fps, start_frame, end_frame, joints`) and the exported FBX's path — Task 13's Unity gate reads them from there, so the two gates cannot disagree about what was declared. Build:

- the `humanoid_live` figure + skeleton + bind (reuse `clip_live`'s scene setup verbatim; do not re-derive the rotation-axis literals — `humanoid_live.biped_pose`'s MEASURED axis table is the source);
- clip `idle` — spine/chest sway only, 2.0 s, loop;
- clip `wave` — one arm only, 1.5 s (**no overlap at all with idle's joints** — that is what makes check 3 meaningful);
- clip `step` — hips/legs plus `root_position` (introduces the root translate channel, which neither earlier clip used — that is the BACKWARDS contamination case).

For check 3, capture the measurement this way (the backwards half is the one that is easy to ship broken):

```python
# Clip idle's per-frame displacement, measured BEFORE step exists...
before = [f["max_displacement"] for f in probe_displacement("idle")]
... author "step" ...
after = [f["max_displacement"] for f in probe_displacement("idle")]
check("authoring 'step' left idle's motion identical",
      all(abs(a - b) < 1e-6 for a, b in zip(before, after))
      and len(before) == len(after))
```

where `probe_displacement(name)` drives `maya_execute_python` to walk that clip's frames and read the bound mesh's vertex positions against the clip's first frame — the same measurement `author_clip` makes, taken independently.

For the forwards half, at three frames inside `wave`'s range read every joint `idle` declared and assert its rotation is within 1e-4 of the rest value.

For check 5, export with `include_animation=true` into `evals/multi_take_live/`, read the bytes with `fbxbytes.read_fbx` + `anim_facts`, and assert the three declared take names are present with the right `start_s`/`stop_s` (by-name lookup; `Take 001` rides along and is not a violation). Then `preview_clip` each of the three by name and write the sheets out.

- [ ] **Step 2: Run it against the disposable Maya**

Run: `uv run python evals/multi_take_live.py`
Expected: exit 0. If a check fails, that is the gate doing its job — fix the product, never the threshold. Record the measured numbers.

- [ ] **Step 3: Judge the renders**

Open every sheet in `evals/multi_take_live/` and confirm with your own eyes that each clip's preview shows THAT clip's motion and nothing else — `wave`'s sheet must show a still spine, `idle`'s a still arm. A contaminated take looks exactly like a correct one in the numbers; this is the check that catches it.

- [ ] **Step 4: Confirm the port and the teardown**

Confirm the run stayed on the disposable Maya (pid-verified) and released it, and that the user's Maya was untouched.

- [ ] **Step 5: Commit**

```bash
git add evals/multi_take_live.py evals/multi_take_live/ && git commit -m "test(#718): live gate for three takes on one rig"
```

---

### Task 13: `evals/multi_take_unity.py` — the consumer gate

The #703 proof shape: a real Unity re-import, measured. The byte gate proves the file says the right thing; only the consumer proves the file MEANS it.

**Files:**
- Create: `evals/multi_take_unity.py`

**Interfaces:**
- Consumes: the FBX produced by Task 12 (or re-exported by this script), the unityMCP tools (driven by the agent, not by this script).
- Produces:
  - `UNITY_MEASURE_CS: str` — the C# the agent runs through `mcp__unityMCP__execute_code`; it reads the imported clips and prints one JSON object.
  - `verify(declared: list, measured: dict) -> List[str]` — pure, returns violations.
  - `main()` — with no arguments, prints the exact unityMCP steps to run; with `--measurements <path>`, verifies the JSON the agent captured and exits 0/1.

**Why this shape:** a Python script cannot call MCP tools; the agent does. The measurement POLICY still belongs in code, so it is reviewable and cannot drift between runs. **Never** substitute a Unity CLI batchmode run for the unityMCP tools — if the editor is not open, report that and stop (the machine's standing rule).

- [ ] **Step 1: Write the script**

Create `evals/multi_take_unity.py`:

```python
"""#718 consumer gate: a multi-take FBX re-imported by a real Unity.

The byte gate proves the FILE declares three takes; this proves UNITY
reads three clips, with the right lengths, and that a joint a clip never
keyed does not move inside that clip. That last one is the contamination
check on the consumer's side - the defect the self-contained rule exists
to prevent is invisible in the bytes.

Driven through the unityMCP TOOLS by the agent, in a SCRATCH project -
Demigol's importer forces importAnimation=false, which is exactly why this
cannot run there. This script holds the C# to run and the policy to judge
its output; it never talks to Unity itself.

If the Unity editor is not open, report that and STOP. Do NOT fall back to
a CLI batchmode run - that is the machine's standing rule, and a silent
fallback hides the breakage.

Usage:
    uv run python evals/multi_take_unity.py                 # print the steps
    uv run python evals/multi_take_unity.py --measurements m.json
Exit: 0 pass, 1 fail.
"""
```

Then:

- `DECLARED` — the three clips Task 12 authored, as `{name, fps, start_frame, end_frame, joints}` (import them from a JSON the live gate writes, so the two gates cannot disagree: have Task 12's `baseline.json` carry the records and read them here).
- `UNITY_MEASURE_CS` — C# that, for the imported model at a given path, reads `AssetDatabase.LoadAllAssetsAtPath`, collects every `AnimationClip`, and prints JSON: `{"clips": [{"name", "length", "frameRate", "curves": [{"path", "property"}]}]}`, plus, per clip, the sampled local rotation of each declared joint at three times (start, middle, end) so a joint's stillness is measurable.
- `verify(declared, measured)` returning violations for: a declared clip missing by name; a clip whose `length` differs from `(end_frame - start_frame) / fps` by more than 1e-3; a joint a clip did not declare whose sampled rotation varies by more than a small epsilon across that clip's three samples.
- `main()` printing, when run bare, the exact tool calls to make in order: `mcp__unityMCP__set_active_instance` (multiple Unitys may be up), `manage_editor` to confirm the editor is responsive, copy the FBX into the scratch project's `Assets/`, `refresh_unity`, `manage_asset` to set `importAnimation` ON and reimport, then `execute_code` with `UNITY_MEASURE_CS`, saving its JSON to a file to pass back via `--measurements`.

- [ ] **Step 2: Run the gate's own policy against a synthetic pass and fail**

Run:

```bash
uv run python -c "import sys; sys.path.insert(0,'evals'); import multi_take_unity as m; d=[{'name':'idle','fps':30,'start_frame':0,'end_frame':60,'joints':['chest']}]; print(m.verify(d, {'clips':[{'name':'idle','length':2.0,'frameRate':30.0,'samples':{}}]})); print(m.verify(d, {'clips':[]}))"
```

Expected: `[]` then a list naming the missing `'idle'`.

- [ ] **Step 3: Run the real gate through the unityMCP tools**

Follow the printed steps. If `claude mcp list` shows unityMCP unhealthy, or the editor is closed, STOP and report it — do not route around it.

Expected: three clips arrive, named `idle`, `wave`, `step`; each length matches Maya's duration to 3 decimals; every joint a clip did not declare is still within that clip.

- [ ] **Step 4: Record the measured numbers**

Write the Unity-side measurements into the script's docstring under `MEASURED:` (clip count, per-clip length, the stillness epsilon actually observed) — the next person must not have to re-derive them.

- [ ] **Step 5: Commit**

```bash
git add evals/multi_take_unity.py && git commit -m "test(#718): consumer gate - a real Unity reads all three takes"
```

---

## Wrap-up (not a task — the controller does this)

- `.superpowers/sdd/progress.md` gains a `## Multi-take FBX (#718)` section, one line per task with the commit range and the measured numbers.
- Redmine #718: comment with the measured gate results, then Resolved.
- Deploy the plugin and record the stamp; the user's Mayas hold the old modules until they restart (`ping` will say `restart_required`).
- `evals/golem_rerun_665/out_v4/` is ANOTHER AGENT'S in-flight work: never commit, clean, or edit it.

---

### Task 10b: take attribution — the correction Task 10's measurement forced

**Why this task exists.** Task 10 measured the real exporter and found the gate's core assumption false. Task 8 assumed ONE curve record per plug spanning the whole bake range. Reality: a two-clip file carries **three** `AnimationCurveNode` records per plug — one full-span record belonging to Maya's own `Take 001` (63 keys over frames 0-62), and one per named take carrying that take's own range (31 keys each). `export.anim_violations` collapses them with `by.setdefault((target, property), t)`, first-wins, and which record is "first" is decided by an FBX-internal UID that is **not stable across identical exports**: 8 back-to-back exports of one scene measured **6 passes and 2 failures**. The shipped gate randomly refuses correct files. This must be fixed before any live gate can mean anything.

**The data needed is already parsed and thrown away.** `maya_plugin/handlers/fbxbytes.py:364` drops the `AnimationCurveNode`→`AnimationLayer` and `Layer`→`Stack` connections, with a comment claiming membership "adds nothing a violation would read". Task 10's measurement falsifies that comment: membership is exactly what a violation needs.

**Files:**
- Modify: `maya_plugin/handlers/fbxbytes.py` (`read_fbx`'s record walk and connection loop; `anim_facts`)
- Modify: `maya_plugin/handlers/export.py` (`anim_violations`, `anim_clip_facts`)
- Modify: `src/maya_mcp/schemas.py` (`AnimCurveTarget` gains the take field)
- Modify: `docs/protocol.md` (the byte-gate paragraph)
- Test: `tests/test_fbxbytes.py`, `tests/test_export_fbx.py`, `tests/test_handlers_mayapy.py`

**Interfaces:**
- Produces: every `anim_facts(...)["targets"]` entry gains `take: Optional[str]` — the name of the `AnimationStack` whose layer owns that curve node, or `None` when the file carries no attribution. Reading, not policy.
- `anim_violations` checks, per declared clip, the curve records attributed to THAT take.
- `anim_clip_facts` counts a clip's curves from its own take's records.

**The per-take contract, from Task 10's measured numbers:** for a take spanning `start_frame..end_frame`, every channel ANY clip on the rig declares carries a curve record attributed to that take with `end_frame - start_frame + 1` keys. The self-contained rule guarantees every channel is keyed in every take's range, so the channel set is the union — what changes is that the key count is now the TAKE's own span, not the whole file's. Records attributed to `Take 001` or to no take remain non-violations, the same rule that already tolerates extra takes.

- [ ] **Step 1: Write the failing reader test**

In `tests/test_fbxbytes.py`, beside the existing anim tests:

```python
    def test_a_curve_node_reports_the_take_it_belongs_to(self):
        """#718 Task 10 MEASURED: a multi-take file carries one curve node
        per plug PER TAKE, plus the full-span one belonging to Maya's own
        default take. Without attribution the gate cannot tell them apart,
        and which one it happens to read is decided by an unstable UID."""
        facts = self._facts()
        tick = fbxbytes.KTIME_PER_SECOND
        facts.anim_stacks_by_uid = {70: "Take 001", 71: "idle", 72: "walk"}
        facts.anim_layers_by_uid = {80: 70, 81: 71, 82: 72}
        facts.anim_curves[20] = {"key_count": 31, "first_tick": 0,
                                 "last_tick": tick}
        facts.anim_nodes[20]["layer"] = 80          # the full-span one
        facts.anim_nodes[21] = {"name": "R", "target": 1,
                                "target_kind": "model",
                                "property": "Lcl Rotation", "curves": [20],
                                "layer": 81}
        by_take = {t["take"]: t for t in fbxbytes.anim_facts(facts)["targets"]}
        assert "idle" in by_take
        assert by_take["idle"]["property"] == "Lcl Rotation"
```

Adapt the fixture to whatever shape `read_fbx` actually produces once Step 3 lands — the point is that `targets` entries carry a `take` name, and that a node with no layer reports `None`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_fbxbytes.py -k take_it_belongs -q`
Expected: FAIL — `targets` entries have no `take` key.

- [ ] **Step 3: Keep the attribution the reader already parses**

In `read_fbx`: record each `AnimationStack`'s uid and name (it currently only increments a counter), each `AnimationLayer`'s uid, and in the connection loop keep the two arms that are currently dropped — curve-node→layer and layer→stack. Add the resolved layer/stack to each `anim_nodes` entry. Keep `anim_stacks` and `anim_layers` reporting exactly what they report today so existing assertions do not move.

In `anim_facts`, resolve each curve node's layer to its stack's NAME and put it on the target entry as `take`. `None` when the chain is absent — never a guess, never a default.

- [ ] **Step 4: Rework the policy to check per take**

In `export.anim_violations`, replace the single `by[(target, property)]` map with a per-take map `by[(take, target, property)]`, and for each declared clip check its own take's records at `end_frame - start_frame + 1` keys. Records belonging to `Take 001` or to no take are ignored, not flagged. Keep every other check as it is: the by-name take lookup, the start/stop comparison at half-frame tolerance, the overlap and duplicate-name checks, and the zero-curves assertion when `include_animation` is false.

In `anim_clip_facts`, count each clip's `curves` from its own take's records.

Write the measured numbers from `.superpowers/sdd/t718-10-report.md` into the comments — the three-records-per-plug shape and the 6-pass/2-fail non-determinism are why this code looks the way it does.

- [ ] **Step 5: Restore end-to-end gate coverage in the mayapy battery**

Task 10 routed its measurements through `TestMultiTakeExportInMaya._export_bypassing_the_gate` because the real gate was non-deterministic. With the gate fixed, add a test that calls the REAL `export.export_fbx` on a two-clip scene and passes — and run it repeatedly (at least 6 consecutive exports in one process, the shape that exposed the 6/2 split) asserting every one passes. Keep the bypass helper for the raw-record measurements that genuinely need it.

- [ ] **Step 6: Run both suites and commit**

Run: `E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=%TEMP%\t10b-mayapy.xml`
Run: `uv run pytest tests/ --junitxml=%TEMP%\t10b.xml -q`
Expected: both green, headless at 1385+ and mayapy at 161+.

```bash
git add maya_plugin/handlers/fbxbytes.py maya_plugin/handlers/export.py src/maya_mcp/schemas.py docs/protocol.md tests/ && git commit -m "fix(#718): attribute curve records to their take so the gate stops guessing"
```
