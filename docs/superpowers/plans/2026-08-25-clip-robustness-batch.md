# Clip Robustness Batch (#721p2, #729, #730, #731, #732) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five clip-robustness defects the #718 reviews and the #713 run filed: the empty-attr export refusal (#731), delete_clip's orphaned rest-pin curves (#730), the fbxmaya reload heap crash (#729), the posed-rig warning noise + rest-is-not-bind deviation (#732), and the Arnold-IPR session-hygiene trap (#721 part 2).

**Architecture:** All five are handler-level fixes inside `maya_plugin/handlers/` plus their tests. No protocol/schema changes except one new result field (`reaped_channels` on `delete_clip`). Pure math goes in `rigmath.py` (headless-testable), Maya plumbing in `clip.py`/`export.py`/`session.py`/`render.py`. Two tasks carry a live-measurement step (mayapy probe for #729; live-Maya probe for #721) whose findings feed the implementation and get recorded in the SDD ledger.

**Tech Stack:** Python (Maya plugin), pytest headless (`python -m pytest tests -q`), mayapy suite (`E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q`), live gates in `evals/` against the AGENT-launched Maya (never the user's 9879 Maya without asking).

## Global Constraints

- Branch: `fix-clip-robustness` off `main` (d6bf80d). Commits: `fix(#NNN): <what>` / `test(#NNN): <what>`.
- **Never touch `evals/golem_rerun_665/out_v4/`** — another agent's in-flight work (untracked; leave it untracked).
- Measure suites with `--junitxml=<scratch>\<name>.xml` — the pytest summary line is lost to stdout buffering on this machine. Report MEASURED pass/skip counts, never "tests pass".
- mayapy path: `E:\Autodesk\Maya2027\bin\mayapy.exe`. The mayapy suite is ONE persistent process; module state persists across tests (that is production semantics for `export.py`'s new cache tracker — do not "fix" it).
- The live gate IS the gate (memory rule): headless green is necessary, not sufficient. Live gates run against an agent-launched Maya with a neutral CWD (a repo-CWD Maya imports the repo plugin and bypasses the deploy) and `MAYA_MCP_PORT` set; verify WHICH Maya answers (pid match) before trusting results.
- `docs/protocol.md` is the tool contract; every result-shape or behavior change lands there in the same task as the code.
- Windows shell is PowerShell; `&&` is unavailable — chain with `;`.

## Ticket → task map

| Ticket | Task(s) | One-liner |
|---|---|---|
| #731 | 1 | clip detection keys on parsed records, not attr existence |
| #730 | 2 | named delete reaps whole curves no surviving clip declares |
| #729 | 3 | fbxmaya force-reload only when the scene frame rate changed |
| #732 | 4 | rest = bind pose (decomposed from dagPose); warning only when truly posed away, summarized |
| #721 p2 | 5 | stop idle Arnold IPR after renders and before keyframe work |
| all | 6 | suites + live gates + docs coherence |
| all | 7 | review, merge, deploy, ticket closeout |

---

### Task 1: #731 — clip detection predicate

**Files:**
- Modify: `maya_plugin/handlers/clip.py:173-180` (`_clips_elsewhere`)
- Modify: `maya_plugin/handlers/export.py:326-350` (`_scene_clips`)
- Test: `tests/test_clip.py`, `tests/test_export_fbx.py`

**Interfaces:**
- Consumes: `clip.clip_meta(cmds, root_long) -> List[dict]` (already returns `[]` for a missing attr, an empty value, and `"[]"`; a non-empty unparseable string still yields one name-only legacy record — that is DELIBERATE pre-#718 compat, do not change it).
- Produces: no signature changes. `_scene_clips` still returns `None` or `{root, fps, span_frames, clips}`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_clip.py` (near `TestGuards`):

```python
class TestClipsElsewherePredicate:
    def test_an_empty_clip_attr_on_another_root_is_not_a_clip(self, monkeypatch):
        # #731: a joint carrying mcp_clip that parses to [] must not trip the
        # "another skeleton carries clips" warning.
        fake = FakeCmds()
        fake.joints.append("|other")
        fake.string_attrs["|other"] = {"mcp_clip": "[]"}
        _install(fake, monkeypatch)
        out = _author(fake)
        assert not any("another skeleton carries clips" in w
                       for w in out["warnings"])

    def test_a_real_clip_on_another_root_still_warns(self, monkeypatch):
        fake = FakeCmds()
        fake.joints.append("|other")
        fake.string_attrs["|other"] = {
            "mcp_clip": json.dumps([{"name": "walk", "fps": 30,
                                     "start_frame": 0, "end_frame": 10}])}
        _install(fake, monkeypatch)
        out = _author(fake)
        assert any("another skeleton carries clips" in w
                   for w in out["warnings"])
```

(`import json` is already imported at the top of test_clip.py; add it if not.)

In `tests/test_export_fbx.py` (bottom, new class — the existing `FakeCmds` there has no joint support, so this one is local and minimal):

```python
class FakeClipSceneCmds:
    """Only what _scene_clips touches: joints, the mcp_clip attr."""
    def __init__(self, attrs):
        # attrs: {joint_long_name: mcp_clip string or None}
        self.attrs = attrs

    def ls(self, type=None, long=False):
        return list(self.attrs)

    def attributeQuery(self, attr, node=None, exists=False):
        return self.attrs.get(node) is not None

    def getAttr(self, key):
        node = key.rsplit(".", 1)[0]
        return self.attrs[node]


class TestSceneClipsPredicate:
    def _records(self):
        return json.dumps([{"name": "idle", "fps": 30,
                            "start_frame": 0, "end_frame": 30}])

    def test_an_empty_attr_beside_a_real_rig_does_not_refuse(self):
        cmds = FakeClipSceneCmds({"|rig": self._records(), "|junk": "[]"})
        declared = export._scene_clips(cmds)
        assert declared is not None and declared["root"] == "rig"

    def test_two_real_rigs_still_refuse(self):
        cmds = FakeClipSceneCmds({"|a": self._records(),
                                  "|b": self._records()})
        with pytest.raises(HandlerError, match="skeletons carry clips"):
            export._scene_clips(cmds)

    def test_only_empty_attrs_means_no_clips(self):
        cmds = FakeClipSceneCmds({"|junk": "[]"})
        assert export._scene_clips(cmds) is None
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python -m pytest tests/test_clip.py::TestClipsElsewherePredicate tests/test_export_fbx.py::TestSceneClipsPredicate -q
```

Expected: the empty-attr tests FAIL (warning fires / refusal raised); the still-warns/still-refuses tests may already pass.

- [ ] **Step 3: Fix both sites**

`clip.py::_clips_elsewhere` — replace the `attributeQuery` filter:

```python
def _clips_elsewhere(cmds, root_long: str) -> List[str]:
    """Short names of OTHER skeleton roots carrying clips. export_fbx
    refuses such a scene (a take is a frame range over the whole file, so a
    multi-rig file needs a timeline policy of its own) - and that ceiling
    should be discovered while authoring, not at write time (#718).

    Keyed on clip_meta parsing to a non-empty record list, NOT on the
    attribute existing (#731): an empty or hollow mcp_clip attr carries no
    clips and must not warn."""
    return [_short(j) for j in cmds.ls(type="joint", long=True) or []
            if j != root_long and clip_meta(cmds, j)]
```

`export.py::_scene_clips` — collect `(root, records)` pairs so the predicate and the payload read the attr once:

```python
def _scene_clips(cmds):
    """The clips maya_author_clip stamped, and the span they occupy.

    Multi-CLIP is supported (#718): one rig, N takes on one timeline. Two
    SKELETONS carrying clips still refuses - a take is a frame range over
    the WHOLE file, so a multi-rig file needs a timeline policy of its own.

    A root "carries clips" only when its mcp_clip attr parses to a
    non-empty record list (#731) - an empty or hollow attr left by a
    crashed or hand-edited scene must not refuse a good export.
    """
    carriers = [(j, records) for j in cmds.ls(type="joint", long=True) or []
                for records in [clip_mod.clip_meta(cmds, j)] if records]
    if not carriers:
        return None
    if len(carriers) > 1:
        raise HandlerError(
            "%d skeletons carry clips (%s) - one rig may carry several "
            "clips and they all export as named takes, but two skeletons "
            "cannot: a take is a frame range over the whole file"
            % (len(carriers),
               ", ".join(r.split("|")[-1] for r, _ in carriers)),
            hint="delete_clip the skeletons not being exported")
    root, records = carriers[0]
    return {"root": root.split("|")[-1],
            "fps": records[0]["fps"],
            "span_frames": max(r["end_frame"] for r in records),
            "clips": records}
```

Note `clip_meta` calls `attributeQuery` first itself, so joints without the attr stay cheap.

- [ ] **Step 4: Run the new tests plus both touched files' suites**

```bash
python -m pytest tests/test_clip.py tests/test_export_fbx.py -q
```

Expected: PASS (no regressions — `_scene_clips`'s old `if not records: return None` tail is gone with the restructure).

- [ ] **Step 5: Commit**

```bash
git add maya_plugin/handlers/clip.py maya_plugin/handlers/export.py tests/test_clip.py tests/test_export_fbx.py
git commit -m "fix(#731): clip detection keys on parsed records, not attr existence"
```

---

### Task 2: #730 — named delete reaps orphaned rest-pin curves

**Files:**
- Modify: `maya_plugin/handlers/clip.py:861-886` (the `kept` branch of `delete_clip`)
- Modify: `docs/protocol.md` (delete_clip row ~line 503; the `deleted_curves` paragraph at ~605-615)
- Test: `tests/test_clip.py` (`TestDelete`), `tests/test_handlers_mayapy.py` (`test_named_delete_measures_real_curve_removal`)

**Interfaces:**
- Consumes: `clipmath.channel_union(records) -> {"joints": [...], "weight_channels": [...], "root_position_used": bool}`; `doomed_record` has the same keys (all records are normalized).
- Produces: `delete_clip` result gains `"reaped_channels": List[str]` (short joint names / weight aliases / `"root_position"`), `[]` on a full teardown and when nothing was orphaned. `deleted_curves` on a partial delete can now be > 0.

- [ ] **Step 1: Write the failing headless test**

In `tests/test_clip.py::TestDelete`:

```python
    def test_a_named_delete_reaps_channels_no_survivor_declares(self, fake):
        # #730: idle keys mid, wave introduces tip, step keys mid again.
        # Deleting wave must remove tip's whole curves - they carry only
        # rest pins inside idle's and step's ranges - without touching a
        # single key of idle's or step's own mid channel.
        _author(fake, name="idle", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 30]}}])
        _author(fake, name="wave", keys=[
            {"time_s": 0.0, "rotations": {"tip": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"tip": [0, 0, 45]}}])
        _author(fake, name="step", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, -30]}}])
        mid_keys_before = dict(fake.keys.get("|root|mid.rotateZ", {}))

        out = clip.delete_clip({"root": "root", "name": "wave"})

        assert out["clips"] == ["idle", "step"]
        assert out["reaped_channels"] == ["tip"]
        # tip's curves are gone ENTIRELY, not just cut in wave's range
        assert not any(p.startswith("|root|mid|tip.") for p in fake.keys)
        assert out["deleted_curves"] >= 3   # tip's three rotate curves
        # the survivors' own keys are untouched
        assert dict(fake.keys.get("|root|mid.rotateZ", {})) == mid_keys_before
        assert any("no surviving clip declares" in w for w in out["warnings"])

    def test_a_named_delete_of_a_declared_shared_channel_reaps_nothing(self, fake):
        # mid is declared by the survivor too - nothing may be reaped.
        _author(fake, name="idle", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 30]}}])
        _author(fake, name="wave", keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [0, 0, 45]}}])
        out = clip.delete_clip({"root": "root", "name": "wave"})
        assert out["reaped_channels"] == []
        assert "|root|mid.rotateZ" in fake.keys
```

(`_author`'s default keys also key `root_position`; pass explicit `keys` as above so `root_position_used` stays False and does not muddy the union.)

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest "tests/test_clip.py::TestDelete" -q
```

Expected: FAIL — `KeyError: 'reaped_channels'` (or the tip-curves assertion).

- [ ] **Step 3: Implement the reap**

In `delete_clip`'s `kept` branch (clip.py:862), AFTER the existing `cutKey` loop and BEFORE `remaining = _anim_curves(...)`, insert:

```python
        # #730: the doomed clip's back-fill wrote rest pins for its own
        # channels into the SURVIVING clips' ranges. A channel no survivor
        # declares now carries only those pins - dead weight every take
        # would bake. Reap the WHOLE curve, but only for channels the
        # doomed record itself declared and no survivor does; a channel a
        # survivor still uses is never touched, range or no range.
        survivors = clipmath.channel_union(kept)
        by_short: Dict[str, List[str]] = {}
        for j in joints:
            by_short.setdefault(_short(j), []).append(j)
        orphan_plugs: List[str] = []
        reaped_channels: List[str] = []
        for short in doomed_record.get("joints", []):
            if short in survivors["joints"]:
                continue
            matches = by_short.get(short) or []
            if len(matches) != 1:
                continue  # vanished or ambiguous: never guess (_rot_plugs rule)
            orphan_plugs.extend("%s.%s" % (matches[0], a)
                                for a in ROTATE_ATTRS)
            reaped_channels.append(short)
        for alias in doomed_record.get("weight_channels", []):
            if alias in survivors["weight_channels"]:
                continue
            node = alias_map.get(alias)
            if node is None or isinstance(node, HandlerError):
                continue
            orphan_plugs.append("%s.%s" % (node, alias))
            reaped_channels.append(alias)
        if (doomed_record.get("root_position_used")
                and not survivors["root_position_used"]):
            orphan_plugs.extend("%s.%s" % (root_long, a)
                                for a in TRANSLATE_ATTRS)
            reaped_channels.append("root_position")
        orphan_curves = sorted({
            c for plug in orphan_plugs
            for c in cmds.listConnections(plug, source=True,
                                          destination=False,
                                          type="animCurve") or []})
        if orphan_curves:
            cmds.delete(*orphan_curves)
            warnings.append(
                "removed the whole curve(s) of %d channel(s) (%s) no "
                "surviving clip declares - they carried only rest pins "
                "inside the surviving clips' ranges (#730)"
                % (len(reaped_channels), ", ".join(reaped_channels)))
```

The existing `deleted_curves = len({...driven...} - {...remaining...})` diff directly below picks the reaped curves up — do not count them separately. In the `else` (full-teardown) branch and in the return dict, add the field: initialize `reaped_channels: List[str] = []` next to `deleted_curves = 0` (before the `if kept:`), and add `"reaped_channels": reaped_channels,` to the return dict.

Check the fake's `delete()` removes the curve AND its keys map (it does — `tests/test_clip.py` FakeCmds.delete drops both).

- [ ] **Step 4: Run headless clip tests**

```bash
python -m pytest tests/test_clip.py -q
```

Expected: PASS, including the two new tests.

- [ ] **Step 5: Update the mayapy measurement test to the new contract**

`tests/test_handlers_mayapy.py::test_named_delete_measures_real_curve_removal` (~line 4069) currently measures `deleted_curves == 0` on the two-clip scene (idle declares mt_mid, walk declares mt_tip; deleting idle leaves mt_mid declared by nobody). Under #730 the same delete now reaps mt_mid's curves. Rewrite the assertions to measure the NEW truth against raw curve state:

```python
        out = clip.delete_clip({"root": root, "name": "idle"})
        # #730: mt_mid is declared by no survivor - its whole curves go.
        assert out["reaped_channels"] == [prefix + "_mid"]
        assert out["deleted_curves"] >= 1
        assert not (cmds.listConnections(
            mid + ".rotateZ", source=True, destination=False,
            type="animCurve") or [])
        # walk's own channel is untouched: same key times as before.
        assert cmds.keyframe(tip + ".rotateZ", query=True) == tip_keys_before
```

(Capture `tip_keys_before = cmds.keyframe(tip + ".rotateZ", query=True)` before the delete; resolve `mid`/`tip` long names the way the surrounding tests do. Update the test's docstring: the "deleted_curves == 0 is structural" claim moves from "measurement" to "pre-#730 history".)

- [ ] **Step 6: Run the mayapy suite**

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\mayapy_t2.xml
```

Expected: PASS (same skip count as baseline). Read the XML for the count, not stdout.

- [ ] **Step 7: Update docs/protocol.md**

Row ~503: add `reaped_channels` to the delete_clip result. Replace the ~605-615 paragraph ("**`deleted_curves` on a NAMED, partial delete is structurally 0…**") with:

```markdown
**`deleted_curves` on a NAMED, partial delete counts two things.** Cutting
the doomed clip's own frame range essentially never empties a shared curve
(the surviving clips' keys and pins remain), BUT a channel that only the
deleted clip declared is reaped whole (#730): the rest pins the deleted
clip back-filled into the surviving clips' ranges are dead weight no take
declares, so its curves are removed entirely and reported in
`reaped_channels`. A partial delete of a clip whose channels are all
shared with survivors still honestly reports `deleted_curves: 0` and
`reaped_channels: []`.
```

- [ ] **Step 8: Check `evals/multi_take_live.py` for assertions the reap invalidates**

```bash
python -c "import io; s=io.open('evals/multi_take_live.py',encoding='utf-8').read(); import re; [print(l) for l in s.splitlines() if 'deleted_curves' in l or 'residual' in l or 'reap' in l]"
```

If the gate asserts `deleted_curves == 0` on a partial delete or asserts the residual pins EXIST (it filed #730, so it may document them), update those assertions to the new contract. If nothing matches, no change.

- [ ] **Step 9: Commit**

```bash
git add maya_plugin/handlers/clip.py docs/protocol.md tests/test_clip.py tests/test_handlers_mayapy.py evals/multi_take_live.py
git commit -m "fix(#730): named delete reaps whole curves no surviving clip declares"
```

---

### Task 3: #729 — fbxmaya reload only on a frame-rate change

**Files:**
- Create: `evals/fbx_fps_probe.py` (standalone mayapy probe, evidence only)
- Modify: `maya_plugin/handlers/export.py:690-719` (the reload block) + module top (state + helper)
- Test: `tests/test_export_fbx.py`, `tests/test_handlers_mayapy.py`
- Reference: `.superpowers/sdd/t718-10b-report.md` (crash-threshold measurements: running total of reload cycles per mayapy process — 2 clean, 3 crashes 3/3)

**Interfaces:**
- Produces: `export._fbx_reload_needed(loaded, cached_unit, scene_unit) -> bool` (module-level, pure) and module state `export._fbx_loaded_time_unit: Optional[str]` (the Maya time-unit string fbxmaya cached at its last genuine load; `None` = unknown). Tests reset it via `monkeypatch.setattr(export, "_fbx_loaded_time_unit", None)`.

- [ ] **Step 1: Probe whether the fps cache can be reset WITHOUT a reload (evidence, time-boxed)**

Create `evals/fbx_fps_probe.py` — a standalone mayapy script (fresh process, so its reload count is its own): initialize standalone, build a minimal one-joint clip scene at 24 fps via `clip.author_clip`, export animated once (this loads/reloads fbxmaya and caches 24), `delete_clip`, re-author at 30 fps, then for each candidate — `mel.eval('FBXResetExport')` (known-no control), `mel.eval('FBXProperty Export|IncludeGrp|Animation|ExtraGrp|UseSceneName -v false')`-style probes of `FBXProperties` output (dump `mel.eval('FBXProperties')` once and grep it for anything matching `Rate|Sampling|Time`), setting any discovered rate property to 30 — export WITHOUT the forced reload (temporarily monkeypatch `cmds.unloadPlugin` to a no-op inside the probe) and count baked keys via `fbxbytes.anim_facts`: 31 keys = the candidate works, 25 = it does not. Print a per-candidate verdict table. Run:

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe evals\fbx_fps_probe.py
```

Record the verdict table in `.superpowers/sdd/progress.md` and in the #729 ticket notes at task end. **Decision rule:** if a property candidate measures 31 keys, implement Step 3-B (property reset, delete the reload entirely); otherwise implement Step 3-A (cached-fps guard). 3-A is the default and is fully specified below; 3-B replaces the unload/reload pair with the measured property call at the same site, keeps the same tests, and additionally asserts zero `unloadPlugin` calls ever.

- [ ] **Step 2: Write the failing headless tests**

In `tests/test_export_fbx.py`:

```python
class TestFbxReloadGuard:
    def test_reload_decision_truth_table(self):
        # (loaded, cached, scene) -> reload?
        assert export._fbx_reload_needed(False, None, "ntsc") is False
        assert export._fbx_reload_needed(False, "film", "ntsc") is False
        assert export._fbx_reload_needed(True, None, "ntsc") is True
        assert export._fbx_reload_needed(True, "film", "ntsc") is True
        assert export._fbx_reload_needed(True, "ntsc", "ntsc") is False

    def test_a_static_export_never_unloads_the_plugin(self, monkeypatch, tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        cmds = FakeCmds()
        _install(monkeypatch, cmds, _facts([node]))
        export.export_fbx(_params(tmp_path))
        assert not any(c[0] == "unloadPlugin" for c in cmds.calls)

    def test_a_fresh_load_records_the_scene_time_unit(self, monkeypatch, tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        cmds = FakeCmds(plugin_loaded=False)
        _install(monkeypatch, cmds, _facts([node]))
        monkeypatch.setattr(export, "_fbx_loaded_time_unit", None)
        export.export_fbx(_params(tmp_path))
        assert export._fbx_loaded_time_unit == "ntsc"
```

Extend the existing `FakeCmds` in that file (do NOT build a new one):

```python
    def __init__(self, existing=("golem_C_pelvis",), load_plugin_raises=None,
                 plugin_loaded=True):
        ...existing body...
        self.plugin_loaded = plugin_loaded

    def pluginInfo(self, name, query=False, loaded=False):
        self.calls.append(("pluginInfo", name))
        return self.plugin_loaded

    def unloadPlugin(self, name, force=False):
        self.calls.append(("unloadPlugin", name))
        self.plugin_loaded = False

    def currentUnit(self, query=False, time=False):
        return "ntsc"
```

and make `loadPlugin` set `self.plugin_loaded = True` after recording.

- [ ] **Step 3: Run to verify failure**

```bash
python -m pytest tests/test_export_fbx.py::TestFbxReloadGuard -q
```

Expected: FAIL with `AttributeError: ... has no attribute '_fbx_reload_needed'`.

- [ ] **Step 4 (3-A): Implement the cached-fps guard**

At export.py module level (near the other constants):

```python
# #729: fbxmaya caches the scene's frame rate at plugin LOAD time (#695,
# measured), but force-unloading a native plugin before EVERY animated
# export corrupts the Windows heap under repetition - a mayapy process
# died in maya.standalone.uninitialize() at a running total of 3 reload
# cycles (2 measured clean; t718-10b-report.md). So the reload happens
# only when the scene's time unit differs from what the plugin cached at
# its last genuine load. Known residual risk, accepted on the ticket: if
# something OUTSIDE this module reloads fbxmaya while the scene sits at a
# different rate than this tracker recorded, the tracker is stale and one
# export can bake at the wrong rate; the gate's key-count check still
# refuses that file.
_fbx_loaded_time_unit = None


def _fbx_reload_needed(loaded, cached_unit, scene_unit):
    """Must fbxmaya be force-reloaded before an animated export?"""
    if not loaded:
        return False  # the load below is fresh and reads the current rate
    return cached_unit is None or cached_unit != scene_unit
```

Replace lines 690-719 (keep the big MEASURED comment, reworded to mention the guard):

```python
    global _fbx_loaded_time_unit
    if include_animation and _fbx_reload_needed(
            cmds.pluginInfo("fbxmaya", query=True, loaded=True),
            _fbx_loaded_time_unit,
            cmds.currentUnit(query=True, time=True)):
        try:
            # a refused unload (GUI Maya, FBX UI open) must not abort the
            # export - the fresh-load check below then leaves the tracker
            # alone, so the next animated export tries again.
            cmds.unloadPlugin("fbxmaya", force=True)
        except Exception:
            pass
    fresh = not cmds.pluginInfo("fbxmaya", query=True, loaded=True)
    try:
        cmds.loadPlugin("fbxmaya", quiet=True)
    except Exception as exc:
        raise HandlerError(
            "the fbxmaya plugin failed to load: %s" % exc,
            hint="the bundled FBX plugin lives in Maya's plug-ins directory; "
                 "check the Plug-in Manager")
    if fresh:
        # the plugin just read (and cached) the scene's CURRENT rate -
        # recorded for static loads too, so the tracker never claims a
        # rate the plugin did not actually cache.
        _fbx_loaded_time_unit = cmds.currentUnit(query=True, time=True)
```

Note the function signature keeps `export_fbx(params)` — the `global` goes at the top of the function body.

- [ ] **Step 5: Run headless**

```bash
python -m pytest tests/test_export_fbx.py -q
```

Expected: PASS (existing tests hold: `pluginInfo` defaults to loaded=True and `currentUnit` answers, so static-path tests see one extra recorded call at most).

- [ ] **Step 6: Add the in-suite repeat-loop proof and update the stale budget docstrings**

In `tests/test_handlers_mayapy.py::TestMultiTakeExportInMaya`, new test:

```python
    def test_repeated_same_fps_exports_neither_reload_nor_crash(self, tmp_path):
        """#729: six real animated exports at ONE fps in this shared
        process. Before the guard this was the measured teardown killer
        (running total of 3 fbxmaya reload cycles crashed
        maya.standalone.uninitialize(), 3/3); with the guard the six
        exports below cost ZERO additional reload cycles, measured by
        counting unloadPlugin calls. The suite finishing cleanly IS the
        teardown proof."""
        import maya.cmds as cmds
        from maya_plugin.handlers import clip, export

        base, root, idle, walk = self._two_clip_scene(cmds, "rp")
        unloads = []
        real_unload = cmds.unloadPlugin

        def counting_unload(*a, **kw):
            unloads.append(a)
            return real_unload(*a, **kw)

        cmds.unloadPlugin = counting_unload
        try:
            for i in range(6):
                path = str(tmp_path / ("r%d.fbx" % i)).replace("\\", "/")
                result = export.export_fbx({
                    "path": path, "metres_per_unit": 1.0,
                    "nodes": [base, root], "include_animation": True})
                assert result["animation"] is not None
        finally:
            cmds.unloadPlugin = real_unload
            clip.delete_clip({"root": root})
        # at most one reload (only if this process's tracker was stale
        # when the loop started); never one per export.
        assert len(unloads) <= 1
```

Then update the two stale budget docstrings to point at #729's fix (keep their measured history, mark it "pre-#729"): `test_the_real_gate_passes_a_two_clip_export` ("WHY THIS TEST IS A SINGLE CALL" — it can stay a single call; just note the budget constraint is lifted by the guard) and `test_a_named_delete_leaves_the_other_take_exportable` (the "one remaining reload cycle" budget note).

- [ ] **Step 7: Run the FULL mayapy suite twice (teardown crash is a process-END event)**

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\mayapy_t3a.xml; echo "exit=$LASTEXITCODE"
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\mayapy_t3b.xml; echo "exit=$LASTEXITCODE"
```

Expected: exit=0 both times (exit 127 = the heap crash came back), pass count = baseline + 1. The #695 fps-change test (`TestClipExportInMaya::test_the_measurements`) MUST still pass — it is the proof the guard still reloads when the rate actually changes.

- [ ] **Step 8: Commit**

```bash
git add maya_plugin/handlers/export.py tests/test_export_fbx.py tests/test_handlers_mayapy.py evals/fbx_fps_probe.py
git commit -m "fix(#729): fbxmaya force-reload only when the scene frame rate changed"
```

---

### Task 4: #732 — rest is the bind pose; posed warning only when truly posed away

**Files:**
- Modify: `maya_plugin/handlers/rigmath.py` (new pure function at the bottom)
- Modify: `maya_plugin/handlers/clip.py` (`_capture_rest` ~207; new `_bind_rotations`; author_clip capture loop ~398-408 and warning block ~410-436)
- Modify: `docs/protocol.md` (author_clip rest note, if it states "current pose")
- Test: `tests/test_rigmath.py`, `tests/test_clip.py`, `tests/test_handlers_mayapy.py`
- Reference: `.superpowers/sdd/progress.md` #718 Task 4 entry (why bind decode was deferred; supersede it)

**Interfaces:**
- Produces: `rigmath.bind_rotation_deg(xform16: List[float], joint_orient_deg: List[float], rotate_axis_deg: List[float], rotate_order: int) -> Optional[List[float]]` — the joint's `.rotate` euler (DEGREES, XYZ) recovered from a dagPose local `xformMatrix`, or `None` for a non-XYZ rotate order (`rotate_order != 0`; the fbxbytes `_rotation` precedent: refuse rather than silently mis-compose).
- Produces: `clip._bind_rotations(cmds, root_long, joints) -> Dict[str, Optional[List[float]]]` — short name → bind `.rotate` triple in UI angle units, `None` when undeterminable; `{}` when the rig has no dagPose. Tests monkeypatch this seam.
- Changes: `clip._capture_rest(cmds, plug, rest, value=None)` — when `value` is not None it is recorded instead of `getAttr(plug)` (still skipped if already recorded / already curve-driven).

- [ ] **Step 1: Write the failing rigmath tests**

In `tests/test_rigmath.py`:

```python
def _rx(d):
    r = math.radians(d); c, s = math.cos(r), math.sin(r)
    return [[1, 0, 0], [0, c, s], [0, -s, c]]

def _ry(d):
    r = math.radians(d); c, s = math.cos(r), math.sin(r)
    return [[c, 0, -s], [0, 1, 0], [s, 0, c]]

def _rz(d):
    r = math.radians(d); c, s = math.cos(r), math.sin(r)
    return [[c, s, 0], [-s, c, 0], [0, 0, 1]]

def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]

def _xyz(t):
    return _mul(_mul(_rx(t[0]), _ry(t[1])), _rz(t[2]))

def _xform16(rot3, translate=(1.0, 2.0, 3.0), scale=1.0):
    m = [[rot3[i][j] * scale for j in range(3)] + [0.0] for i in range(3)]
    m.append([translate[0], translate[1], translate[2], 1.0])
    return [v for row in m for v in row]


class TestBindRotationDeg:
    def test_identity(self):
        out = rigmath.bind_rotation_deg(_xform16(_xyz([0, 0, 0])),
                                        [0, 0, 0], [0, 0, 0], 0)
        assert all(abs(v) < 1e-9 for v in out)

    def test_pure_rotate_no_orient(self):
        out = rigmath.bind_rotation_deg(_xform16(_xyz([10, 20, 30])),
                                        [0, 0, 0], [0, 0, 0], 0)
        assert all(abs(a - b) < 1e-6 for a, b in zip(out, [10, 20, 30]))

    def test_joint_orient_alone_reads_zero_rotate(self):
        # the create_skeleton shape: orientation lives in jointOrient, the
        # rotate channel is zero at bind.
        jo = [0, -35, 12]
        out = rigmath.bind_rotation_deg(_xform16(_xyz(jo)), jo, [0, 0, 0], 0)
        assert all(abs(v) < 1e-6 for v in out)

    def test_full_composition_round_trips(self):
        # M_rot = RA . R . JO (row vectors); recover R.
        ra, r, jo = [5, 0, 0], [10, 20, 30], [0, -35, 12]
        rot = _mul(_mul(_xyz(ra), _xyz(r)), _xyz(jo))
        out = rigmath.bind_rotation_deg(_xform16(rot), jo, ra, 0)
        assert all(abs(a - b) < 1e-6 for a, b in zip(out, r))

    def test_uniform_scale_is_normalized_out(self):
        out = rigmath.bind_rotation_deg(
            _xform16(_xyz([10, 20, 30]), scale=2.5), [0, 0, 0], [0, 0, 0], 0)
        assert all(abs(a - b) < 1e-6 for a, b in zip(out, [10, 20, 30]))

    def test_non_xyz_rotate_order_refuses(self):
        assert rigmath.bind_rotation_deg(_xform16(_xyz([10, 0, 0])),
                                         [0, 0, 0], [0, 0, 0], 3) is None
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_rigmath.py::TestBindRotationDeg -q
```

Expected: FAIL with `AttributeError: ... 'bind_rotation_deg'`.

- [ ] **Step 3: Implement `bind_rotation_deg` in rigmath.py**

```python
def _rot3_axis(axis: str, deg: float):
    """Row-vector rotation matrix about one axis (Maya's convention:
    row-major matrices, v' = v . M)."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    if axis == "x":
        return [[1.0, 0.0, 0.0], [0.0, c, s], [0.0, -s, c]]
    if axis == "y":
        return [[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]]
    return [[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]


def _mat3_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def _euler_xyz_deg(m) -> List[float]:
    """Euler XYZ (degrees) of a row-vector rotation matrix M = Rx.Ry.Rz."""
    sy = -m[0][2]
    cy = math.hypot(m[0][0], m[0][1])
    if cy < 1e-9:  # gimbal: pick rz = 0
        return [math.degrees(math.atan2(-m[2][1], m[1][1])),
                math.degrees(math.atan2(sy, cy)), 0.0]
    return [math.degrees(math.atan2(m[1][2], m[2][2])),
            math.degrees(math.atan2(sy, cy)),
            math.degrees(math.atan2(m[0][1], m[0][0]))]


def bind_rotation_deg(xform16: List[float], joint_orient_deg: List[float],
                      rotate_axis_deg: List[float],
                      rotate_order: int) -> Optional[List[float]]:
    """The `.rotate` euler (DEGREES, XYZ) stored inside a dagPose local
    xformMatrix, with jointOrient and rotateAxis stripped (#732).

    A joint's local rotation composes as Rot = RA . R . JO in Maya's
    row-vector convention, so R = RA^-1 . Rot . JO^-1; both strippers are
    orthonormal, so inverse = transpose. Only the default XYZ rotate order
    (0) is composed - anything else returns None rather than guessing
    (the fbxbytes._rotation precedent: a wrong assumption would record a
    wrong rest value silently)."""
    if rotate_order != 0:
        return None
    rows = [[float(xform16[i * 4 + j]) for j in range(3)] for i in range(3)]
    normalized = []
    for row in rows:
        norm = math.sqrt(sum(v * v for v in row))
        if norm < 1e-12:
            return None
        normalized.append([v / norm for v in row])

    def _xyz(t):
        return _mat3_mul(_mat3_mul(_rot3_axis("x", t[0]),
                                   _rot3_axis("y", t[1])),
                         _rot3_axis("z", t[2]))

    def _t(m):
        return [[m[j][i] for j in range(3)] for i in range(3)]

    r = _mat3_mul(_mat3_mul(_t(_xyz(rotate_axis_deg)), normalized),
                  _t(_xyz(joint_orient_deg)))
    return _euler_xyz_deg(r)
```

(Add `Optional` to rigmath's typing imports if absent. If the round-trip test disagrees on a sign, the test compositions are the contract — fix the implementation, not the test.)

- [ ] **Step 4: Run rigmath tests**

```bash
python -m pytest tests/test_rigmath.py -q
```

Expected: PASS.

- [ ] **Step 5: Write the failing clip.py headless tests**

In `tests/test_clip.py` (new class near `TestSelfContainedTakes`; also UPDATE the existing `test_a_posed_rig_warns_that_rest_is_not_the_bind_pose` at ~564 to the new summarized no-bind-info message — same trigger, new text, see Step 6's messages):

```python
class TestBindPoseRest:
    def test_rest_captures_the_bind_rotation_when_known(self, fake, monkeypatch):
        # an "imported rig" whose bind pose carries rotation: current pose
        # EQUALS bind, so no warning, and rest records the bind value.
        monkeypatch.setattr(clip, "_bind_rotations",
                            lambda cmds, root, joints:
                            {"mid": [10.0, 0.0, 0.0]})
        fake.attrs["|root|mid.rotateX"] = 10.0
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [10, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [40, 0, 0]}}])
        rest = json.loads(fake.string_attrs["|root"]["mcp_clip_rest"])
        assert rest["mid.rotateX"] == 10.0
        assert not any("posed" in w for w in out["warnings"])

    def test_posed_away_from_a_known_bind_warns_and_pins_at_bind(
            self, fake, monkeypatch):
        monkeypatch.setattr(clip, "_bind_rotations",
                            lambda cmds, root, joints:
                            {"mid": [0.0, 0.0, 0.0]})
        fake.attrs["|root|mid.rotateX"] = 25.0   # posed away from bind
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [40, 0, 0]}}])
        rest = json.loads(fake.string_attrs["|root"]["mcp_clip_rest"])
        assert rest["mid.rotateX"] == 0.0        # BIND, not the posed 25
        assert any("posed away from the bind pose" in w
                   for w in out["warnings"])

    def test_unknown_bind_falls_back_to_current_capture(self, fake):
        # FakeCmds.dagPose returns [] -> _bind_rotations returns {} -> the
        # pre-#732 behavior: capture current, warn (summarized) on non-zero.
        fake.attrs["|root|mid.rotateX"] = 25.0
        out = _author(fake, keys=[
            {"time_s": 0.0, "rotations": {"mid": [0, 0, 0]}},
            {"time_s": 1.0, "rotations": {"mid": [40, 0, 0]}}])
        rest = json.loads(fake.string_attrs["|root"]["mcp_clip_rest"])
        assert rest["mid.rotateX"] == 25.0
        assert any("no readable bind pose" in w for w in out["warnings"])
```

- [ ] **Step 6: Implement the clip.py side**

New reader (below `_rest_map`), using `rigmath` (clip.py must import it: `from . import clipmath, rigmath, ...` — check the existing import line):

```python
def _bind_rotations(cmds, root_long: str,
                    joints: List[str]) -> Dict[str, Optional[List[float]]]:
    """short joint name -> the BIND pose's `.rotate` triple (UI angle
    units), or None when it cannot be determined for that joint. {} when
    nothing is bound (no dagPose). Reads the SAME pose node delete_clip
    restores (#732)."""
    poses = cmds.dagPose(root_long, query=True, bindPose=True) or []
    if not poses:
        return {}
    pose = poses[0]
    out: Dict[str, Optional[List[float]]] = {}
    for j in joints:
        out[_short(j)] = None
        try:
            plugs = cmds.listConnections(j + ".message", source=False,
                                         destination=True, plugs=True,
                                         type="dagPose") or []
            idx = None
            for p in plugs:
                node, attr = p.split(".", 1)
                if node == pose and attr.startswith("members["):
                    idx = int(attr[len("members["):-1])
                    break
            if idx is None:
                continue
            xform = list(cmds.getAttr("%s.xformMatrix[%d]" % (pose, idx)))
            orient = [units.ui_to_degrees(cmds, v)
                      for v in cmds.getAttr(j + ".jointOrient")[0]]
            axis = [units.ui_to_degrees(cmds, v)
                    for v in cmds.getAttr(j + ".rotateAxis")[0]]
            deg = rigmath.bind_rotation_deg(
                xform, orient, axis, int(cmds.getAttr(j + ".rotateOrder")))
            if deg is not None:
                out[_short(j)] = [units.degrees_to_ui(cmds, v) for v in deg]
        except Exception:
            pass  # unreadable entry -> current-pose fallback for this joint
    return out
```

(Verify `units.ui_to_degrees` exists with that name — grep `def ui_to_degrees` in `maya_plugin/handlers/units.py`; if the function is named differently, use the real name. `getAttr` on compound attrs returns `[(x, y, z)]`.)

`_capture_rest` gains the value override:

```python
def _capture_rest(cmds, plug: str, rest: Dict[str, float],
                  value: Optional[float] = None) -> None:
    """Record a channel's rest value the moment it becomes curve-driven.
    ...existing docstring...
    `value` overrides the current-pose read: the BIND rotation when the
    dagPose decomposition knows it (#732)."""
    key = _rest_key(plug)
    if key in rest:
        return
    if cmds.listConnections(plug, source=True, destination=False,
                            type="animCurve"):
        return
    rest[key] = float(cmds.getAttr(plug)) if value is None else float(value)
```

In `author_clip`, before the capture loop (~line 398) add `bind = _bind_rotations(cmds, root_long, joints)`, and change the rotation-capture loop:

```python
    for short in mine["joints"]:
        triple = bind.get(short)
        for plug, bind_v in zip(_rot_plugs(short),
                                triple if triple is not None
                                else (None, None, None)):
            _capture_rest(cmds, plug, rest, value=bind_v)
```

(`_rot_plugs` yields in `ROTATE_ATTRS` order, matching the triple's order. `_rot_plugs` can return `[]`; `zip` handles it.)

Replace the warning block (current lines 410-436, the `#718 review Fix 4` comment through the `warnings.append(...)`) with:

```python
    # #732: rest is the BIND pose where the dagPose can be decomposed
    # (rigmath.bind_rotation_deg strips jointOrient/rotateAxis). The
    # warning now fires only when the rig is measurably POSED AWAY from
    # that bind pose at first capture - an imported rig whose bind pose
    # legitimately carries rotation stays silent. Joints with no readable
    # bind entry keep the pre-#732 behavior (capture current, warn on
    # non-zero, since a create_skeleton rig reads zero at rest) - both
    # warnings are summarized, never one line per joint. Root translation
    # is excluded (a rig legitimately sits anywhere) and weight channels
    # are excluded (recorded 0.0 by rule, never captured).
    newly_captured = {k: v for k, v in rest.items() if k not in rest_before}
    posed_away: List[str] = []
    unknown_bind: List[str] = []
    for short in sorted({k.rsplit(".", 1)[0] for k in newly_captured
                         if k.rsplit(".", 1)[1] in ROTATE_ATTRS}):
        plugs = _rot_plugs(short)
        if not plugs:
            continue
        triple = bind.get(short)
        if triple is not None:
            current = [float(cmds.getAttr(p)) for p in plugs]
            if any(abs(c - b) > 1e-4 for c, b in zip(current, triple)):
                posed_away.append(short)
        elif any(abs(newly_captured.get("%s.%s" % (short, a), 0.0)) > 1e-9
                 for a in ROTATE_ATTRS):
            unknown_bind.append(short)
    if posed_away:
        warnings.append(
            "%d joint(s) are posed away from the bind pose (e.g. %s) - "
            "rest pins use the BIND pose, so boundary frames will not hold "
            "the current pose" % (len(posed_away),
                                  ", ".join(posed_away[:3])))
    if unknown_bind:
        warnings.append(
            "rest was captured from this rig's CURRENT pose for %d "
            "joint(s) with no readable bind pose (e.g. %s) - a non-zero "
            "value here usually means the rig was posed, e.g. via "
            "pose_skeleton, before its first clip"
            % (len(unknown_bind), ", ".join(unknown_bind[:3])))
```

- [ ] **Step 7: Run the headless suites**

```bash
python -m pytest tests/test_clip.py tests/test_rigmath.py -q
```

Expected: PASS, including the updated ~564 test (its expected message is now the `unknown_bind` one).

- [ ] **Step 8: Write and run the mayapy proof**

New class in `tests/test_handlers_mayapy.py` (near `TestClipExportInMaya`):

```python
class TestBindPoseRestInMaya:
    """#732 against real dagPose data. create_skeleton auto-orients local
    X down the bone, so jointOrient is NON-zero and rotate is zero at
    bind - decomposition must recover ~0. A hand-built rig with non-zero
    rotate at bind is the imported-rig case the warning used to spam."""

    def test_a_posed_create_skeleton_rig_pins_at_bind_and_warns(self, tmp_path):
        import json
        import maya.cmds as cmds
        from maya_plugin.handlers import clip, rigging

        base = cmds.ls(cmds.polyCube(name="bp_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        skel = rigging.create_skeleton({"joints": [
            {"name": "bp_root", "position": [0.0, -1.0, 0.0]},
            {"name": "bp_mid", "position": [0.0, 0.0, 0.0],
             "parent": "bp_root"},
            {"name": "bp_tip", "position": [0.0, 1.0, 0.0],
             "parent": "bp_mid"}]})
        rigging.bind_skin({"mesh": base, "root": skel["root"]})
        rigging.pose_skeleton({"root": skel["root"],
                               "rotations": {"bp_mid": [25, 0, 0]}})
        out = clip.author_clip({
            "root": skel["root"], "name": "idle", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"bp_mid": [0, 0, 0]}},
                {"time_s": 1.0, "rotations": {"bp_mid": [0, 0, 30]}}]})
        rest = json.loads(cmds.getAttr(skel["root"] + ".mcp_clip_rest"))
        assert abs(rest["bp_mid.rotateX"]) < 1e-3   # BIND, not 25
        assert any("posed away from the bind pose" in w
                   for w in out["warnings"])
        clip.delete_clip({"root": skel["root"]})

    def test_a_bind_pose_with_rotation_does_not_warn(self, tmp_path):
        import json
        import maya.cmds as cmds
        from maya_plugin.handlers import clip, rigging

        cmds.select(clear=True)
        r = cmds.joint(name="ir_root", position=[0, -1, 0])
        m = cmds.joint(name="ir_mid", position=[0, 0, 0])
        cmds.joint(name="ir_tip", position=[0, 1, 0])
        cmds.setAttr(m + ".rotateX", 15.0)   # bind pose WITH rotation
        base = cmds.ls(cmds.polyCube(name="ir_base", height=2,
                                     subdivisionsHeight=4)[0], long=True)[0]
        root_long = cmds.ls(r, long=True)[0]
        rigging.bind_skin({"mesh": base, "root": root_long})
        out = clip.author_clip({
            "root": root_long, "name": "idle", "fps": 30,
            "keys": [
                {"time_s": 0.0, "rotations": {"ir_mid": [15, 0, 0]}},
                {"time_s": 1.0, "rotations": {"ir_mid": [45, 0, 0]}}]})
        rest = json.loads(cmds.getAttr(root_long + ".mcp_clip_rest"))
        assert abs(rest["ir_mid.rotateX"] - 15.0) < 1e-3
        assert not any("posed" in w for w in out["warnings"])
        clip.delete_clip({"root": root_long})
```

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -k BindPoseRest -q --junitxml=$env:TEMP\mayapy_t4.xml
```

Expected: 2 passed. If the decomposition disagrees with real Maya here, the REAL Maya numbers are the contract — fix rigmath's composition order and re-run the headless suite (its compositions must be corrected to match, they encode the same convention).

- [ ] **Step 9: Docs + ledger**

- `docs/protocol.md`: wherever author_clip's rest capture is described as "current pose", state: rest is the bind pose when a dagPose exists and decomposes (XYZ rotate order); current pose otherwise, with the summarized warning.
- `.superpowers/sdd/progress.md`: append a #732 entry superseding the #718 Task 4 accepted-deviation note.

- [ ] **Step 10: Full suites, then commit**

```bash
python -m pytest tests -q --junitxml=$env:TEMP\headless_t4.xml
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\mayapy_t4full.xml
git add maya_plugin/handlers/rigmath.py maya_plugin/handlers/clip.py docs/protocol.md .superpowers/sdd/progress.md tests/test_rigmath.py tests/test_clip.py tests/test_handlers_mayapy.py
git commit -m "fix(#732): rest is the bind pose; posed warning fires only when truly posed away"
```

---

### Task 5: #721 part 2 — Arnold IPR session hygiene

**Files:**
- Modify: `maya_plugin/handlers/session.py` (new `stop_idle_ipr`)
- Modify: `maya_plugin/handlers/render.py` (`_run_shots`, ~686; add `session` to its `from . import` line)
- Modify: `maya_plugin/handlers/clip.py` (`author_clip` ~327, `preview_clip`)
- Create: `evals/clip_hygiene_live.py`
- Test: `tests/test_session.py`, `tests/test_clip.py`
- NO dispatcher change: the "can the dispatcher interrupt a wedged command" question in the ticket is already answered by design — `dispatcher.py::_busy_hint`'s docstring (lines 204-246) documents why it cannot (the worker blocks synchronously in `executeInMainThreadWithResult`) and the hint escalates to "restart Maya" past `_LIKELY_WEDGED_S`. Record that in the ticket notes at closeout; do not add an interrupt.

**Interfaces:**
- Produces: `session.stop_idle_ipr(cmds) -> List[str]` — human-readable actions taken (`[]` in batch mode, when mtoa is absent, or when nothing was open). Callers append these to their `warnings` with context.

- [ ] **Step 1: LIVE PROBE — measure what actually stops the Arnold RenderView (agent Maya, MCP tools)**

Use the agent-launched Maya via the `mcp__maya__*` tools (NOT `maya9879`, the user's). With `maya_execute_python`:

1. `cmds.loadPlugin("mtoa", quiet=True)`; report `cmds.pluginInfo("mtoa", q=True, loaded=True)`.
2. Open the view: try `cmds.arnoldRenderView()` and if that raises, `mel.eval("arnoldRenderView")`. Report `cmds.lsUI(windows=True)` and specifically `cmds.window("ArnoldRenderView", exists=True)`.
3. Try the stop candidates IN ORDER, reporting after each: (a) `cmds.arnoldRenderView(opt=("Run IPR", "false"))` (also try `mode="stop"` / `option=...` — the mtoa signature varies by version; `help(cmds.arnoldRenderView)` output is the authority), (b) `cmds.deleteUI(<measured window name>)` if the window still exists, (c) `cmds.arnoldIpr(mode="stop")` for the legacy render-view IPR.
4. Record: the real window name, which candidate calls exist, which actually close/stop it, and whether a closed-then-reopened view resumes IPR. Write the findings into `.superpowers/sdd/progress.md` (a "#721p2 probe" entry).

If the maya MCP server is down: STOP and tell the user (CLAUDE.md rule) — do not fall back to driving Maya another way.

- [ ] **Step 2: Write the failing headless tests**

In `tests/test_session.py`:

```python
class RecordingIprCmds:
    """Only what stop_idle_ipr touches; every surface is recorded."""
    def __init__(self, batch=False, mtoa=True, window=True):
        self.batch, self.mtoa, self.window_open = batch, mtoa, window
        self.calls = []

    def about(self, batch=False):
        return self.batch

    def pluginInfo(self, name, query=False, loaded=False):
        return self.mtoa

    def arnoldRenderView(self, **kw):
        self.calls.append(("arnoldRenderView", kw))

    def window(self, name, exists=False):
        return self.window_open

    def deleteUI(self, name):
        self.calls.append(("deleteUI", name))
        self.window_open = False


class TestStopIdleIpr:
    def test_batch_mode_does_nothing(self):
        cmds = RecordingIprCmds(batch=True)
        assert session.stop_idle_ipr(cmds) == []
        assert cmds.calls == []

    def test_no_mtoa_no_window_does_nothing(self):
        assert session.stop_idle_ipr(
            RecordingIprCmds(mtoa=False, window=False)) == []

    def test_an_open_view_is_stopped_and_closed(self):
        cmds = RecordingIprCmds()
        actions = session.stop_idle_ipr(cmds)
        assert actions   # something was done, and it is reported
        assert ("deleteUI", "ArnoldRenderView") in cmds.calls

    def test_a_fake_without_ui_surfaces_degrades_to_noop(self):
        class Bare:
            pass
        assert session.stop_idle_ipr(Bare()) == []
```

In `tests/test_clip.py` (inside `TestAuthor`):

```python
    def test_author_clip_stops_an_idle_ipr_and_warns(self, fake, monkeypatch):
        monkeypatch.setattr(clip.session, "stop_idle_ipr",
                            lambda cmds: ["closed the Arnold RenderView"])
        out = _author(fake)
        assert any("closed the Arnold RenderView" in w and "#721" in w
                   for w in out["warnings"])
```

- [ ] **Step 3: Run to verify failure**

```bash
python -m pytest tests/test_session.py::TestStopIdleIpr tests/test_clip.py::TestAuthor -q
```

Expected: FAIL with `AttributeError: ... 'stop_idle_ipr'`.

- [ ] **Step 4: Implement `session.stop_idle_ipr`**

At the bottom of session.py (adjust the two mtoa calls to whatever Step 1 MEASURED — the shape below is the candidate set, every layer best-effort):

```python
def stop_idle_ipr(cmds) -> list:
    """Best-effort: stop any Arnold IPR session and close the Arnold
    RenderView window; returns what was done, [] when there was nothing
    to do. #721: an idle IPR view re-renders on EVERY scene mutation -
    the first keyframe call after a render_scene hero pass wedged Maya
    for 30+ minutes. render tools call this after finishing; keyframe
    tools call it before starting. Interactive sessions only - batch has
    no UI to leak."""
    actions = []
    try:
        if cmds.about(batch=True):
            return actions
    except Exception:
        return actions  # not a real cmds (headless fake): nothing to do
    try:
        if cmds.pluginInfo("mtoa", query=True, loaded=True):
            try:
                cmds.arnoldRenderView(opt=("Run IPR", "false"))
                actions.append("stopped the Arnold RenderView IPR")
            except Exception:
                pass
    except Exception:
        pass
    try:
        if cmds.window("ArnoldRenderView", exists=True):
            cmds.deleteUI("ArnoldRenderView")
            actions.append("closed the Arnold RenderView window")
    except Exception:
        pass
    return actions
```

- [ ] **Step 5: Wire the call sites**

`render.py`: add `session` to the `from . import capture, lighting, naming` line. In `_run_shots`, the render result is returned from inside the `try:` — restructure minimally so hygiene can reach the caller: bind the success result to a local (`out = {...}` instead of `return {...}`), and in the `finally:` block's END append:

```python
        hygiene = session.stop_idle_ipr(cmds)
```

(declare `hygiene: List[str] = []` before the `try:`), then after the try/finally:

```python
    out.setdefault("warnings", []).extend(
        a + " after rendering - an idle IPR re-renders on every scene "
        "mutation and can wedge later keyframe work (#721)"
        for a in hygiene)
    return out
```

(If `_run_shots` raises, the finally still stops the IPR — that is the point; the warning is only deliverable on success.)

`clip.py::author_clip`, right after `warnings: List[str] = []` (~line 327):

```python
    for action in session.stop_idle_ipr(cmds):
        warnings.append(
            action + " before keyframe work - an idle IPR re-renders on "
            "every scene mutation and can wedge a keyframe call for "
            "minutes (#721)")
```

`clip.py::preview_clip`: same loop immediately after its `records`/`meta` validation, appending into its warnings list (check how preview_clip reports warnings; if it has none, add `warnings` to its result dict and document in protocol.md).

- [ ] **Step 6: Run headless**

```bash
python -m pytest tests/test_session.py tests/test_clip.py tests/test_render.py -q
```

Expected: PASS. (`test_render.py`'s fakes lack `about` → `stop_idle_ipr` degrades to `[]`; if a fake explodes differently, extend THAT fake with a no-op `about`, never weaken the helper.)

- [ ] **Step 7: Write and run the live gate**

Create `evals/clip_hygiene_live.py` (follow `evals/live_call.py`'s direct-TCP client pattern; port from `MAYA_MCP_PORT`, default 9877 — confirm the AGENT Maya's port and pid first):

1. `render_scene` one angle, `renderer="arnold"`, low resolution, on a fresh cube — assert the result's warnings mention the hygiene action OR that `execute_python cmds.window("ArnoldRenderView", exists=True)` is False afterwards.
2. `execute_python` to open the ARV deliberately (the probe's measured open call), then `create_skeleton` (two joints) + `author_clip` (three keys, one channel) with default timeout — assert it returns within the default 120 s AND its warnings carry the "#721" hygiene line.
3. Clean up: `delete_clip`, delete the objects, close any view.

Run it, report elapsed times and the warning text verbatim. This is the measured re-run of the #713 wedge scenario.

- [ ] **Step 8: Docs + commit**

`docs/protocol.md`: note on render_scene/render_sheet and author_clip/preview_clip that idle Arnold IPR sessions are stopped and reported in `warnings` (#721).

```bash
git add maya_plugin/handlers/session.py maya_plugin/handlers/render.py maya_plugin/handlers/clip.py docs/protocol.md tests/test_session.py tests/test_clip.py evals/clip_hygiene_live.py
git commit -m "fix(#721): stop idle Arnold IPR after renders and before keyframe work"
```

---

### Task 6: Whole-branch verification

- [ ] **Step 1: Full headless suite**

```bash
python -m pytest tests -q --junitxml=$env:TEMP\headless_final.xml
```

Expected: baseline (1481 + 1 skip at branch time) plus every test this plan added; 0 failures. Read the XML.

- [ ] **Step 2: Full mayapy suite, twice** (teardown crash regression check for #729)

```bash
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\mayapy_final.xml; echo "exit=$LASTEXITCODE"
E:\Autodesk\Maya2027\bin\mayapy.exe -m pytest tests/test_handlers_mayapy.py -q --junitxml=$env:TEMP\mayapy_final2.xml; echo "exit=$LASTEXITCODE"
```

Expected: exit=0 both runs.

- [ ] **Step 3: Live gates against the agent Maya**

Run `evals/multi_take_live.py` (the #718 gate — exercises author/delete/export end to end; #730/#731 touched its territory) and `evals/clip_hygiene_live.py` (#721). Report measured pass counts. If `evals/clip_live.py` is cheap (read its header), run it too.

- [ ] **Step 4: Docs coherence pass**

Re-read the diff of `docs/protocol.md` against every behavior change: delete_clip (`reaped_channels`, deleted_curves paragraph), author_clip (bind-pose rest, summarized warnings, IPR hygiene warning), preview_clip (warnings, if added), render tools (IPR note), export (nothing user-visible for #729/#731 beyond honesty — mention the reload guard under export_fbx's notes if the file documents the reload today).

- [ ] **Step 5: Commit anything the pass caught**

```bash
git add -A -- docs tests maya_plugin evals/clip_hygiene_live.py evals/fbx_fps_probe.py
git commit -m "test: whole-branch verification for the clip robustness batch"
```

(Nothing under `evals/golem_rerun_665/` may appear in `git status` staging — if it does, unstage it.)

---

### Task 7: Review, merge, deploy, closeout

- [ ] **Step 1:** Use superpowers:requesting-code-review on the branch diff (`git diff main...fix-clip-robustness`); fix what it finds (superpowers:receiving-code-review), re-run affected suites.
- [ ] **Step 2:** Use superpowers:finishing-a-development-branch — merge `fix-clip-robustness` to `main` (repo precedent: merge locally, delete the branch), do NOT touch `shards-delivery`.
- [ ] **Step 3:** Deploy the plugin copy: `python maya_plugin/install.py` (it refuses downgrades since #755); verify the stamp/digest it prints. Note for the final report: running Mayas hold the OLD modules until restart; `ping`'s `restart_required` tells the truth.
- [ ] **Step 4:** Redmine closeout — one `update_issue` per ticket with measured notes:
  - #731 → Resolved (both sites, tests).
  - #730 → Resolved (reap rule, `reaped_channels`, docs; note the re-author-with-fewer-channels variant of the residue was observed and deliberately left out of scope).
  - #729 → Resolved (probe verdict table; guard or property fix; the in-suite 6x proof and the two clean full-suite teardowns; stale docstring budgets updated).
  - #732 → Resolved (bind decomposition, XYZ-only refusal rule, mayapy proofs).
  - #721 → Resolved (part 1 was cb8e794; part 2: hygiene helper + call sites + live gate timings; dispatcher-interrupt bullet answered by design — cite `dispatcher.py::_busy_hint`'s docstring).
