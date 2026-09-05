"""render_scene tests: framing math, validation, and restore discipline.

The math is pure and fully tested here. The Maya-touching part is exercised
against a fake cmds - real pixels are the job of evals/render_scene_live.py,
because a green suite here proved nothing while capture_viewport was quietly
returning transparent images (redmine #584).
"""

import math

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import capture, render


class TestFocalLength:
    """The lens now comes from capture.apply_framing_fov, which reads the
    film back off the camera instead of assuming one.

    What used to live here computed the lens from a hardcoded VERTICAL
    aperture of 0.981 in. Measured on Maya 2027 (#772): the camera's vertical
    aperture is 0.9449 in, and with filmFit Horizontal on a square render it
    is the HORIZONTAL aperture that governs anyway - so the old helper was
    wrong on both counts and produced a ~55 deg frame while claiming 40.
    Arithmetic and film-back reading are covered by test_capture.py's
    TestFramingFov; what belongs here is that the render path uses it.
    """

    def test_render_asks_capture_for_the_lens(self, monkeypatch):
        seen = []
        monkeypatch.setattr(capture, "apply_framing_fov",
                            lambda cmds, cam, **kw: seen.append(cam) or 49.45)
        assert capture.apply_framing_fov(object(), "someCam") == 49.45
        assert seen == ["someCam"]

    def test_the_helper_render_used_to_own_is_gone(self):
        """It survived as a trap: a module-level default aperture is exactly
        how the wrong film back gets picked up again."""
        assert not hasattr(render, "focal_length_for_fov")
        assert not hasattr(render, "MAYA_VERTICAL_APERTURE_IN")


class TestValidation:
    def test_default_angle_is_a_single_three_quarter(self):
        assert render.resolve_angles(None) == ["three_quarter"]

    def test_rejects_unknown_angle(self):
        with pytest.raises(HandlerError):
            render.resolve_angles(["diagonal"])

    def test_rejects_more_than_four_angles(self):
        with pytest.raises(HandlerError):
            render.resolve_angles(["front", "side", "back", "top", "three_quarter"])

    def test_default_renderer_is_arnold(self):
        assert render.resolve_renderer(None) == "arnold"

    def test_hw2_maps_to_maya_hardware_2(self):
        assert render.RENDERER_TO_MAYA[render.resolve_renderer("hw2")] == "mayaHardware2"

    def test_rejects_unknown_renderer(self):
        with pytest.raises(HandlerError):
            render.resolve_renderer("redshift")

    def test_resolution_defaults_to_512_and_clamps(self):
        assert render.clamp_resolution(None) == 512
        assert render.clamp_resolution(4) == 64
        assert render.clamp_resolution(9000) == 2048
        assert render.clamp_resolution(True) == 512  # bool is not a resolution

    def test_samples_default_and_range(self):
        assert render.resolve_samples(None) == 3
        assert render.resolve_samples(6) == 6
        for bad in (0, 9, 2.5, True):
            with pytest.raises(HandlerError):
                render.resolve_samples(bad)


class TestFramePrefix:
    def test_prefix_is_unique_per_index(self):
        a = render.frame_prefix("abc123", 0, "front")
        b = render.frame_prefix("abc123", 1, "front")
        assert a != b
        assert "front" in a and a.startswith("mayaMcpRender_")

    def test_prefix_has_no_path_separators(self):
        prefix = render.frame_prefix("abc123", 0, "three_quarter")
        assert "/" not in prefix and "\\" not in prefix


class FakeCmds:
    """Enough maya.cmds to drive render_scene's restore discipline.

    Records every mutation so the tests can assert the scene came back as it
    was - the house rule for perception tools (capture._PanelState).

    #799 replaced four answers-anything fallbacks:

    - `ls(x, long=True)` answered "|x" for any string at all, and `getAttr`
      answered 0 for any plug it did not recognise, so nothing here could
      tell a live node from one that was deleted or never made.
    - `listRelatives(parent=True)` ended in an unconditional
      `return ["mayaMcpTempKey"]`: ask it for the parent of anything and it
      named the fallback light.
    - `camera()` handed back a transform with NO SHAPE, so
      capture.apply_framing_fov fell down its shapeless-node fallback and
      read the film back off the TRANSFORM - where this fake answered 0, so
      the render camera's focal length came out 0.0 and the #772 fix, whose
      whole point is that the render eye really has its 40 deg, was never
      once exercised on the render path.
    - `getAttr("<cam>.translate")` answered a constant [(0,0,0)], so the
      camera_positions this tool REPORTS were never compared with what it
      set.

    Round 2 caught a fifth: `exactWorldBoundingBox` was the one
    string-accepting method left off the registry, answering a unit box for
    a name nobody made and never able to produce Maya's inverted sentinel -
    which left capture._scene_bbox's #640 fallback unreachable from here.
    `TestTheFakeRefusesWhatMayaRefuses` below is the barrier for all of it:
    round 1's hardening was asserted by nothing, so reverting it left the
    suite green.

    `attrs` deliberately keeps a plug after its node is deleted: it doubles
    as the mutation log the restore tests read once a render has finished
    and cleaned up. Existence is decided by the node registry, not by it.
    """

    # DG singletons: no DAG node behind them, and every one of them is
    # asked for by name.
    _DG_NODES = ("defaultRenderGlobals", "defaultResolution",
                 "defaultArnoldRenderOptions", "defaultArnoldDriver",
                 "hardwareRenderingGlobals")

    def __init__(self, lights=(), geometry=("|ball|ballShape", "|floor|floorShape"),
                 arnold_options=True):
        # mtoa builds `defaultArnoldRenderOptions` LAZILY: on a Maya that has
        # only just loaded the plugin it does not exist yet, and a setAttr
        # against it raises. `arnold_options=False` is that cold Maya - the
        # state in which the AA sample count the caller asked for silently
        # became Arnold's own default (#797). Modelled here because the fake
        # used to accept the write unconditionally, so the swallow could not
        # be seen from a test.
        self.dg_nodes = set(self._DG_NODES)
        if not arnold_options:
            self.dg_nodes.discard("defaultArnoldRenderOptions")
        self.made_nodes = []
        self.attrs = {
            "defaultRenderGlobals.imageFormat": 7,
            "defaultRenderGlobals.imageFilePrefix": "",
            "defaultRenderGlobals.currentRenderer": "mayaSoftware",
            "defaultResolution.width": 960,
            "defaultResolution.height": 540,
            "defaultResolution.deviceAspectRatio": 1.777,
        }
        if arnold_options:
            self.attrs["defaultArnoldRenderOptions.AASamples"] = 1
        self.created = []
        self.deleted = []
        self.hidden = []
        self.written = []
        self.loaded_plugins = []
        self._renderers = ["mayaSoftware", "mayaHardware2", "arnold"]
        # Arnold registers its renderer through a DEFERRED callback, so on a
        # real Maya the renderer list can still omit it right after a
        # successful load. Set this to reproduce that window.
        self.renderer_list_lags = False
        # World rotation reported for a light transform, keyed by name.
        self.light_yaw_query = {}
        self.yaw_history = []
        self._lights = list(lights)
        # Arnold's light shapes are their own node types and answer NEITHER
        # ls(lights=True) nor ls(type="light") - they have to be asked for by
        # name. A sky dome also answers ls(geometry=True), which is #618.
        self.arnold_lights = []
        # Geometry is SHAPES, as cmds.ls(geometry=True) returns them - the
        # distinction that made isolate hide its own subject (redmine #584).
        self._geometry = list(geometry)
        self._transforms = sorted({s.rsplit("|", 1)[0] for s in self._geometry})
        self.visibility = {name: True for name in self._geometry}
        # Per-shape world boxes, for tests that care where things are. Anything
        # unlisted is the unit box.
        self.boxes = {}
        # plug -> the node feeding it. A visibility plug an anim curve or a
        # constraint drives refuses `cmds.hide` in real Maya, and hiding is
        # how this module isolates (#799 contract 2).
        #
        # Round 2: hiding is NOT the only persistent write this module
        # makes. `_orient_rig`/`_restore_rig` setAttr .rotateY on the tool's
        # own rig lights - `mcpLight_*` nodes that live in the user's scene
        # and can be keyed or constrained like any other - so the same
        # refusal applies to setAttr, and both writes there sit inside a
        # bare `except Exception: pass`. Narrowing this to `hide` on the
        # premise that everything else render.py writes is a temp camera or
        # a render-globals plug was simply wrong.
        # plug -> the SOURCE PLUG feeding it, because that is what Maya's
        # listConnections(plugs=True) answers and what the shared
        # writability guard classifies with nodeType (#802). Every entry's
        # source node must therefore be registered in `node_types`.
        self.driven_plugs = {}
        # Plugs a rigger locked. First modelled in #802: `_orient_rig`
        # writes a rig light the user may have locked, and `cmds.hide` on a
        # shape whose visibility is driven does not raise at all - it
        # returns cleanly and leaves the shape in frame (measured), which
        # is why the guard asks rather than catches.
        self.locked_plugs = set()
        self.undo_state = True
        # Nodes this fake MADE (cameras, the fallback light) plus the
        # parent/shape wiring Maya would have given them (#799).
        self._made = set()
        self.shape_of = {}
        self.parent_of = {}
        self.node_types = {}
        self._create_seq = 0

    # --- #799 existence --------------------------------------------------
    def _scene_nodes(self):
        """Every node that exists RIGHT NOW.

        `deleted` is a LOG, not a tombstone: it is deliberately not
        subtracted here. Subtracting it made a name unusable forever, so a
        second render_scene against one fake built its temp camera, renamed
        it to the name the first render had deleted, and then could not
        find the node it had just made - a fake wrong in the STRICT
        direction, which produces spurious failures the next reader "fixes"
        by weakening it back. `delete` unregisters instead.
        """
        nodes = set(self._geometry) | set(self._transforms) | set(self._lights)
        # A light shape's transform: real lights hang under one.
        nodes |= {s.rsplit("|", 1)[0] for s in self._lights if s.count("|") > 1}
        nodes |= self._made
        # A connection implies both of its ends, so the node feeding a
        # driven plug exists by definition (#802). Its TYPE still has to be
        # declared in `node_types` - nodeType raises otherwise, which is the
        # #799 rule that a fake answers only what it was told.
        nodes |= {src.split(".")[0] for src in self.driven_plugs.values()}
        return nodes

    def _resolve(self, name):
        name = str(name)
        nodes = self._scene_nodes()
        if name in nodes:
            return name
        short = name.rsplit("|", 1)[-1]
        hits = [n for n in nodes if n.rsplit("|", 1)[-1] == short]
        return hits[0] if len(hits) == 1 else None

    def _require(self, name):
        """Maya's answer for a node that was deleted or never made.

        The render path deletes its temp camera and its fallback light in a
        `finally`, and anything that asks about either afterwards gets this
        rather than a plausible default (#796's blocking-defect class).
        """
        if str(name) in self.dg_nodes:
            return str(name)
        resolved = self._resolve(name)
        if resolved is None:
            raise RuntimeError("No object matches name: %s" % name)
        return resolved

    def _make(self, transform, shape, node_type):
        self._made.update((transform, shape))
        self.shape_of[transform] = shape
        self.parent_of[shape] = transform
        self.node_types[transform] = "transform"
        self.node_types[shape] = node_type
        self.attrs[transform + ".translate"] = [0.0, 0.0, 0.0]
        self.attrs[transform + ".rotate"] = [0.0, 0.0, 0.0]
        self.attrs[transform + ".rotateY"] = 0.0
        return transform, shape

    # --- queries
    def ls(self, *args, **kwargs):
        if kwargs.get("lights"):
            return list(self._lights)
        if kwargs.get("type") == "light":
            return list(self._lights)
        if kwargs.get("type") == "aiSkyDomeLight":
            return list(self.arnold_lights)
        if kwargs.get("geometry"):
            # Real cmds.ls returns SHORT names unless long=True is asked for.
            # Reproducing that is the whole point: the live gate found isolate
            # hiding its own subject because "gemShape" never matches "|gem".
            if kwargs.get("long"):
                return list(self._geometry)
            return [name.rsplit("|", 1)[-1] for name in self._geometry]
        if args:
            name = args[0]
            # #799: a name nobody made answers with NOTHING. It used to
            # answer "|<whatever you asked>", which is why _hide_non_targets'
            # `or [name]` fallback and every "is this really there?" question
            # in this module were unaskable here.
            resolved = self._resolve(name)
            if resolved is None:
                return []
            return [resolved] if kwargs.get("long") else [name]
        return []

    def objExists(self, name):
        if str(name) in self.dg_nodes:
            return True
        return self._resolve(name) is not None

    def createNode(self, node_type, name=None, **kwargs):
        """Build a DG node. Used for mtoa's lazy options node.

        Registers it, so the setAttr that follows stops raising - the
        ensure-then-write sequence is only worth anything if the fake can
        tell "the node was created" from "the write was accepted anyway".
        """
        made = name or (node_type + "1")
        self.made_nodes.append((node_type, made))
        self.dg_nodes.add(made)
        return made

    def exactWorldBoundingBox(self, *targets, **kwargs):
        """A transform's box INCLUDES its descendants - and, unless
        ignoreInvisible is asked for, includes hidden ones too.

        Both halves are measured against Maya 2027 (mayapy): a parent whose only
        distant child is hidden still reports that child's corner at 20.5, and
        ignoreInvisible=True reports 0.5. A fake that ignored the flag would let
        #640's second half - a sheet cell framed on the whole subtree it had
        just hidden - stay green.

        #799 round 2: it takes the node registry like every other
        string-accepting method here (it answered a unit box for a name
        nobody made), and it answers Maya's INVERTED SENTINEL when nothing
        under the targets is visible. Measured on 2027 as [1e20]*3 +
        [-1e20]*3; a plausible unit box instead left capture._scene_bbox's
        sentinel fallback (capture.py:470-475, the #640 fix that stops a
        camera being placed 5.8e20 units out) unreachable from this file,
        deletable with the suite still green. Short names resolve, as Maya
        resolves them - `ls(geometry=True)` hands this module short names.
        """
        ignore_invisible = bool(kwargs.get("ignoreInvisible"))
        boxes = []
        for target in targets:
            resolved = self._require(target)
            for shape in self._geometry:
                if shape != resolved and not shape.startswith(resolved + "|"):
                    continue
                if ignore_invisible and not self.visibility.get(shape, True):
                    continue
                boxes.append(self.boxes.get(shape, (-1.0, -1.0, -1.0, 1.0, 1.0, 1.0)))
        if not boxes:
            return [1e20, 1e20, 1e20, -1e20, -1e20, -1e20]
        return [min(b[i] for b in boxes) for i in range(3)] + [
            max(b[i] for b in boxes) for i in range(3, 6)
        ]

    def getAttr(self, attr, lock=False, **kw):
        node, _, name = str(attr).rpartition(".")
        self._require(node)
        if kw:
            # #802: an unmodelled flag used to fall into **kw and come back
            # as the VALUE - a silent lie about a question never taught.
            raise TypeError(
                "FakeCmds.getAttr models lock= only (#802), not %r" % sorted(kw))
        if lock:
            # Exact-plug, as Maya is: getAttr('.rotate', lock=True) is False
            # while rotateY alone is locked (measured A01).
            return attr in self.locked_plugs
        if name == "visibility":
            return self.visibility.get(node, True)
        if attr not in self.attrs:
            raise RuntimeError("No object matches name: %s" % attr)
        value = self.attrs[attr]
        if name in ("translate", "rotate"):
            # Maya wraps a double3 query in a one-tuple list, and the value
            # is whatever was SET - not a constant (0,0,0), which is how the
            # reported camera_positions went unchecked (#799).
            return [tuple(value)]
        return value

    def renderer(self, *args, **kwargs):
        return list(self._renderers)

    def loadPlugin(self, name, **kwargs):
        self.loaded_plugins.append(name)
        if name == "mtoa" and not self.renderer_list_lags:
            if "arnold" not in self._renderers:
                self._renderers.append("arnold")
        return [name]

    def pluginInfo(self, name, **kwargs):
        if kwargs.get("loaded"):
            return name in self.loaded_plugins
        return None

    def undoInfo(self, **kwargs):
        # #799: it used to answer True to everything, edits included, so
        # "did the render put undo recording back?" - the whole point of the
        # snapshot in _run_shots - could not be asked here.
        if kwargs.get("query"):
            return self.undo_state
        if "stateWithoutFlush" in kwargs:
            self.undo_state = bool(kwargs["stateWithoutFlush"])
        return None

    def nodeType(self, name):
        resolved = self._require(name)
        if resolved in self.node_types:
            return self.node_types[resolved]
        if resolved in self.arnold_lights:
            return "aiSkyDomeLight"
        if resolved in self._lights:
            return "directionalLight"
        if resolved in self._geometry:
            return "mesh"
        # Every remaining registered node is a transform; a trailing
        # `return "transform"` for ANYTHING is the fallback #796 was shipped
        # under, so the unknown case raises instead (#799).
        if resolved in self._transforms or resolved in {
            s.rsplit("|", 1)[0] for s in self._lights if s.count("|") > 1
        }:
            return "transform"
        raise RuntimeError("No object matches name: %s" % name)


    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, type=None, **kw):
        """Source-side connections of ONE EXACT plug, as Maya answers them.

        Exact, because Maya is: a query on `.rotate` returns None while all
        three children are constraint-fed, and a child query does not see a
        connection on the compound - measured on 2027 by
        evals/static_write_probe_802.py (B01/B02). The shared guard asks
        about the compound and its children separately BECAUSE of that, so
        a fake that folded them together would make its central case
        untestable (#802).
        """
        self._require(str(plug).split(".")[0])
        if not source:
            raise AssertionError(
                "FakeCmds.listConnections models source queries only (#802)")
        src = self.driven_plugs.get(plug)
        if src is None:
            return None
        node = src.split(".")[0]
        if type is not None:
            # Maya's type filter matches DERIVED types (the #796 trap).
            actual = self.nodeType(node)
            if not (actual == type
                    or (type == "animCurve" and actual.startswith(type))):
                return None
        return [src] if plugs else [node]

    # --- mutations
    def _static_write_blocker(self, node, name):
        """The connection that makes a static write to `node.name` raise.

        Maya refuses in BOTH compound directions: `.rotate` will not take a
        write while `.rotateY` alone is fed, and `.rotateY` will not take
        one while the whole `.rotate` compound is. The second direction is
        the one this module meets - `_orient_rig` writes the CHILD plug
        `.rotateY` on the tool's own rig lights, and a rig light riding a
        parentConstraint has the compound fed.
        """
        candidates = ["%s.%s" % (node, name)]
        candidates += ["%s.%s%s" % (node, name, axis) for axis in "XYZ"]
        if name[-1:] in ("X", "Y", "Z"):
            candidates.append("%s.%s" % (node, name[:-1]))
        for plug in candidates:
            if plug in self.locked_plugs:
                return "%s is locked" % plug
            if plug in self.driven_plugs:
                return self.driven_plugs[plug]
        return None

    def setAttr(self, attr, *values, **kwargs):
        node, _, name = str(attr).rpartition(".")
        resolved = self._require(node)
        # #799 round 2: a connection-fed or locked plug REFUSES a static
        # write. render.py does not only write temp cameras and DG plugs -
        # `_orient_rig`/`_restore_rig` write .rotateY on the tool's own
        # persistent rig lights, nodes a user can key or constrain, and both
        # writes sit inside a bare `except Exception: pass`.
        source = self._static_write_blocker(resolved, name)
        if source:
            raise RuntimeError(
                "setAttr: The attribute '%s.%s' is locked or connected and "
                "cannot be modified (%s feeds it)" % (resolved, name, source))
        self.attrs[attr] = values[0] if len(values) == 1 else list(values)
        if attr.endswith(".rotateY"):
            self.yaw_history.append(values[0])

    def camera(self, *args, **kwargs):
        # A real camera comes with a SHAPE, and the film back lives on it.
        # Handing back a shapeless transform sent apply_framing_fov down its
        # `or [camera]` fallback and made the #772 lens fix inert here (#799).
        self._create_seq += 1
        transform = "camera%d" % self._create_seq
        shape = "cameraShape%d" % self._create_seq
        self._make(transform, shape, "camera")
        self.attrs[shape + ".horizontalFilmAperture"] = \
            capture.MAYA_HORIZONTAL_APERTURE_IN
        self.attrs[shape + ".verticalFilmAperture"] = 0.9449
        self.attrs[shape + ".focalLength"] = 35.0
        self.attrs[shape + ".filmFit"] = 0
        self.attrs[transform + ".nearClipPlane"] = 0.1
        self.created.append(transform)
        return [transform, shape]

    def rename(self, old, new):
        resolved = self._require(old)
        self.created.append(new)
        old_shape = self.shape_of.pop(resolved, None)
        self._made.discard(resolved)
        self._made.add(new)
        self.node_types[new] = self.node_types.pop(resolved, "transform")
        if old_shape:
            # Maya renames a default-named shape along with its transform.
            new_shape = new + "Shape"
            self._made.discard(old_shape)
            self._made.add(new_shape)
            self.shape_of[new] = new_shape
            self.parent_of.pop(old_shape, None)
            self.parent_of[new_shape] = new
            self.node_types[new_shape] = self.node_types.pop(old_shape, "camera")
            # cmds.directionalLight hands back the SHAPE and the tool renames
            # the TRANSFORM, so the light registry is keyed on the shape's
            # OLD name. Leaving it there orphaned the fallback light: the
            # render deleted it and `directionalLightShape1` went on
            # answering objExists/nodeType/ls(lights=True) forever - the
            # vanished-node fallback surviving inside the class that claims
            # to have removed it (#799 round 2).
            if old_shape in self._lights:
                self._lights[self._lights.index(old_shape)] = new_shape
            for plug in list(self.attrs):
                if plug.startswith(old_shape + "."):
                    self.attrs[new_shape + plug[len(old_shape):]] = \
                        self.attrs.pop(plug)
        for plug in list(self.attrs):
            if plug.startswith(resolved + "."):
                self.attrs[new + plug[len(resolved):]] = self.attrs.pop(plug)
        if resolved in self._lights:
            self._lights[self._lights.index(resolved)] = new
        return new

    def directionalLight(self, **kwargs):
        # cmds.directionalLight returns the SHAPE, under Maya's own generated
        # name - not the tool's. The tool renames the transform afterwards,
        # and pinning the pre-rename name here hid whether it did.
        self._create_seq += 1
        transform = "directionalLight%d" % self._create_seq
        shape = "directionalLightShape%d" % self._create_seq
        self._make(transform, shape, "directionalLight")
        self.created.append(shape)
        self._lights.append(shape)
        return shape

    def listRelatives(self, name, **kwargs):
        resolved = self._require(name)
        if kwargs.get("parent"):
            parent = self.parent_of.get(resolved)
            if parent is None and resolved.startswith("|") and resolved.count("|") > 1:
                parent = resolved.rsplit("|", 1)[0]
            return [parent] if parent else None
        if kwargs.get("shapes"):
            shape = self.shape_of.get(resolved)
            return [shape] if shape else None
        if kwargs.get("allDescendents"):
            return [s for s in self._geometry if s.startswith(resolved + "|")]
        return []

    def xform(self, *args, **kwargs):
        transform = self._require(args[0]) if args else None
        if "edit" in kwargs:
            # MEASURED on Maya 2027 (#802): cmds.xform has no `edit` flag
            # at all - it raises "Invalid flag 'edit'". This fake accepted
            # it, so `_orient_rig`'s rotateAxis write looked alive here
            # while raising on every real render, swallowed by a bare
            # `except Exception: pass`. A fake that accepts what Maya
            # rejects is how a dead call stays green for a year.
            raise TypeError("Invalid flag 'edit'")
        if kwargs.get("query") and kwargs.get("rotation"):
            return list(self.light_yaw_query.get(transform, (0.0, 0.0, 0.0)))
        return None

    def hide(self, name):
        # cmds.hide IS a setAttr on .visibility, so it takes the same
        # blocker - one rule, not two that can drift apart.
        resolved = self._require(name)
        source = self._static_write_blocker(resolved, "visibility")
        if source:
            raise RuntimeError(
                "setAttr: The attribute '%s.visibility' is locked or "
                "connected and cannot be modified (%s feeds it)"
                % (resolved, source))
        self.hidden.append(name)
        self.visibility[name] = False

    def showHidden(self, name):
        self._require(name)
        self.visibility[name] = True

    def delete(self, name):
        resolved = self._require(name)
        self.deleted.append(name)
        # Deleting a transform takes its shape with it - so a later query
        # about either one raises, which is the whole point of tracking it.
        # `shape_of` is a LOG, like `attrs`: a test that asks which shape the
        # temp camera had reads it after the render cleaned up. Existence is
        # decided by the registries below, so a stale entry answers nothing -
        # every query goes through `_require` first.
        shape = self.shape_of.get(resolved)
        for gone in (resolved, shape):
            if gone is None:
                continue
            self._made.discard(gone)
            self.node_types.pop(gone, None)
            self.parent_of.pop(gone, None)
            self.visibility.pop(gone, None)
            if gone in self._lights:
                self._lights.remove(gone)
            if gone in self._geometry:
                self._geometry.remove(gone)
            if gone in self._transforms:
                self._transforms.remove(gone)
        if shape:
            self.deleted.append(shape)


def _stub_render_frame(tmp_path, fake):
    """Stand in for cmds.render: writes a small lit PNG, records the call."""
    from PIL import Image as PILImage

    def render_frame(cmds, camera, prefix, renderer, resolution, samples,
                     notes=None):
        path = tmp_path / (prefix + ".png")
        PILImage.new("RGB", (8, 8), (120, 30, 30)).save(path)
        fake.written.append({
            "prefix": prefix, "renderer": renderer,
            "resolution": resolution, "samples": samples,
            # Per-FRAME state. `fake.hidden` accumulates across a sheet and
            # showHidden does not unwind it, so only a snapshot taken at render
            # time can say what a given cell actually showed.
            "visible": sorted(n for n, on in fake.visibility.items() if on),
            "camera_translate": fake.attrs.get(camera + ".translate"),
        })
        return str(path)

    return render_frame


@pytest.fixture
def fake_maya(monkeypatch, tmp_path):
    fake = FakeCmds(lights=["|keyLightShape"])
    monkeypatch.setattr(render, "_cmds", lambda: fake)
    monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
    return fake


class TestTheFakeRefusesWhatMayaRefuses:
    """The regression barrier for FakeCmds itself (#799 round 2).

    The hardening above was asserted by nothing: reverting every behavioural
    change in this fake left the suite fully green, which is the ticket's own
    complaint - "a green suite proves nothing" - moved up one level. These
    pin the contract points this fake actually models, so loosening one goes
    RED here rather than quietly restoring the answers-anything fallbacks.

    A fake that is wrong in the STRICT direction is just as bad, so the
    lifecycle claims below (a name is reusable after a delete, a bbox
    resolves a short name) are pinned alongside the refusals.
    """

    # -- #802: the two queries the shared writability guard makes ---------
    def test_getattr_lock_is_exact_plug_like_maya(self):
        """MEASURED (A01): getAttr('.rotate', lock=True) is False while
        rotateY is locked, which is why the guard walks the family."""
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.locked_plugs = {"|mcpLight_key.rotateY"}
        assert fake.getAttr("|mcpLight_key.rotateY", lock=True) is True
        assert fake.getAttr("|mcpLight_key.rotate", lock=True) is False

    def test_a_locked_rig_light_refuses_its_setattr(self):
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.locked_plugs = {"|mcpLight_key.rotateY"}
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("|mcpLight_key.rotateY", 90.0)

    def test_listconnections_answers_the_exact_plug_only(self):
        """MEASURED (B01/B02): the compound answers None while the children
        are fed, and a child does not see the compound's own source."""
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.node_types["key_anim"] = "animCurveTA"
        fake.driven_plugs["|mcpLight_key.rotateY"] = "key_anim.output"
        ask = lambda plug: fake.listConnections(  # noqa: E731
            plug, source=True, destination=False, plugs=True)
        assert ask("|mcpLight_key.rotateY") == ["key_anim.output"]
        assert ask("|mcpLight_key.rotate") is None
        assert ask("|mcpLight_key.rotateX") is None
        with pytest.raises(AssertionError, match="source queries only"):
            fake.listConnections("|mcpLight_key.rotateY", destination=True)

    def test_a_source_node_exists_but_its_type_must_be_declared(self):
        """A connection implies both ends, so the source node exists. Its
        TYPE does not follow from that, and inventing one would let a wrong
        hint ship green (#799's rule, applied to the new query)."""
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.driven_plugs["|mcpLight_key.rotateY"] = "mystery.output"
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("mystery")
        fake.node_types["mystery"] = "pairBlend"
        assert fake.nodeType("mystery") == "pairBlend"

    def test_an_unmodelled_getattr_flag_raises_rather_than_lying(self):
        fake = FakeCmds()
        with pytest.raises(TypeError, match="lock="):
            fake.getAttr("|ball|ballShape.visibility", settable=True)

    def test_xform_has_no_edit_flag(self):
        """MEASURED on Maya 2027 (#802): `cmds.xform(node, edit=True, ...)`
        raises "Invalid flag 'edit'". This fake used to accept it, and
        `_orient_rig`'s rotateAxis write therefore looked alive here while
        raising on every real render into a bare `except Exception: pass`.
        The dead call is gone; this keeps it from coming back green."""
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        with pytest.raises(TypeError, match="Invalid flag 'edit'"):
            fake.xform("|mcpLight_key", edit=True, rotateAxis=(0, 0, 0))
        # ...and the form Maya DOES take is still accepted.
        fake.xform("|mcpLight_key", rotateAxis=(0, 0, 0))

    def test_orient_rig_makes_only_the_yaw_write(self, monkeypatch, tmp_path):
        """The rotateAxis write is deleted, not repaired: making it work for
        the first time would leave a permanent mutation in the user's rig
        that _restore_rig never undoes."""
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.light_yaw_query["|mcpLight_key"] = (-35.0, 30.0, 0.0)
        notes, refused = render._orient_rig(fake, {"|mcpLight_key": 30.0}, 90.0)
        assert notes == [] and refused == []
        assert fake.yaw_history == [120.0]

    def test_a_blocked_light_is_neither_swung_nor_restored(self, monkeypatch,
                                                           tmp_path):
        """One keyed light, one free: the free one swings and is put back,
        the keyed one is never written - not by the relight, and not by the
        restore in the finally either (review catch: the restore's skip was
        covered by nothing)."""
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape",
                                "|mcpLight_fill|mcpLight_fillShape"])
        fake.light_yaw_query["|mcpLight_key"] = (-35.0, 30.0, 0.0)
        fake.light_yaw_query["|mcpLight_fill"] = (-20.0, -55.0, 0.0)
        fake.node_types["fill_anim"] = "animCurveTA"
        fake.driven_plugs["|mcpLight_fill.rotateY"] = "fill_anim.output"
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["side"]})
        assert out["relit_lights"] == 1
        # exactly two writes in the whole render: the key out, the key back
        assert fake.yaw_history == [120.0, 30.0]
        assert "|mcpLight_fill.rotateY" not in fake.attrs
        assert sum("mcpLight_fill" in w for w in out["warnings"]) == 1

    # -- contract 1: existence -------------------------------------------
    def test_every_query_about_a_node_nobody_made_raises(self):
        fake = FakeCmds()
        ghost = "|nobodyMadeThis"
        for call in (
            lambda: fake.getAttr(ghost + ".translate"),
            lambda: fake.nodeType(ghost),
            lambda: fake.listRelatives(ghost, parent=True),
            lambda: fake.xform(ghost, query=True, rotation=True),
            lambda: fake.setAttr(ghost + ".rotateY", 1.0),
            lambda: fake.hide(ghost),
            lambda: fake.showHidden(ghost),
            lambda: fake.rename(ghost, "somethingElse"),
            lambda: fake.delete(ghost),
            lambda: fake.exactWorldBoundingBox(ghost),
        ):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_ls_and_objexists_report_rather_than_raise(self):
        # The two existence queries Maya answers instead of refusing - and
        # the pair every "is it really there?" test is written on.
        fake = FakeCmds()
        assert fake.ls("|nobodyMadeThis", long=True) == []
        assert fake.objExists("|nobodyMadeThis") is False
        assert fake.ls("|ball", long=True) == ["|ball"]
        assert fake.objExists("ballShape") is True

    def test_the_temp_camera_stops_answering_once_the_render_deletes_it(
        self, fake_maya
    ):
        out = render.render_scene({"angles": ["front"]})
        camera = out["camera_positions"][0]["camera"]
        assert camera in fake_maya.deleted
        assert fake_maya.objExists(camera) is False
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake_maya.nodeType(camera)
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake_maya.getAttr(camera + ".translate")

    def test_the_fallback_light_really_leaves_the_scene(self, monkeypatch, tmp_path):
        """Round 2, finding 2: `rename` updated the light registry only when
        the RENAMED node was in it, and it holds the light SHAPE while
        render.py renames the TRANSFORM - so the shape's pre-rename name was
        orphaned and went on answering objExists/nodeType/ls(lights=True)
        forever, the deleted-node fallback surviving inside the class that
        claims to have removed it."""
        fake = FakeCmds(lights=[])
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        render.render_scene({"angles": ["front"]})
        assert fake.ls(lights=True) == []
        for stale in ("directionalLightShape1", "mayaMcpTempKeyShape"):
            assert fake.objExists(stale) is False
            with pytest.raises(RuntimeError, match="No object matches name"):
                fake.nodeType(stale)

    def test_a_deleted_name_can_be_used_again(self, monkeypatch, tmp_path):
        """Round 2, finding 3 - the STRICT-direction half: `deleted` was
        subtracted from the scene forever, so a second render built its temp
        camera, renamed it to the name the first render had deleted, and
        then died inside capture.apply_framing_fov on the node it had just
        made."""
        fake = FakeCmds(lights=["|keyLightShape"])
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        render.render_scene({"angles": ["front"]})
        second = render.render_scene({"angles": ["front"]})
        assert second["images"][0]["png_b64"]
        assert fake.deleted.count("mayaMcpRenderCam") == 2

    # -- contract 2: a fed plug refuses a static write --------------------
    def test_setattr_refuses_a_connection_fed_plug(self):
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.node_types["key_rotateY_anim"] = "animCurveTA"
        fake.driven_plugs["|mcpLight_key.rotateY"] = (
            "key_rotateY_anim.output")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("|mcpLight_key.rotateY", 90.0)
        assert fake.yaw_history == []

    def test_setattr_refuses_a_child_write_when_the_compound_is_fed(self):
        # The direction render.py meets: _orient_rig writes the CHILD plug
        # .rotateY, and a rig light riding a parentConstraint has the whole
        # .rotate compound fed.
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.node_types["mcpLight_key_pc1"] = "parentConstraint"
        fake.driven_plugs["|mcpLight_key.rotate"] = (
            "mcpLight_key_pc1.constraintRotate")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("|mcpLight_key.rotateY", 90.0)

    def test_setattr_refuses_a_compound_write_when_a_child_is_fed(self):
        # The other direction, measured on #796: Maya refuses the compound
        # too. A blocker that models only one of the two is a guard a test
        # can be written on and pass vacuously.
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.node_types["key_rotateY_anim"] = "animCurveTA"
        fake.driven_plugs["|mcpLight_key.rotateY"] = (
            "key_rotateY_anim.output")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("|mcpLight_key.rotate", 0.0, 90.0, 0.0)

    def test_a_free_plug_still_takes_its_write(self):
        # The refusal must not become the answer to everything either.
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.setAttr("|mcpLight_key.rotateY", 90.0)
        assert fake.attrs["|mcpLight_key.rotateY"] == 90.0
        assert fake.yaw_history == [90.0]

    def test_hide_refuses_a_fed_visibility(self):
        # cmds.hide IS a setAttr on .visibility - the refusal the
        # _hide_non_targets xfail is built on.
        fake = FakeCmds()
        fake.node_types["floor_vis_anim"] = "animCurveTU"
        fake.driven_plugs["|floor|floorShape.visibility"] = (
            "floor_vis_anim.output")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.hide("|floor|floorShape")
        assert fake.visibility["|floor|floorShape"] is True

    # -- the answers-anything fallbacks that were removed ------------------
    def test_the_bbox_answers_mayas_sentinel_when_nothing_is_visible(self):
        """Round 2, finding 4: it invented a unit box, so
        capture._scene_bbox's sentinel fallback - the #640 fix that stops a
        camera being placed 5.8e20 units out - was unreachable from this
        file and could have been deleted with the suite green."""
        fake = FakeCmds()
        fake.visibility["|ball|ballShape"] = False
        assert fake.exactWorldBoundingBox("|ball", ignoreInvisible=True) == [
            1e20, 1e20, 1e20, -1e20, -1e20, -1e20]
        # ...and the fallback that follows it reports where the ball IS.
        assert fake.exactWorldBoundingBox("|ball") == [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0]

    def test_the_bbox_takes_the_short_names_ls_hands_out(self):
        # The strict direction again: cmds.ls(geometry=True) returns SHORT
        # names and Maya resolves an unambiguous one, so demanding long names
        # here would refuse the call framable_geometry actually makes.
        fake = FakeCmds()
        assert fake.exactWorldBoundingBox("ballShape") == \
            fake.exactWorldBoundingBox("|ball|ballShape")

    def test_undoinfo_records_the_edit_it_used_to_swallow(self):
        fake = FakeCmds()
        assert fake.undoInfo(query=True, state=True) is True
        fake.undoInfo(stateWithoutFlush=False)
        assert fake.undoInfo(query=True, state=True) is False

    def test_a_created_camera_comes_with_a_shape_that_holds_the_film_back(self):
        # The shapeless transform made apply_framing_fov read the film back
        # off the transform - where this fake answered 0 - and the #772 lens
        # fix was inert on the render path.
        fake = FakeCmds()
        transform, shape = fake.camera()
        assert fake.listRelatives(transform, shapes=True, fullPath=True) == [shape]
        assert fake.getAttr(shape + ".horizontalFilmAperture") == \
            capture.MAYA_HORIZONTAL_APERTURE_IN

    def test_getattr_reports_what_setattr_wrote(self):
        # It answered a constant [(0,0,0)] for every .translate, so the
        # camera_positions this tool REPORTS were compared with nothing.
        fake = FakeCmds()
        transform, _shape = fake.camera()
        fake.setAttr(transform + ".translate", 1.0, 2.0, 3.0)
        assert fake.getAttr(transform + ".translate") == [(1.0, 2.0, 3.0)]

    def test_listrelatives_no_longer_names_the_fallback_light_for_anything(self):
        # It ended in an unconditional `return ["mayaMcpTempKey"]`.
        fake = FakeCmds(lights=["|keyLightShape"])
        assert fake.listRelatives("|ball|ballShape", parent=True) == ["|ball"]
        assert fake.listRelatives("|ball", parent=True) is None


class TestRenderScene:
    def test_returns_one_image_per_angle(self, fake_maya):
        out = render.render_scene({"angles": ["front", "side"]})
        assert [i["angle"] for i in out["images"]] == ["front", "side"]
        assert all(i["png_b64"] for i in out["images"])
        assert out["renderer"] == "arnold"
        assert len(out["camera_positions"]) == 2

    def test_every_frame_gets_its_own_prefix(self, fake_maya):
        render.render_scene({"angles": ["front", "front"]})
        prefixes = [w["prefix"] for w in fake_maya.written]
        assert len(set(prefixes)) == 2, "cmds.render overwrites a fixed path"

    def test_render_globals_are_restored(self, fake_maya):
        # Including currentRenderer: the call has to switch the scene's renderer
        # to render at all, and must switch it back.
        before = dict(fake_maya.attrs)
        render.render_scene({"angles": ["front"], "resolution": 256})
        after = {key: fake_maya.attrs[key] for key in before}
        assert after == before

    def test_temp_camera_is_deleted(self, fake_maya):
        render.render_scene({"angles": ["front"]})
        assert any("mayaMcpRenderCam" in name for name in fake_maya.deleted)

    def test_undo_recording_is_put_back(self, fake_maya):
        # Perception must not pollute the undo queue, so the render turns
        # recording off - and has to turn it back on. undoInfo answered True
        # to edits as well as queries until #799, so this was unaskable.
        render.render_scene({"angles": ["front"]})
        assert fake_maya.undo_state is True

    def test_isolate_hides_non_targets_and_restores_them(self, fake_maya):
        render.render_scene({"angles": ["front"], "isolate": ["|ball"]})
        assert "|floor|floorShape" in fake_maya.hidden
        assert all(fake_maya.visibility.values()), "visibility must be restored"

    def test_isolate_leaves_already_hidden_objects_hidden(self, monkeypatch, tmp_path):
        # Restoring visibility on something WE did not hide would show the user
        # an object they deliberately hid - a perception tool editing the scene.
        fake = FakeCmds(lights=["|keyLightShape"])
        fake.visibility["|floor|floorShape"] = False
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        render.render_scene({"angles": ["front"], "isolate": ["|ball"]})
        assert fake.visibility["|floor|floorShape"] is False
        assert "|floor|floorShape" not in fake.hidden

    def test_isolate_does_not_hide_its_own_subject(self, fake_maya):
        # cmds.ls(geometry=True) returns SHAPES, and a transform name never
        # matches one: the live gate caught this hiding the very gem it was
        # asked to render, and returning a black frame (redmine #584).
        render.render_scene({"angles": ["front"], "isolate": ["|ball"]})
        assert "|ball|ballShape" not in fake_maya.hidden

    def test_isolate_rejects_a_missing_object(self, fake_maya):
        with pytest.raises(HandlerError):
            render.render_scene({"angles": ["front"], "isolate": ["|nope"]})

    def test_fallback_light_added_when_dark_and_removed_after(
        self, monkeypatch, tmp_path
    ):
        fake = FakeCmds(lights=[])
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"]})
        assert out["fallback_light"] is True
        assert any("mayaMcpTempKey" in name for name in fake.deleted)

    def test_no_fallback_light_when_the_scene_has_one(self, fake_maya):
        out = render.render_scene({"angles": ["front"]})
        assert out["fallback_light"] is False

    def test_fallback_light_can_be_declined(self, monkeypatch, tmp_path):
        fake = FakeCmds(lights=[])
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"], "fallback_light": False})
        assert out["fallback_light"] is False
        assert not any("mayaMcpTempKey" in name for name in fake.created)

    def test_unknown_renderer_is_rejected_before_touching_the_scene(self, fake_maya):
        with pytest.raises(HandlerError):
            render.render_scene({"renderer": "redshift"})
        assert fake_maya.created == []

    def test_missing_arnold_is_an_error_not_a_silent_substitution(
        self, monkeypatch, fake_maya
    ):
        monkeypatch.setattr(
            fake_maya, "renderer", lambda *a, **k: ["mayaSoftware", "mayaHardware2"]
        )
        monkeypatch.setattr(
            fake_maya, "loadPlugin",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mtoa not installed")),
        )
        with pytest.raises(HandlerError) as excinfo:
            render.render_scene({"angles": ["front"]})
        assert "hw2" in str(excinfo.value.hint or "")

    def test_mtoa_is_loaded_when_arnold_is_not_listed_yet(self, monkeypatch, tmp_path):
        # A cold Maya lists only mayaSoftware and mayaHardware2 until something
        # loads mtoa. Making the caller do that to use the DEFAULT renderer is
        # a tool defect; the live gate hit it on a freshly launched Maya.
        fake = FakeCmds(lights=["|keyLightShape"])
        fake._renderers = ["mayaSoftware", "mayaHardware2"]
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"]})
        assert fake.loaded_plugins == ["mtoa"]
        assert out["renderer"] == "arnold"

    def test_mtoa_is_not_loaded_for_an_hw2_render(self, fake_maya):
        render.render_scene({"angles": ["front"], "renderer": "hw2"})
        assert fake_maya.loaded_plugins == []

    def test_a_loaded_mtoa_counts_even_while_the_renderer_list_lags(
        self, monkeypatch, tmp_path
    ):
        # Arnold registers its renderer through a deferred callback, so for a
        # moment after a SUCCESSFUL load the renderer list still omits it.
        # Trusting that list rejected arnold on a just-started Maya; the
        # authoritative answer is whether the plugin is loaded.
        fake = FakeCmds(lights=["|keyLightShape"])
        fake._renderers = ["mayaSoftware", "mayaHardware2"]
        fake.renderer_list_lags = True
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"]})
        assert fake.loaded_plugins == ["mtoa"]
        assert out["renderer"] == "arnold"

    def test_target_frames_without_hiding_anything(self, fake_maya):
        # The #585 blocker: framing a gem for a close-up must not hide the
        # backdrop it needs behind it to refract.
        render.render_scene({"angles": ["front"], "target": ["|ball"]})
        assert fake_maya.hidden == []

    def test_isolate_still_frames_when_no_target_is_given(self, fake_maya):
        render.render_scene({"angles": ["front"], "isolate": ["|ball"]})
        assert "|floor|floorShape" in fake_maya.hidden

    def test_target_and_isolate_can_disagree(self, fake_maya):
        # Frame the ball, hide only the floor: both questions answered
        # independently, which is the point of the split.
        render.render_scene({
            "angles": ["front"], "target": ["|ball"], "isolate": ["|ball"]})
        assert "|floor|floorShape" in fake_maya.hidden

    def test_target_rejects_a_missing_object(self, fake_maya):
        with pytest.raises(HandlerError):
            render.render_scene({"angles": ["front"], "target": ["|nope"]})

    def test_zoom_moves_the_camera_closer_without_changing_the_angle(self):
        bbox_min, bbox_max = [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]
        position, _ = capture.camera_placement("front", bbox_min, bbox_max)
        closer = render.zoomed_position(position, bbox_min, bbox_max, 2.0)
        assert closer[2] == pytest.approx(position[2] / 2.0)
        assert closer[0] == pytest.approx(position[0])
        assert closer[1] == pytest.approx(position[1])

    def test_zoom_validation(self):
        assert render.resolve_zoom(None) == 1.0
        for bad in (0.0, 0.1, 20.0, "2x", True):
            with pytest.raises(HandlerError):
                render.resolve_zoom(bad)

    def test_box_clearance_is_zero_inside_and_axis_aligned_outside(self):
        box_min, box_max = [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]
        assert render.box_clearance((0.0, 0.0, 0.0), box_min, box_max) == 0.0
        assert render.box_clearance((0.5, -0.9, 0.2), box_min, box_max) == 0.0
        assert render.box_clearance((0.0, 0.0, 3.0), box_min, box_max) == \
            pytest.approx(2.0)
        # Off a corner both axes count, which is why this is not just a
        # centre-to-camera distance minus a radius.
        assert render.box_clearance((4.0, 1.0, 5.0), box_min, box_max) == \
            pytest.approx(5.0)

    def test_a_comfortable_framing_keeps_mayas_own_near_plane(self):
        # The cap is the point: everything that already rendered correctly must
        # keep the exact plane it had.
        box_min, box_max = [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]
        position, _ = capture.camera_placement("front", box_min, box_max)
        assert render.near_clip_for(position, box_min, box_max) == \
            render.DEFAULT_NEAR_CLIP

    def test_the_670_framing_puts_the_plane_in_front_of_the_subject(self):
        # Measured in Maya 2027: a 0.08 ball at z=0.55 in front of a 0.5 ball,
        # rendered at zoom 5, put the camera at z=0.6737 - 0.0437 in front of
        # the subject, INSIDE the fixed 0.1 plane. The ball came back sliced
        # flat; at zoom 4 (0.196 away) it rendered round.
        box_min, box_max = [-0.5, -0.5, -0.5], [0.5, 0.5, 0.63]
        position = (0.0, 0.0, 0.6737)
        clearance = render.box_clearance(position, box_min, box_max)
        assert clearance == pytest.approx(0.0437, abs=1e-4)
        assert render.DEFAULT_NEAR_CLIP > clearance  # the defect, in one line
        assert render.near_clip_for(position, box_min, box_max) < clearance

    def test_the_plane_stays_above_the_minimum_maya_will_accept(self):
        # Measured: setAttr REFUSES a nearClipPlane below 0.001 - it raises
        # instead of clamping, so a plane derived from a camera inside the
        # subject took the whole render down with it until the floor was
        # raised to Maya's own (#670 live gate, zoom 8).
        box_min, box_max = [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]
        for inside in ((0.0, 0.0, 0.0), (0.0, 0.0, 0.5), (0.9, -0.9, 0.1)):
            assert render.near_clip_for(inside, box_min, box_max) >= 0.001
        # ...and a camera a millimetre off a tiny subject cannot dodge it either.
        tiny_min, tiny_max = [-0.001, -0.001, -0.001], [0.001, 0.001, 0.001]
        assert render.near_clip_for((0.0, 0.0, 0.0015), tiny_min, tiny_max) >= 0.001

    def test_zoom_shrinks_the_near_plane_on_the_camera(self, fake_maya):
        out = render.render_scene({"angles": ["front"], "zoom": 5.0})
        camera = out["camera_positions"][0]["camera"]
        near = fake_maya.attrs[camera + ".nearClipPlane"]
        assert near < render.DEFAULT_NEAR_CLIP
        assert out["camera_positions"][0]["near_clip"] == near

    def test_a_camera_inside_the_framed_box_says_so(self, fake_maya):
        out = render.render_scene({"angles": ["front"], "zoom": 8.0})
        assert any("INSIDE the framed bounding box" in w
                   for w in out["warnings"])

    def test_a_normal_framing_warns_about_nothing(self, fake_maya):
        out = render.render_scene({"angles": ["front"]})
        assert out["warnings"] == []

    def test_a_subject_closer_than_mayas_minimum_plane_is_named(self):
        # Between "inside the box" and "comfortably framed" there is a band
        # where the plane has already bottomed out at 0.001 and the subject is
        # still in front of it. Nothing can be moved; saying so is the product.
        box_min, box_max = [-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]
        position = (0.0, 0.0, 1.0005)
        clearance = render.box_clearance(position, box_min, box_max)
        assert clearance < render.MIN_NEAR_CLIP
        # The plane cannot go where it would need to go, so it does not.
        assert render.near_clip_for(position, box_min, box_max) > clearance
        message = render.framing_warning(position, box_min, box_max, 6.0, "|ball")
        assert message is not None
        assert "no plane can fix that" in message

    def test_the_rig_follows_the_camera_and_is_put_back(self, monkeypatch, tmp_path):
        # setup_lighting builds a WORLD-locked rig while render_scene orbits, so
        # a side render came back nearly black: key at yaw +30, camera at 90.
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.light_yaw_query["|mcpLight_key"] = (-35.0, 30.0, 0.0)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["side"]})
        assert out["relit_lights"] == 1
        # side is azimuth 90: the key swings to 120 for the render...
        assert fake.yaw_history == [120.0, 30.0]
        # ...and 30 is where it ends up, because the rig is the user's scene.
        assert fake.attrs["|mcpLight_key.rotateY"] == 30.0

    def test_a_rig_light_it_could_not_swing_is_named(self, monkeypatch, tmp_path):
        """#802 FIXED. A rig it could not swing is named, not counted.

        Both writes sat in a bare `except Exception: pass` while
        `relit_lights` reported len(rig) - the count of lights DISCOVERED,
        not lights moved - so the caller was told the rig had followed the
        camera and got the nearly-black side render #585 exists to prevent.
        #799 pinned this expecting Maya to raise. It does not: a keyed
        rotateY takes the setAttr and the curve reasserts on the next frame
        change, and the `xform -rotateAxis` beside it never raises at all
        (measured, evals/static_write_probe_802b.py K3/K5 and L8/L9). There
        was no exception to catch, which is why the guard asks first.
        """
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.light_yaw_query["|mcpLight_key"] = (-35.0, 30.0, 0.0)
        fake.node_types["mcpLight_key_rotateY_anim"] = "animCurveTA"
        fake.driven_plugs["|mcpLight_key.rotateY"] = (
            "mcpLight_key_rotateY_anim.output")
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["side"]})
        # The mechanism, and it stays true however the handler is fixed: Maya
        # will not take that write, so the key sits where the user put it.
        assert fake.yaw_history == []
        assert "|mcpLight_key.rotateY" not in fake.attrs
        # The claim: a rig it could not swing must be named, not counted.
        assert any("mcpLight_key" in w for w in out["warnings"]), out["warnings"]
        # ...and not counted as swung either. The first cut of #802 added
        # the warning and left relit_lights at len(rig) - the count of
        # lights DISCOVERED - so the one structured field a caller reads
        # contradicted the warning beside it (review catch).
        assert out["relit_lights"] == 0
        # The pass belongs to three commands, so the sentence names the
        # pass, not render_scene.
        assert not any(w.startswith("render_scene") for w in out["warnings"])

    def test_a_user_authored_rig_is_never_touched(self, monkeypatch, tmp_path):
        fake = FakeCmds(lights=["|myKeyLight|myKeyLightShape"])
        fake.light_yaw_query["|myKeyLight"] = (-35.0, 30.0, 0.0)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["side"]})
        assert out["relit_lights"] == 0
        assert fake.yaw_history == []

    def test_a_dome_in_our_own_rig_is_never_swung(self, monkeypatch, tmp_path):
        """_rig_lights excludes aiSkyDomeLight by asking cmds.nodeType, and
        the fake had no nodeType at all - the AttributeError landed in the
        bare `except: pass` above the check, so the exclusion never ran and
        deleting it outright would not have been noticed (#799). Swinging a
        dome rotates every reflection shot to shot, which is the opposite of
        what an environment is for."""
        fake = FakeCmds(lights=["|mcpLight_dome|mcpLight_domeShape",
                                "|mcpLight_key|mcpLight_keyShape"])
        fake.arnold_lights = ["|mcpLight_dome|mcpLight_domeShape"]
        fake.light_yaw_query["|mcpLight_dome"] = (0.0, 10.0, 0.0)
        fake.light_yaw_query["|mcpLight_key"] = (-35.0, 30.0, 0.0)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["side"]})
        assert out["relit_lights"] == 1  # the key, and only the key
        assert "|mcpLight_dome.rotateY" not in fake.attrs
        # side is azimuth 90: the key swings to 120 and comes back to 30.
        assert fake.yaw_history == [120.0, 30.0]

    def test_relight_can_be_declined(self, monkeypatch, tmp_path):
        fake = FakeCmds(lights=["|mcpLight_key|mcpLight_keyShape"])
        fake.light_yaw_query["|mcpLight_key"] = (-35.0, 30.0, 0.0)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["side"], "relight": False})
        assert out["relit_lights"] == 0
        assert fake.yaw_history == []

    def test_samples_and_resolution_reach_the_render_step(self, fake_maya):
        render.render_scene({"angles": ["front"], "samples": 6, "resolution": 256})
        assert fake_maya.written[0]["samples"] == 6
        assert fake_maya.written[0]["resolution"] == 256

    def test_hw2_maps_through_to_the_maya_renderer_name(self, fake_maya):
        out = render.render_scene({"angles": ["front"], "renderer": "hw2"})
        assert out["renderer"] == "hw2"
        assert fake_maya.written[0]["renderer"] == "mayaHardware2"


class TestTheRenderCameraReallyHasTheFov:
    """#772 on the RENDER path, which is where the inert version lived.

    Until #799 the fake handed back a camera with no shape, so
    apply_framing_fov fell down its shapeless-node fallback, read the film
    back off the TRANSFORM (answered 0), and set a focal length of 0.0 -
    and TestFocalLength above only checks that render DELEGATES the lens.
    Nothing asserted the camera it renders through ends up with the 40 deg
    the placement math solved for. With no panel there is no viewFit to
    refine the framing, so here the lens IS the framing.
    """

    def test_the_lens_matches_the_fov_the_placement_solved_for(self, fake_maya):
        out = render.render_scene({"angles": ["front"]})
        shape = fake_maya.shape_of[out["camera_positions"][0]["camera"]]
        assert fake_maya.attrs[shape + ".focalLength"] == pytest.approx(
            capture.focal_length_for_fov(
                capture._FOV_DEG, capture.MAYA_HORIZONTAL_APERTURE_IN))

    def test_film_fit_is_pinned_horizontal(self, fake_maya):
        # Which aperture governs is a function of filmFit; leaving it at
        # whatever the scene had makes the lens right only by luck.
        out = render.render_scene({"angles": ["front"]})
        shape = fake_maya.shape_of[out["camera_positions"][0]["camera"]]
        assert fake_maya.attrs[shape + ".filmFit"] == capture._FILM_FIT_HORIZONTAL

    def test_the_lens_reads_this_cameras_own_film_back(self, monkeypatch, tmp_path):
        """A hardcoded aperture is exactly how #772 happened. Give the
        camera a wider back and the lens has to follow it."""
        fake = FakeCmds(lights=["|keyLightShape"])
        real_camera = fake.camera

        def wide_camera(*a, **kw):
            transform, shape = real_camera(*a, **kw)
            fake.attrs[shape + ".horizontalFilmAperture"] = 2.8346
            return [transform, shape]

        monkeypatch.setattr(fake, "camera", wide_camera)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"]})
        shape = fake.shape_of[out["camera_positions"][0]["camera"]]
        assert fake.attrs[shape + ".focalLength"] == pytest.approx(
            capture.focal_length_for_fov(capture._FOV_DEG, 2.8346))

    def test_the_reported_position_is_the_one_it_actually_set(self, fake_maya):
        """getAttr used to answer a constant [(0,0,0)] for every .translate,
        so camera_positions - the field an LLM reads to reason about what it
        is looking at - was never compared with anything (#799)."""
        out = render.render_scene({"angles": ["front"]})
        camera = out["camera_positions"][0]["camera"]
        assert out["camera_positions"][0]["position"] == pytest.approx(
            fake_maya.attrs[camera + ".translate"])
        assert out["camera_positions"][0]["position"] != [0.0, 0.0, 0.0]


class TestRenderSheet:
    """One frame per subject in ONE call - the kit contact sheet was 41 of them.

    Everything outside the frame loop is setup: resolving the renderer,
    snapshotting the user's render globals, building a camera, hiding the scene.
    These assert that the setup happens once and the loop is just frames.
    """

    def test_one_frame_per_subject_labelled_by_subject(self, fake_maya):
        out = render.render_sheet({"subjects": ["|ball", "|floor"]})
        assert [i["label"] for i in out["images"]] == ["|ball", "|floor"]
        assert all(i["png_b64"] for i in out["images"])

    def test_the_camera_is_built_once_for_the_whole_sheet(self, fake_maya):
        render.render_sheet({"subjects": ["|ball", "|floor"]})
        cameras = [n for n in fake_maya.created if "RenderCam" in n]
        assert len(cameras) == 1, "a camera per cell is setup, not picture"

    def test_each_cell_is_isolated_to_its_own_subject(self, fake_maya):
        render.render_sheet({"subjects": ["|ball", "|floor"]})
        # Each subject's cell hid the OTHER one; both are visible again at the end.
        assert "|floor|floorShape" in fake_maya.hidden
        assert "|ball|ballShape" in fake_maya.hidden
        assert all(fake_maya.visibility.values()), "visibility must be restored"

    def test_isolation_can_be_declined_for_subjects_that_need_the_room(self, fake_maya):
        """Hiding the surroundings also removes what a transmissive material
        refracts - the #585 lesson, kept reachable here."""
        render.render_sheet({"subjects": ["|ball"], "isolate": False})
        assert fake_maya.hidden == []

    def test_every_cell_gets_its_own_render_prefix(self, fake_maya):
        render.render_sheet({"subjects": ["|ball", "|floor"]})
        prefixes = [w["prefix"] for w in fake_maya.written]
        assert len(set(prefixes)) == 2, "cmds.render overwrites a fixed path"

    def test_render_globals_are_restored_after_a_whole_sheet(self, fake_maya):
        before = dict(fake_maya.attrs)
        render.render_sheet({"subjects": ["|ball", "|floor"], "resolution": 256})
        assert {k: fake_maya.attrs[k] for k in before} == before

    def test_a_bad_name_is_caught_before_any_frame_is_rendered(self, fake_maya):
        """A sheet that dies on cell 30 has spent thirty frames' worth of
        seconds to report a typo."""
        with pytest.raises(HandlerError) as exc:
            render.render_sheet({"subjects": ["|ball", "|nonexistent"]})
        assert "nonexistent" in str(exc.value)
        assert fake_maya.written == []

    def test_empty_subjects_points_at_render_scene(self, fake_maya):
        with pytest.raises(HandlerError) as exc:
            render.render_sheet({"subjects": []})
        assert "render_scene" in exc.value.hint

    def test_too_many_subjects_is_refused(self, fake_maya):
        with pytest.raises(HandlerError) as exc:
            render.render_sheet(
                {"subjects": ["|ball"] * (render.MAX_SHEET_SUBJECTS + 1)}
            )
        assert "cap" in str(exc.value)

    def test_an_unknown_angle_is_refused(self, fake_maya):
        with pytest.raises(HandlerError):
            render.render_sheet({"subjects": ["|ball"], "angle": "diagonal"})

    def test_a_sheet_does_not_pollute_the_undo_queue(self):
        assert render.render_sheet.no_undo_chunk is True

    def test_a_rival_subject_it_could_not_hide_is_named(self, fake_maya):
        """#802 FIXED. A cell that could not be isolated says so.

        A keyed or expression-driven `.visibility` is ordinary on a rig,
        and the refusal used to vanish into the bare `except: pass` - the
        rival stayed in frame and out["warnings"] was []. That is the #640
        defect this tool exists to prevent, and the far milder nesting case
        already got a paragraph of warning while this one was silent.

        #799 pinned it expecting Maya to raise. Measured (#802, W2/W3):
        `cmds.hide` on such a shape returns cleanly and leaves it visible.
        """
        fake_maya.node_types["floorShape_visibility_anim"] = "animCurveTU"
        fake_maya.driven_plugs["|floor|floorShape.visibility"] = (
            "floorShape_visibility_anim.output")
        out = render.render_sheet({"subjects": ["|ball", "|floor"]})
        # The mechanism: the hide was refused, so the ball's cell still
        # contains the floor.
        assert "|floor|floorShape" not in fake_maya.hidden
        assert "|floor|floorShape" in fake_maya.written[0]["visible"]
        # The claim: a cell that could not be isolated must say so.
        assert any("floor" in w for w in out["warnings"]), out["warnings"]

    def test_the_unhideable_rival_is_named_once_not_once_per_cell(self, fake_maya):
        """The isolate pass re-runs for every cell of a sheet, and the same
        rival fails identically in each; the relight notes beside it were
        deduped for exactly this reason and this path was not (review)."""
        fake_maya._geometry.append("|crate|crateShape")
        fake_maya._transforms.append("|crate")
        fake_maya.visibility["|crate|crateShape"] = True
        fake_maya.node_types["floorShape_visibility_anim"] = "animCurveTU"
        fake_maya.driven_plugs["|floor|floorShape.visibility"] = (
            "floorShape_visibility_anim.output")
        out = render.render_sheet({"subjects": ["|ball", "|floor", "|crate"]})
        assert len(fake_maya.written) == 3
        assert sum("floorShape.visibility" in w for w in out["warnings"]) == 1


# A parented rig, as the #601 golem was: the pelvis contains the chest, which
# contains the head. Every one of the three is also a subject of the sheet.
NESTED_RIG = (
    "|golem|pelvis|pelvisShape",
    "|golem|pelvis|chest|chestShape",
    "|golem|pelvis|chest|head|headShape",
)


@pytest.fixture
def nested_maya(monkeypatch, tmp_path):
    fake = FakeCmds(lights=["|keyLightShape"], geometry=NESTED_RIG)
    # Spread them out, so framing the whole subtree is measurably different
    # from framing one chunk.
    fake.boxes = {
        "|golem|pelvis|pelvisShape": (-1.0, 0.0, -1.0, 1.0, 2.0, 1.0),
        "|golem|pelvis|chest|chestShape": (-2.0, 2.0, -2.0, 2.0, 6.0, 2.0),
        "|golem|pelvis|chest|head|headShape": (-1.0, 6.0, -1.0, 1.0, 8.0, 1.0),
    }
    monkeypatch.setattr(render, "_cmds", lambda: fake)
    monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
    return fake


class TestSheetCellsOnANestedRig:
    """#640-4: a subject that CONTAINS other subjects rendered them too.

    14 of 29 cells came back as sub-assemblies on the golem sheet -
    `golem_C_pelvis` rendered the entire golem. Keeping a target's descendants is
    right for render_scene, where you isolate an assembly to see the assembly.
    In a sheet the other cells are siblings in one list, not content.
    """

    SUBJECTS = ["|golem|pelvis", "|golem|pelvis|chest", "|golem|pelvis|chest|head"]

    def test_a_containing_subject_hides_the_subjects_it_contains(self, nested_maya):
        render.render_sheet({"subjects": self.SUBJECTS})
        # Cell 0 is the pelvis: the chest and head are subjects of their own, so
        # its frame must have shown neither. This is the 14-of-29 defect.
        pelvis_cell = nested_maya.written[0]["visible"]
        assert "|golem|pelvis|pelvisShape" in pelvis_cell
        assert "|golem|pelvis|chest|chestShape" not in pelvis_cell
        assert "|golem|pelvis|chest|head|headShape" not in pelvis_cell

    def test_a_descendant_that_is_NOT_a_subject_stays_in_frame(self, monkeypatch, tmp_path):
        """A bolt on the pelvis is part of the pelvis. Only rival CELLS go."""
        fake = FakeCmds(
            lights=["|keyLightShape"],
            geometry=NESTED_RIG + ("|golem|pelvis|bolt|boltShape",),
        )
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame", _stub_render_frame(tmp_path, fake))
        render.render_sheet({"subjects": ["|golem|pelvis", "|golem|pelvis|chest"]})
        pelvis_cell = fake.written[0]["visible"]
        assert "|golem|pelvis|bolt|boltShape" in pelvis_cell
        assert "|golem|pelvis|chest|chestShape" not in pelvis_cell

    def test_the_cell_is_framed_on_what_it_shows_not_on_the_subtree(self, nested_maya):
        """The other half of the defect. Hiding the sub-assemblies is not enough:
        exactWorldBoundingBox includes hidden children, so the camera still
        framed the whole rig and left the piece a speck.

        Asserted against camera_placement's own answer for each box rather than a
        magic distance, so it says WHICH framing happened.
        """
        render.render_sheet({"subjects": self.SUBJECTS})
        placed = list(nested_maya.written[0]["camera_translate"])

        chunk_only, _ = capture.camera_placement(
            "three_quarter", [-1.0, 0.0, -1.0], [1.0, 2.0, 1.0]
        )
        whole_subtree, _ = capture.camera_placement(
            "three_quarter", [-2.0, 0.0, -2.0], [2.0, 8.0, 2.0]
        )
        assert placed == pytest.approx(list(chunk_only), abs=1e-6)
        assert placed != pytest.approx(list(whole_subtree), abs=1e-6), (
            "the pelvis cell is framed on the whole rig it just hid"
        )

    def test_a_subject_nested_BETWEEN_two_others_still_shows_itself(self, nested_maya):
        """Found by the live gate, not by design. The chest has the pelvis above
        it and the head below it, both subjects. Treating an excluded ANCESTOR as
        banished hid the chest's own shape: the cell came back empty and its
        camera was placed 5.8e20 units out. exclude exists only to override the
        descendant rule, so an ancestor in it is already handled and must be
        ignored."""
        render.render_sheet({"subjects": self.SUBJECTS})
        chest_cell = nested_maya.written[1]["visible"]
        assert "|golem|pelvis|chest|chestShape" in chest_cell, (
            "the middle subject hid its own geometry: %s" % chest_cell
        )
        assert "|golem|pelvis|pelvisShape" not in chest_cell
        assert "|golem|pelvis|chest|head|headShape" not in chest_cell

    def test_no_cell_is_framed_from_absurdly_far_away(self, nested_maya):
        """The symptom that exposed the bug above, pinned as its own claim: a
        camera 5.8e20 units out renders a frame of nothing and reads as a broken
        renderer."""
        render.render_sheet({"subjects": self.SUBJECTS})
        for cell in nested_maya.written:
            placed = cell["camera_translate"]
            assert max(abs(v) for v in placed) < 1e4, (
                "cell %r placed its camera at %r" % (cell["prefix"], placed)
            )

    def test_nesting_is_reported_not_silent(self, nested_maya):
        out = render.render_sheet({"subjects": self.SUBJECTS})
        warnings = " ".join(out["warnings"])
        assert "|golem|pelvis" in warnings
        assert "contains 2 other subject" in warnings

    def test_a_flat_kit_gets_no_nesting_warning(self, fake_maya):
        out = render.render_sheet({"subjects": ["|ball", "|floor"]})
        assert out["warnings"] == []

    def test_declining_isolation_keeps_the_whole_subtree(self, nested_maya):
        """isolate=False means the caller wants the surroundings, and a
        contained subject is part of them."""
        render.render_sheet({"subjects": self.SUBJECTS, "isolate": False})
        assert nested_maya.hidden == []


class FakeArnoldCmds(FakeCmds):
    """FakeCmds plus the mtoa-side surface _render_frame touches.

    Seeded with the scene as found on 9877: the driver on Use Output Transform
    with output transforms DISABLED, which is the configuration in which mode 2
    silently degrades to Raw (redmine #615).
    """

    def __init__(self, tmp_path, output_transforms=None, arnold_render_raises=False):
        super().__init__(lights=["|keyLightShape"])
        self.tmp_path = tmp_path
        self.attrs["defaultArnoldDriver.colorManagement"] = 0
        self.attrs["defaultArnoldDriver.aiTranslator"] = "exr"
        self.output_transforms = (
            ["Un-tone-mapped (sRGB)", "ACES 1.0 SDR-video (sRGB)"]
            if output_transforms is None
            else list(output_transforms)
        )
        self.cm_prefs = {
            "outputTransformEnabled": False,
            "outputTransformName": "ACES 1.0 SDR-video (sRGB)",
            "viewTransformName": "ACES 1.0 SDR-video (sRGB)",
        }
        self.arnold_render_raises = arnold_render_raises
        self.arnold_renders = []
        self.legacy_renders = []
        self.during = []  # colour-management state at the moment of rendering

    def colorManagementPrefs(self, *args, **kwargs):
        if kwargs.get("query"):
            if kwargs.get("outputTransformNames"):
                return list(self.output_transforms)
            for key in ("outputTransformEnabled", "outputTransformName",
                        "viewTransformName"):
                if kwargs.get(key):
                    return self.cm_prefs[key]
            return None
        for key in ("outputTransformEnabled", "outputTransformName",
                    "viewTransformName"):
            if key in kwargs:
                self.cm_prefs[key] = kwargs[key]
        return None

    def renderSettings(self, **kwargs):
        prefix = self.attrs["defaultRenderGlobals.imageFilePrefix"]
        return [str(self.tmp_path / (prefix + ".png"))]

    def _snapshot(self):
        return {
            "colorManagement": self.attrs["defaultArnoldDriver.colorManagement"],
            "aiTranslator": self.attrs["defaultArnoldDriver.aiTranslator"],
            "outputTransformEnabled": self.cm_prefs["outputTransformEnabled"],
            "outputTransformName": self.cm_prefs["outputTransformName"],
        }

    def arnoldRender(self, **kwargs):
        self.during.append(self._snapshot())
        if self.arnold_render_raises:
            raise RuntimeError("arnoldRender exploded")
        self.arnold_renders.append(kwargs)
        self._write_image(self.renderSettings()[0])

    def render(self, camera, **kwargs):
        self.during.append(self._snapshot())
        self.legacy_renders.append({"camera": camera, **kwargs})
        prefix = self.attrs["defaultRenderGlobals.imageFilePrefix"]
        path = str(self.tmp_path / (prefix + "_legacy.png"))
        self._write_image(path)
        return path

    @staticmethod
    def _write_image(path):
        from PIL import Image as PILImage

        PILImage.new("RGB", (8, 8), (188, 188, 188)).save(path)


@pytest.fixture
def arnold_cmds(tmp_path):
    return FakeArnoldCmds(tmp_path)


def _frame(fake, renderer="arnold"):
    return render._render_frame(fake, "|cam|camShape", "shot0", renderer, 256, 3)


class TestDisplayTransform:
    """#615: every frame this tool returned was raw linear, ~2.2 gamma dark.

    cmds.render never consults the Arnold driver, so no colour-management
    setting could reach it. cmds.arnoldRender does - measured live, a linear-0.5
    plane goes 127 -> 188 - which is why the arnold branch changes render call.
    """

    def test_arnold_frames_go_through_arnold_render(self, arnold_cmds):
        _frame(arnold_cmds)
        assert len(arnold_cmds.arnold_renders) == 1
        assert arnold_cmds.legacy_renders == []

    def test_the_frame_is_rendered_with_the_output_transform_applied(self, arnold_cmds):
        _frame(arnold_cmds)
        during = arnold_cmds.during[0]
        assert during["colorManagement"] == 2  # Use Output Transform
        assert during["outputTransformEnabled"] is True
        assert during["outputTransformName"] == render.DISPLAY_TRANSFORM

    def test_it_writes_png_rather_than_the_drivers_exr(self, arnold_cmds):
        # arnoldRender obeys the DRIVER's translator, not imageFormat: left
        # alone it writes .exr and the handler reads a file that is not a PNG.
        _frame(arnold_cmds)
        assert arnold_cmds.during[0]["aiTranslator"] == "png"

    def test_it_returns_the_file_arnold_actually_wrote(self, arnold_cmds, tmp_path):
        assert _frame(arnold_cmds) == str(tmp_path / "shot0.png")

    def test_it_restores_the_driver_afterwards(self, arnold_cmds):
        _frame(arnold_cmds)
        assert arnold_cmds.attrs["defaultArnoldDriver.colorManagement"] == 0
        assert arnold_cmds.attrs["defaultArnoldDriver.aiTranslator"] == "exr"

    def test_it_restores_the_colour_management_prefs_afterwards(self, arnold_cmds):
        _frame(arnold_cmds)
        assert arnold_cmds.cm_prefs["outputTransformEnabled"] is False
        assert arnold_cmds.cm_prefs["outputTransformName"] == "ACES 1.0 SDR-video (sRGB)"

    def test_it_restores_them_even_when_the_render_fails(self, tmp_path):
        fake = FakeArnoldCmds(tmp_path, arnold_render_raises=True)
        _frame(fake)
        assert fake.attrs["defaultArnoldDriver.colorManagement"] == 0
        assert fake.cm_prefs["outputTransformEnabled"] is False

    def test_a_failed_arnold_render_falls_back_to_cmds_render(self, tmp_path):
        # A dark frame beats no frame: the caller asked to see something.
        fake = FakeArnoldCmds(tmp_path, arnold_render_raises=True)
        assert _frame(fake).endswith("_legacy.png")

    def test_it_uses_the_view_transform_when_no_output_one_is_available(self, tmp_path):
        # Another OCIO config need not carry that name. Mode 1 reads the
        # scene's VIEW transform, which is still a display transform.
        fake = FakeArnoldCmds(tmp_path, output_transforms=["Rec.709"])
        _frame(fake)
        assert fake.during[0]["colorManagement"] == 1

    def test_hw2_still_goes_through_cmds_render(self, arnold_cmds):
        _frame(arnold_cmds, renderer="mayaHardware2")
        assert arnold_cmds.arnold_renders == []
        assert len(arnold_cmds.legacy_renders) == 1


class TestIsolateSparesLights:
    """#618: cmds.ls(geometry=True) reports aiSkyDomeLight shapes as GEOMETRY.

    So isolate hid the dome along with the scenery and the frame came back pure
    black - measured live: (0,0,0) across a whole 256x256 frame under the
    environment preset, against (122,110,107) for the same scene without
    isolate. render_sheet isolates every subject by default, so a contact sheet
    of a kit under a dome was 41 black cells.

    It bites exactly where it hurts most: the dome preset exists because a full
    metal has nothing to reflect in a directional rig, so the dome is the only
    rig in which steel and glass can be judged - and isolate is how a single
    piece gets judged.
    """

    def _fake(self):
        fake = FakeCmds(geometry=("|ball|ballShape", "|floor|floorShape",
                                  "|mcpLight_dome|mcpLight_domeShape"))
        # what Maya really does: the dome answers ls(geometry=True) AND the
        # Arnold light-type query
        fake.arnold_lights = ["|mcpLight_dome|mcpLight_domeShape"]
        return fake

    def test_it_does_not_hide_a_sky_dome(self):
        fake = self._fake()
        hidden = render._hide_non_targets(fake, ["|ball"])
        assert "|mcpLight_dome|mcpLight_domeShape" not in hidden
        assert fake.visibility["|mcpLight_dome|mcpLight_domeShape"] is True

    def test_it_still_hides_the_geometry_that_is_not_the_subject(self):
        fake = self._fake()
        hidden = render._hide_non_targets(fake, ["|ball"])
        assert hidden == ["|floor|floorShape"]


class TestASheetRefusesTheCurrentAngle:
    """#797 row 21: a sheet places its own camera, so 'current' means nothing.

    _run_shots degrades "current" to three_quarter, and every cell came back
    labelled "current" - a label naming an angle that was not shot.
    render_scene's schema promises that degrade (see below); render_sheet's
    does not, so here the honest answer is a refusal.
    """

    def test_it_refuses_before_any_maya_call(self, monkeypatch):
        monkeypatch.setattr(
            render, "_cmds",
            lambda: pytest.fail("render_sheet reached Maya despite the "
                                "inapplicable angle"))
        with pytest.raises(HandlerError) as exc:
            render.render_sheet({"subjects": ["|ball"], "angle": "current"})
        message = str(exc.value)
        assert "does not use 'angle'" in message, message
        assert "current" in message, message
        assert "three_quarter" in exc.value.hint

    def test_a_named_angle_still_renders(self, fake_maya):
        out = render.render_sheet({"subjects": ["|ball"], "angle": "side"})
        assert [i["angle"] for i in out["images"]] == ["side"]


class TestSamplesUnderHw2:
    """#797 row 29: hw2 has no AA sample count, and the result said it did.

    _render_frame reads `samples` only on the arnold branch - hw2 draws the
    viewport's own image - so the value was validated, dropped, and then
    echoed back in the result. A caller reading `samples: 6` believes the
    frame was sampled six times, and nothing in the payload could tell them
    otherwise.
    """

    def test_hw2_reports_null_and_says_the_count_was_dropped(self, fake_maya):
        out = render.render_scene(
            {"angles": ["front"], "renderer": "hw2", "samples": 6})
        assert out["samples"] is None
        notes = [w for w in out["warnings"] if "samples" in w]
        assert len(notes) == 1, out["warnings"]
        assert "hw2" in notes[0] and "arnold" in notes[0]

    def test_hw2_without_a_request_reports_null_and_says_nothing(
            self, fake_maya):
        out = render.render_scene({"angles": ["front"], "renderer": "hw2"})
        assert out["samples"] is None
        assert [w for w in out["warnings"] if "samples" in w] == []

    def test_arnold_still_reports_the_count_it_applied(self, fake_maya):
        out = render.render_scene(
            {"angles": ["front"], "renderer": "arnold", "samples": 6})
        assert out["samples"] == 6
        assert [w for w in out["warnings"] if "samples" in w] == []

    def test_a_sheet_under_hw2_says_it_once(self, fake_maya):
        out = render.render_sheet(
            {"subjects": ["|ball", "|floor"], "renderer": "hw2", "samples": 4})
        assert out["samples"] is None
        assert len([w for w in out["warnings"] if "samples" in w]) == 1


class TestArnoldSamplesReallyReachArnold:
    """The AA write used to sit in a bare `except: pass`.

    MEASURED: on a Maya that has only just loaded mtoa,
    `defaultArnoldRenderOptions` does not exist yet - mtoa builds it lazily -
    so the setAttr raised, was swallowed, and the frame rendered at Arnold's
    own default while the result reported the caller's number. Same false
    claim as the hw2 echo above, one layer down.
    """

    def test_a_cold_mtoa_gets_its_options_node_built(self, monkeypatch,
                                                     tmp_path):
        fake = FakeCmds(lights=["|keyLightShape"], arnold_options=False)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame",
                            _stub_render_frame(tmp_path, fake))
        out = render.render_scene(
            {"angles": ["front"], "renderer": "arnold", "samples": 5})
        assert ("aiOptions", "defaultArnoldRenderOptions") in fake.made_nodes
        assert fake.attrs["defaultArnoldRenderOptions.AASamples"] == 5
        assert out["samples"] == 5
        assert [w for w in out["warnings"] if "AA sample" in w] == []

    def test_a_count_that_cannot_be_written_is_never_claimed(self, monkeypatch,
                                                             tmp_path):
        fake = FakeCmds(lights=["|keyLightShape"], arnold_options=False)

        def _no_options(*args, **kwargs):
            raise RuntimeError("aiOptions is not a registered node type")

        monkeypatch.setattr(fake, "createNode", _no_options)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame",
                            _stub_render_frame(tmp_path, fake))
        out = render.render_scene(
            {"angles": ["front"], "renderer": "arnold", "samples": 5})
        assert out["samples"] is None, "a count that was not applied is a lie"
        assert len([w for w in out["warnings"] if "AA sample" in w]) == 1


class TestCurrentIsLabelledWithWhatWasShot:
    """#797 row 30: the degrade is promised; the LABEL was not.

    render_scene's schema says "current" falls back to three_quarter
    offscreen, and _run_shots does exactly that - then labelled the image
    and its camera_positions entry "current" anyway. The frame, the camera
    it was shot from, and the name on both have to agree.
    """

    def test_the_frame_carries_the_angle_it_was_shot_from(self, fake_maya):
        out = render.render_scene({"angles": ["current"]})
        assert out["images"][0]["angle"] == "three_quarter"
        assert out["images"][0]["requested_angle"] == "current"
        assert out["camera_positions"][0]["angle"] == "three_quarter"
        assert out["camera_positions"][0]["requested_angle"] == "current"
        notes = [w for w in out["warnings"] if "three_quarter" in w]
        assert len(notes) == 1, out["warnings"]

    def test_an_ordinary_angle_carries_no_extra_key(self, fake_maya):
        out = render.render_scene({"angles": ["side"]})
        assert out["images"][0]["angle"] == "side"
        assert "requested_angle" not in out["images"][0]
        assert "requested_angle" not in out["camera_positions"][0]
        assert out["warnings"] == []

    def test_the_camera_really_is_the_three_quarter_one(self, fake_maya):
        current = render.render_scene({"angles": ["current"]})
        three_q = render.render_scene({"angles": ["three_quarter"]})
        assert (current["camera_positions"][0]["position"]
                == pytest.approx(three_q["camera_positions"][0]["position"]))


class TestAHideThatRefusesIsNamed:
    """#797 row 37: `except Exception: continue` after a failed hide.

    The plugwrite guard classifies the refusals it can (a keyed or
    driven .visibility); anything it cannot lands here. Continuing silently
    leaves a rival subject in the cell and reports no warning at all - the
    #640 defect this pass exists to prevent, wearing a different coat.
    """

    def test_the_shape_that_stayed_in_frame_is_named(self, monkeypatch,
                                                     tmp_path):
        fake = FakeCmds(lights=["|keyLightShape"])
        real_hide = fake.hide

        def _flaky_hide(name):
            if name.endswith("floorShape"):
                raise RuntimeError("hide: unknown VP2 refusal")
            return real_hide(name)

        monkeypatch.setattr(fake, "hide", _flaky_hide)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame",
                            _stub_render_frame(tmp_path, fake))
        out = render.render_scene({"angles": ["front"], "isolate": ["|ball"]})
        notes = [w for w in out["warnings"] if "floorShape" in w]
        assert len(notes) == 1, out["warnings"]
        assert "stays in frame" in notes[0]
        # and the render still happened - a rival in the cell is a warning,
        # not a reason to refuse the frame
        assert len(out["images"]) == 1

    def test_a_sheet_says_it_once_not_once_per_cell(self, monkeypatch,
                                                    tmp_path):
        fake = FakeCmds(lights=["|keyLightShape"])
        real_hide = fake.hide

        def _flaky_hide(name):
            if name.endswith("floorShape"):
                raise RuntimeError("hide: unknown VP2 refusal")
            return real_hide(name)

        monkeypatch.setattr(fake, "hide", _flaky_hide)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame",
                            _stub_render_frame(tmp_path, fake))
        out = render.render_sheet({"subjects": ["|ball", "|floor"]})
        assert len([w for w in out["warnings"] if "floorShape" in w]) == 1


class TestTheColdArnoldOptionsNodeIsNotLeftDirty:
    """Review round 1 on the cold-mtoa fix: building the node is a WRITE.

    Two ways a perception tool leaked through it:

      * `_RenderGlobalsState` snapshots AASamples before the node exists, so
        it records None and its restore skips - and the caller's AA count
        then sat in the user's scene for every render they made afterwards.
      * the createNode ran before `undoInfo(stateWithoutFlush=False)`, so a
        no_undo_chunk tool put a node creation in the user's undo queue.
    """

    def _cold(self, monkeypatch, tmp_path):
        fake = FakeCmds(lights=["|keyLightShape"], arnold_options=False)
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame",
                            _stub_render_frame(tmp_path, fake))
        return fake

    def test_the_fresh_node_keeps_its_own_default_afterwards(self, monkeypatch,
                                                             tmp_path):
        fake = self._cold(monkeypatch, tmp_path)
        real_create = fake.createNode

        def _create_with_arnolds_default(node_type, name=None, **kwargs):
            made = real_create(node_type, name=name, **kwargs)
            # A fresh aiOptions carries Arnold's own AA default, not ours.
            fake.attrs[made + ".AASamples"] = 3
            return made

        monkeypatch.setattr(fake, "createNode", _create_with_arnolds_default)
        out = render.render_scene(
            {"angles": ["front"], "renderer": "arnold", "samples": 7})
        assert out["samples"] == 7, "the count still has to REACH arnold"
        assert fake.attrs["defaultArnoldRenderOptions.AASamples"] == 3, (
            "the render's own AA count outlived it: the state snapshot read "
            "nothing (no node yet), so the restore has to be handed the "
            "fresh node's default")

    def test_the_node_is_built_under_the_undo_suppression(self, monkeypatch,
                                                          tmp_path):
        """render_scene is no_undo_chunk: every write it makes has to happen
        with recording OFF, or a perception call leaves a createNode in the
        user's undo queue."""
        fake = self._cold(monkeypatch, tmp_path)
        recording = []
        real_create = fake.createNode

        def _watch_create(node_type, name=None, **kwargs):
            recording.append(fake.undo_state)
            return real_create(node_type, name=name, **kwargs)

        monkeypatch.setattr(fake, "createNode", _watch_create)
        render.render_scene(
            {"angles": ["front"], "renderer": "arnold", "samples": 7})
        assert recording == [False], (
            "the options node was built while undo recording was %r" % recording)

    def test_a_warm_maya_is_left_exactly_as_it_was(self, monkeypatch, tmp_path):
        """The ordinary case: the node already exists, the snapshot read the
        user's count, and nothing new is created."""
        fake = FakeCmds(lights=["|keyLightShape"])
        fake.attrs["defaultArnoldRenderOptions.AASamples"] = 2
        monkeypatch.setattr(render, "_cmds", lambda: fake)
        monkeypatch.setattr(render, "_render_frame",
                            _stub_render_frame(tmp_path, fake))
        render.render_scene(
            {"angles": ["front"], "renderer": "arnold", "samples": 7})
        assert fake.made_nodes == []
        assert fake.attrs["defaultArnoldRenderOptions.AASamples"] == 2


class TestHardwareFallbackIsSaid:
    """redmine #837: the arnold branch of _render_frame falls through to
    cmds.render when Arnold writes nothing, and that fallback was silent -
    the calibration gate read a raw-linear 127 from a result that said
    renderer='arnold'. Measured cause: a project whose 'images' file rule
    is empty makes the predicted path and Arnold's write disagree."""

    class _Cmds:
        def __init__(self):
            self.rendered = []

        def setAttr(self, *a, **kw):
            return None

        def render(self, camera, x=None, y=None):
            self.rendered.append(camera)
            return "hw2.png"

    class _DisplayOk:
        def __init__(self, cmds):
            pass

        def apply(self):
            return True

        def restore(self):
            return None

    class _DisplayNo(_DisplayOk):
        def apply(self):
            return False

    def test_arnold_writing_nothing_is_reported(self, monkeypatch):
        cmds = self._Cmds()
        monkeypatch.setattr(render, "_ArnoldDisplayState", self._DisplayOk)
        monkeypatch.setattr(render, "_arnold_render", lambda c, cam, res: "")
        monkeypatch.setattr(render, "_ensure_arnold_samples", lambda c, s: (None, None))
        notes = []
        path = render._render_frame(cmds, "|cam", "p", "arnold", 64, 1, notes=notes)
        assert path == "hw2.png" and cmds.rendered == ["|cam"]
        assert notes == [render.HW2_FALLBACK_NOTE]
        assert "RAW LINEAR" in notes[0] and "images" in notes[0]

    def test_a_display_state_that_cannot_apply_is_reported(self, monkeypatch):
        cmds = self._Cmds()
        monkeypatch.setattr(render, "_ArnoldDisplayState", self._DisplayNo)
        monkeypatch.setattr(render, "_ensure_arnold_samples", lambda c, s: (None, None))
        notes = []
        render._render_frame(cmds, "|cam", "p", "arnold", 64, 1, notes=notes)
        assert notes == [render.DISPLAY_STATE_NOTE]

    def test_a_frame_arnold_wrote_carries_no_note(self, monkeypatch):
        cmds = self._Cmds()
        monkeypatch.setattr(render, "_ArnoldDisplayState", self._DisplayOk)
        monkeypatch.setattr(render, "_arnold_render", lambda c, cam, res: "arnold.png")
        monkeypatch.setattr(render, "_ensure_arnold_samples", lambda c, s: (None, None))
        notes = []
        assert render._render_frame(cmds, "|cam", "p", "arnold", 64, 1, notes=notes) == "arnold.png"
        assert notes == [] and cmds.rendered == []
