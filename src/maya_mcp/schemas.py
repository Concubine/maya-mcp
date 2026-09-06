"""Result models for maya-mcp tools.

These validate what comes back from the plugin before it reaches the client,
and give every tool a real structured-output schema. Extra keys from newer
plugin versions are ignored rather than fatal.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExecuteResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stdout: str = Field(description="Captured stdout, capped at 8 KB with an explicit notice.")
    stderr: str = Field(description="Captured stderr.")
    result_repr: Optional[str] = Field(
        default=None, description="repr() of the trailing expression, if the code ended in one."
    )
    traceback: Optional[str] = Field(
        default=None,
        description="Complete verbatim Python traceback if the code raised; None on success.",
    )
    namespace_keys: List[str] = Field(
        default_factory=list, description="Names currently defined in the persistent namespace."
    )
    checkpoint: Optional[str] = Field(
        default=None, description="Path of the auto-checkpoint taken when risky=true."
    )
    result_truncated: bool = Field(
        default=False,
        description=(
            "True when result_repr was cut at the cap. A truncated repr will NOT "
            "parse - check this before eval'ing it, and have the code write to a "
            "file or return a summary instead."
        ),
    )
    result_bytes: Optional[int] = Field(
        default=None, description="Full length of the repr before any capping."
    )
    stdout_truncated: bool = Field(default=False)
    stderr_truncated: bool = Field(default=False)


class SceneObject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name, e.g. |group1|golem_torso.")
    type: str = Field(description="Shape node type (mesh, pointLight, ...) or 'group'.")
    tris: Optional[int] = None
    verts: Optional[int] = None
    bbox_min: List[float] = Field(default_factory=list)
    bbox_max: List[float] = Field(default_factory=list)
    material: Optional[str] = None
    parent: Optional[str] = None
    visible: bool = True


class SceneUnits(BaseModel):
    """What the scene's numbers mean. Every measurement is bare without it.

    maya-mcp #634. Maya's internal linear unit is centimetres whatever
    `linear_unit` says, and the FBX exporter writes those internal numbers -
    so `export_metres_per_unit` is what a delivery actually inherits.
    """

    model_config = ConfigDict(extra="ignore")

    linear_unit: str = Field(
        description="The scene's linear unit as Maya reports it (cm, m, mm, in, ...)."
    )
    export_metres_per_unit: Optional[float] = Field(
        default=None,
        description=(
            "Metres one scene unit becomes in an exported FBX, and the number "
            "to size your model by: at 1.0 a 45 cm lamp is 0.45 units and a 2 m "
            "creature is 2. 1.0 (linear_unit 'cm') is the ONLY value that "
            "produces a metre-true delivery and is the convention every mesh "
            "out of this repo is authored under - the scene reads 'cm' while "
            "the numbers mean metres, so trust THIS number and not the unit "
            "string. 100.0 (linear_unit 'm') is the 100x defect of maya-mcp "
            "#629, which no in-Maya measurement can see. Null means the unit "
            "was not recognised - never assume 1.0."
        ),
    )


class SceneGraphResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objects: List[SceneObject]
    total: int = Field(description="Total matching objects before pagination.")
    cursor: Optional[str] = Field(
        default=None, description="Pass back to fetch the next page; None when complete."
    )
    units: Optional[SceneUnits] = Field(
        default=None,
        description="What every bbox above is measured in. Reported on every page.",
    )


class ObjectInfoResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the object queried.")
    transform: Optional[dict] = Field(
        default=None, description="World-space translate/rotate/scale."
    )
    mesh_stats: Optional[dict] = Field(
        default=None,
        description="tris, verts, faces, boundary_edges, nonmanifold_edges, watertight.",
    )
    uvs: Optional[dict] = Field(
        default=None, description="UV set names and count - a summary, never raw UVs."
    )
    shading: Optional[dict] = Field(
        default=None,
        description=(
            "shading_groups, materials, and per_face - per_face=true means "
            "face-level assignment, which is unreliable on boolean output."
        ),
    )
    history: Optional[dict] = Field(
        default=None, description="Construction-history node count and distinct node types."
    )
    units: Optional[SceneUnits] = Field(
        default=None,
        description="What the transform's numbers are measured in. Always present.",
    )


class CheckpointResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    checkpoint_id: str = Field(description="Stem NNN_label; pass to maya_restore_checkpoint.")
    path: str = Field(description="Saved .ma file path.")


class RestoreResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    restored: str
    path: Optional[str] = Field(
        default=None, description="The checkpoint file that was actually opened."
    )
    pre_restore_checkpoint: str = Field(
        description="Auto-checkpoint of the state before restoring, in case you change your mind."
    )
    pre_restore_path: Optional[str] = Field(
        default=None,
        description="File the pre-restore auto-checkpoint went to; pass as path= to undo this restore.",
    )


class UndoResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    undone: int = 0
    redone: int = 0
    requested: int
    skipped: List[str] = Field(
        default_factory=list,
        description=(
            "Maya's own no-op queue entries stepped over without counting "
            "(selectionMaskResetAll, hikDefinitionFileNewCallback, the "
            "nameless entry new_scene leaves) - measured, they change nothing."))
    queue_empty: bool = Field(
        default=False,
        description="True when nothing is left to undo (or redo) afterwards.")


class NewSceneResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    new_scene: bool = Field(description="True when the new scene was created successfully.")
    pre_checkpoint: Optional[str] = Field(
        default=None,
        description="Checkpoint id saved just before the discarded scene was replaced; "
        "pass to maya_restore_checkpoint to recover it.",
    )
    pre_checkpoint_path: Optional[str] = Field(
        default=None,
        description="File that checkpoint went to. An empty scene resolves ids against the "
        "workspace root instead, so this path is the reliable handle to recover it.",
    )
    units: Optional[SceneUnits] = Field(
        default=None,
        description="The unit the new scene was set to - stated, not inherited.",
    )


class OpenSceneResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    opened: str = Field(description="Absolute path to the scene file that was opened.")
    pre_checkpoint: Optional[str] = Field(
        default=None,
        description="Checkpoint id saved just before the discarded scene was replaced; "
        "pass to maya_restore_checkpoint to recover it.",
    )
    pre_checkpoint_path: Optional[str] = Field(
        default=None,
        description="File that checkpoint went to. Opening a scene elsewhere moves which "
        "directory ids resolve in, so this path is the reliable handle to recover it.",
    )


class SaveSceneResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = Field(description="Absolute path where the scene was saved.")


class ResetNamespaceResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reset: bool = Field(description="True when the namespace was reset successfully.")


class NameResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the affected object.")
    warnings: List[str] = Field(default_factory=list)


class GroupResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the new group.")
    pivot: List[float] = Field(description=(
        "World-space rotate pivot the group actually has: the members' "
        "bounding-box centre by default (Maya's choice), or the origin when "
        "pivot='origin'. A later rotate or scale on the group turns about it."
    ))
    children: List[str] = Field(description=(
        "The members' canonical long names inside the group, in the order "
        "given - a member may have been renamed if a sibling held its name."
    ))
    warnings: List[str] = Field(default_factory=list)


class PrimitiveResult(NameResult):
    """What create_primitive actually built, not just what it was asked for.

    `divisions` is a multiplier whose per-kind meaning is invisible from the
    call site - divisions=4 on a cylinder buys 80 around and 4 along - so the
    resolved counts come back rather than leaving the caller to re-derive
    them (maya-mcp #669). A result field absent from this model is a field the
    caller never sees (#757), so both are declared here.
    """

    model_config = ConfigDict(extra="ignore")

    subdivisions: Optional[List[int]] = Field(
        default=None,
        description="Subdivision count per axis as built, in this kind's axis "
                    "order (cube [width, height, depth]; plane [width, depth]; "
                    "sphere/cylinder/cone [around, along]; torus [ring, tube]; "
                    "prism/pyramid [along]). Empty for the platonic solids, "
                    "which have no subdivision flags at all.",
    )
    faces: Optional[int] = Field(
        default=None,
        description="Face count of the mesh just built.",
    )


class CurveFormResult(NameResult):
    """What the curve build measured about itself, not just that it ran.

    The whole point of curve-driven authoring (#768) is that the numbers the
    caller wrote are assertable: worst_station_deviation is the worst
    distance from the produced surface to those numbers, as a fraction of
    form_size, so a caller (and the gate) reads conformance straight off the
    result instead of re-deriving it.
    """

    model_config = ConfigDict(extra="ignore")

    faces: int = Field(description="Face count of the mesh just built.")
    verts: int = Field(description="Vertex count of the mesh just built.")
    watertight: bool = Field(description=(
        "True when the mesh has no boundary and no non-manifold edges."))
    stations: int = Field(description=(
        "How many authored stations were measured against the mesh."))
    worst_station_deviation: float = Field(description=(
        "Worst distance from the mesh surface to an authored station, as a "
        "fraction of form_size. Near 0 = the surface passes through your "
        "numbers; large = raise `resolution` or simplify the curve."))
    worst_station: Optional[str] = Field(
        default=None,
        description="Label of the worst station, e.g. 'path[3]' or 'profile[2]@90'.")
    form_size: float = Field(description=(
        "Max authored extent in scene units - the deviation normalizer."))


class TransformedObject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    translate: List[float] = Field(description=(
        "The translate CHANNEL in world space, as Maya's `xform -q -ws -t` "
        "answers it - NOT where the object is once its pivot sits off its "
        "origin: a rotate or scale about such a pivot moves the object and "
        "leaves this number alone (maya-mcp #831). Read world_position / "
        "bbox_center for where it is."))
    rotate: List[float]
    scale: List[float]
    pivot: Optional[List[float]] = Field(
        default=None,
        description="World-space rotate pivot after the call - the point this "
                    "object turns about, which is what a ragdoll reads. Same "
                    "meaning as AssembledObject.pivot.",
    )
    world_position: Optional[List[float]] = Field(
        default=None,
        description="Where the object's ORIGIN is in world space after the "
                    "call: the world matrix's translation row, which carries "
                    "the pivot compensation `translate` leaves out. Equal to "
                    "translate whenever the pivot is at the origin. None only "
                    "from a plugin older than #831.",
    )
    bbox_center: Optional[List[float]] = Field(
        default=None,
        description="Centre of the object's exact world bounding box after "
                    "the call, descendants included - where the GEOMETRY is, "
                    "which differs from world_position when the mesh is "
                    "offset from its origin. None for a node with no geometry "
                    "under it (an empty group, a joint), or from a plugin "
                    "older than #831.",
    )


class TransformResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objects: List[TransformedObject]
    warnings: List[str] = Field(
        default_factory=list,
        description="Includes live-user-edit notices when an object moved outside maya-mcp.",
    )


class DeleteResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deleted: List[str]
    warnings: List[str] = Field(default_factory=list)


class BooleanResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    tris: int
    watertight: bool
    parent: Optional[str] = Field(
        default=None,
        description=(
            "Long name of the result's parent - a's parent, carried across the "
            "rebuild (#638). null means the result is at the scene root."
        ),
    )
    pivot: List[float] = Field(
        default_factory=list,
        description="World-space pivot of the result: a's pivot, carried across (#638).",
    )
    uv_bounds: Optional[List[float]] = Field(
        default=None,
        description=(
            "[u_min, v_min, u_max, v_max] of the result's UVs. Compare with the "
            "atlas patch the chunk belongs to: a boolean brings the cutter's "
            "faces with it, and their UVs are folded into a's bounds (#638)."
        ),
    )
    warnings: List[str] = Field(default_factory=list)
    carved_text: Optional[str] = None


class SculptResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    applied: int
    ops: List[str]
    tris: int
    warnings: List[str] = Field(default_factory=list)
    checkpoint_id: Optional[str] = Field(
        default=None,
        description="Auto-checkpoint id; pass to maya_restore_checkpoint to revert vertex ops.",
    )
    op_results: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description=(
            "One entry per cage op (insert_loop, extrude_edges, "
            "mirror_topology, split), each carrying that op's measured "
            "outcome: insert_loop/split report edges_before/edges_after/"
            "faces_before/faces_after; extrude_edges reports the verified "
            "new_faces count (checked against len(edges)*divisions); "
            "mirror_topology reports shells (must be 1 unless "
            "allow_unmerged was set) and merged_vertices. The other eight "
            "ops (soft_move, inflate_region, displace_noise, smooth, "
            "extrude_faces, bevel_edges, crease_edges, bridge) contribute "
            "nothing here."
        ),
    )


class ArrayResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    names: List[str] = Field(
        description="Canonical long names of the copies, in array order. The source is not listed."
    )
    mode: str
    group: Optional[str] = Field(
        default=None, description="Long name of the group holding the copies, when group_name was given."
    )
    signed_volume: Optional[float] = Field(
        default=None,
        description=(
            "Mirror mode only. Positive means the mirrored copy's faces point "
            "outward. Negative means they point inward - it will render black "
            "or hollow, which looks like a lighting failure and is not one."
        ),
    )
    warnings: List[str] = Field(default_factory=list)


class DeformResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deformer_nodes: List[str]
    baked: bool = False
    warnings: List[str] = Field(default_factory=list)
    max_displacement: float = Field(
        default=0.0,
        description=(
            "How far the furthest vertex actually moved, in scene units, "
            "measured before/after. The proof the deformer did something: a "
            "value near zero against the mesh's own size means the call was a "
            "no-op and warnings says why."
        ),
    )


class RemeshResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    tris: int
    faces: int = Field(
        default=0,
        description=(
            "Face count after the call - the currency target_polycount is in. "
            "polyRetopo lands within its own 10% tolerance of the target "
            "(measured); polyRemesh ignores the target and says so."))
    faces_before: int = Field(default=0, description="Face count before the call.")
    target_polycount: int = Field(default=0, description="What was asked for, echoed.")
    uvs: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "{before, after, transferred}. polyRetopo destroys every UV "
            "(measured: 439 -> 0); with keep_original the UVs are transferred "
            "back from the hidden original by world position and `after` is "
            "non-zero; without it `after` is 0 and warnings say so."))
    method: str = Field(description="Which path ran: polyRetopo, polyRemesh, or polyReduce.")
    warnings: List[str] = Field(default_factory=list)
    original: Optional[str] = Field(
        default=None,
        description=(
            "Long name of the hidden pre-remesh duplicate, when keep_original=true. "
            "A hidden mesh still travels into export_fbx (measured) - delete it "
            "before exporting, or pass keep_original=false."),
    )


class MeshStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tris: int
    verts: int
    faces: int
    boundary_edges: int
    nonmanifold_edges: int
    watertight: bool


class CleanupResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    before: MeshStats
    after: MeshStats
    warnings: List[str] = Field(default_factory=list)


class RenderedFrame(BaseModel):
    model_config = ConfigDict(extra="ignore")

    angle: str = Field(description="The angle the frame was actually shot from.")
    requested_angle: Optional[str] = Field(
        default=None,
        description=(
            "Set only when it differs from `angle`: 'current' has no camera "
            "offscreen and is shot as three_quarter (#797 row 30)."
        ),
    )
    opaque_px: int = Field(
        description="Pixels with a subject in them. Zero means the frame is empty."
    )
    total_px: int
    distinct_colors: int = Field(
        description="One colour edge to edge means an unlit render or a camera inside geometry."
    )
    clipped_fraction: float = Field(
        default=0.0,
        description=(
            "Fraction of the frame blown out (any channel at 250+). Above ~0.15 on a "
            "lit subject the exposure is too hot and surfaces read as flat saturated "
            "colour - which looks exactly like a material failure and is not one."
        ),
    )
    mean_luma: float = Field(
        default=0.0,
        description="Mean luminance 0-255 over the whole frame. Compare between passes, not absolutely.",
    )


class RenderResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    renderer: str = Field(description="Renderer used: 'arnold' or 'hw2'.")
    samples: Optional[int] = Field(
        default=None,
        description="Arnold AA samples applied; null under hw2, which has none.",
    )
    fallback_light: bool = Field(
        description="True if the scene had no light and a temporary key was added for the render."
    )
    frames: List[RenderedFrame]
    warnings: List[str] = Field(
        default_factory=list,
        description=(
            "Handler-side notices about the render session - e.g. the #721 "
            "IPR-hygiene report. Also surfaced as 'note: ' content lines."
        ),
    )


class ViewportState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    panel: str
    show_grid: bool
    show_light_icons: bool
    show_camera_icons: bool
    show_locators: bool
    show_manipulators: bool
    show_texture_placements: bool
    wireframe_on_shaded: bool
    display_lights: str
    camera: Optional[str] = Field(
        default=None,
        description="Canonical long name of the panel's active camera, or None when the "
        "panel reports no camera.",
    )
    # extra="ignore" above is why this field has to exist: a warning the
    # handler sends and the model does not declare is dropped before any
    # caller sees it (#757, and the reason #829 checked).
    warnings: List[str] = Field(
        default_factory=list,
        description="Notes about what this call did and did not change - notably that "
        "captures force grid and icons off for their own frames, so switching one on "
        "here changes only what a human sees in Maya.",
    )


class CameraResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    position: List[float]
    rotation: List[float]
    warnings: List[str] = Field(default_factory=list)


class LightingResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preset: str
    lights: List[str] = Field(description="Canonical long names of the lights created.")
    removed: List[str] = Field(
        default_factory=list, description="Short names of lights deleted by replace_existing."
    )
    checkpoint_id: Optional[str] = Field(
        default=None,
        description="Auto-checkpoint taken before deleting lights; None if nothing was deleted.",
    )
    warnings: List[str] = Field(default_factory=list)


class ReferenceResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref_id: str = Field(description="Id to pass to maya_compare_to_reference.")
    width: int
    height: int
    bytes: int = Field(description="Stored size of the reference image.")


class MaterialResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    material: str = Field(description="Name of the shader node created.")
    shading_group: str
    shader: str
    warnings: List[str] = Field(default_factory=list)


class AssembledObject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the finished object.")
    parts: int = Field(description="How many primitives went into it.")
    tris: int
    verts: int
    faces: int
    shells: int = Field(
        description=(
            "Separate closed pieces. Equals `parts` for a combined object: "
            "assemble unites, it does not weld."
        )
    )
    pivot: Optional[List[float]] = Field(
        default=None,
        description="World-space rotate pivot after the call - the point this "
                    "object turns about. Null means no pivot treatment was "
                    "applied at all, which now happens only when freeze is "
                    "false and the chunk has no entry in `pivots`: a freeze "
                    "moves the pivot to the origin, so a frozen chunk always "
                    "reports where its pivot actually ended up. Otherwise "
                    "this is measured from Maya after the write, the same as "
                    "TransformedObject.pivot.",
    )
    combined: bool


class AssembleResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objects: List[AssembledObject]
    parts: int = Field(description="Primitives built across the whole call.")
    tris: int
    outside_patch: int = Field(
        description=(
            "Parts whose UVs spilled out of their atlas patch - those pieces "
            "read the neighbouring patch, which is another material's pixels."
        )
    )
    atlas: Optional[List[int]] = Field(
        default=None, description="[cols, rows] used, or null when UVs were left alone."
    )
    warnings: List[str] = Field(default_factory=list)


class PbrMapResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file: str = Field(description="The file node reading this map.")
    attr: str = Field(description="Shader attribute the map ends up driving.")
    channel: Optional[str] = Field(
        default=None, description="Channel read for scalar slots; None for colour."
    )
    inverted: bool = Field(description="True when a reverse node sits in the path.")
    raw: bool = Field(
        description=(
            "True when the file is read linearly (colorSpace Raw). Normal and "
            "mask maps are data, not colour: sRGB on them bends the normals and "
            "shifts every roughness value."
        )
    )


class PbrResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meshes: List[str] = Field(description="Meshes now wearing this material.")
    material: str
    shading_group: str
    shader: str
    maps: Dict[str, PbrMapResult] = Field(
        description="What each requested slot ended up connected to."
    )
    nodes: List[str] = Field(description="Every node the call created.")
    warnings: List[str] = Field(default_factory=list)


class TextureRecipeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    recipe: str
    slot: str = Field(description="Semantic slot driven: color, roughness, or normal.")
    nodes: List[str] = Field(description="Texture nodes created by the recipe.")
    replaced: List[str] = Field(
        default_factory=list,
        description=(
            "Nodes of the slot's PREVIOUS network deleted by this call - an "
            "earlier recipe's or assign_pbr's - because nothing else used "
            "them. A node something else still uses is kept and named in "
            "warnings."
        ),
    )
    warnings: List[str] = Field(default_factory=list)


class SessionInfo(BaseModel):
    """Which Maya this server is talking to (#862): the process, the scene
    it holds and whether that scene has unsaved changes, and which copy of
    the plugin answered. Read from the plugin's ping - nothing in the scene
    is touched."""

    model_config = ConfigDict(extra="ignore")

    pid: Optional[int] = Field(default=None, description=(
        "The Maya process answering on this port. A port is not an identity: "
        "check this against the process you launched."))
    host: Optional[str] = None
    port: Optional[int] = None
    scene: Optional[str] = Field(default=None, description=(
        "Path of the open scene; '' for an untitled scene."))
    scene_modified: Optional[bool] = Field(default=None, description=(
        "True when the open scene carries unsaved changes - the flag to read "
        "before killing a Maya. None from a plugin older than #862."))
    cwd: Optional[str] = Field(default=None, description=(
        "The process's working directory: a Maya launched from a repo imports "
        "that repo's plugin. None from a plugin older than #862."))
    uptime_s: Optional[float] = Field(default=None, description=(
        "Seconds since the plugin bound the port - a restart resets it."))
    started_at: Optional[float] = None
    maya: Optional[bool] = Field(default=None, description=(
        "False when the plugin runs headless (no maya.cmds)."))
    plugin_package_dir: Optional[str] = None
    plugin_stamp: Optional[str] = Field(default=None, description=(
        "The commit the loaded plugin copy was stamped with, when deployed."))
    plugin_digest: Optional[str] = None
    plugin_restart_required: Optional[bool] = Field(default=None, description=(
        "True when the files on disk no longer match the code Maya loaded."))


class CombineResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the merged object.")
    inputs: int = Field(description="How many meshes were consumed.")
    parent: Optional[str] = Field(default=None, description=(
        "Where the result lives: names[0]'s parent, carried onto it (#867); "
        "None at the world root. Read back from Maya, not assumed."))
    tris: int
    verts: int
    faces: int
    shells: int = Field(
        description=(
            "Separate closed pieces inside the merged mesh. This should equal "
            "the number of inputs: combine does not weld, so a lower count "
            "means inputs were already touching as one shell."
        )
    )
    pivot: List[float]
    pivot_mode: str
    frozen: bool
    shading: Dict[str, Any] = Field(
        description="The single object-level shading group the result carries."
    )
    warnings: List[str] = Field(default_factory=list)


class UvAtlasMesh(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    uv_bounds: List[float] = Field(
        description="MEASURED (u_min, v_min, u_max, v_max) after packing."
    )
    inside_patch: bool


class UvAtlasResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meshes: List[UvAtlasMesh]
    atlas: List[int] = Field(description="(cols, rows) of the atlas grid.")
    patch: List[int] = Field(description="(col, row) written to; row 0 is the TOP row.")
    patch_rect: List[float]
    margin: float
    projection: str
    normalized: bool
    world_scale: Optional[float] = Field(
        default=None,
        description=(
            "Metres mapped across one patch when fixed-density packing was "
            "used; null when the object was normalised to fill the patch."
        ),
    )
    all_inside: bool = Field(
        description=(
            "False means at least one mesh's UVs escaped its patch, which will "
            "read as another material's pixels bleeding onto the piece."
        )
    )
    # #797 row 10: the APPLIED density, not the requested one. Undeclared
    # here, `extra="ignore"` dropped it on the floor - the handler measured
    # it, protocol.md's result row promised it, and no caller could read it.
    uv_per_metre: Optional[float] = Field(
        default=None,
        description=(
            "UV units per metre applied by world-scale packing; null when the "
            "mesh was normalised to the patch instead."
        ),
    )
    # #797 row 8: protocol.md promised this field; the handler now fills it.
    warnings: List[str] = Field(default_factory=list)


class SkinFacts(BaseModel):
    """Skin records read back OUT OF THE FILE, never from the scene."""

    model_config = ConfigDict(extra="ignore")

    deformers: int = Field(description="SkinCluster deformer records.")
    clusters: int = Field(description="Per-joint cluster records.")
    influenced_models: int = Field(
        description="Distinct joint Models the clusters link.")
    bind_pose_present: bool
    max_weight_sum_error: Optional[float] = Field(
        default=None,
        description=(
            "Furthest any vertex's file-side weight sum sits from 1.0. Null "
            "when the records could not be read - see unavailable_reason, "
            "never a guess."))
    unweighted_file_vertices: int = 0
    max_influences: Optional[int] = Field(
        default=None,
        description=(
            "Most clusters carrying a non-zero weight for any one vertex, in "
            "the file. Above 4, a consumer that caps influences (Unity's "
            "default import) keeps the 4 heaviest and renormalises - see "
            "warnings. Null when the records could not be read."))
    vertices_over_4_influences: int = Field(
        default=0,
        description="File vertices carrying more than 4 non-zero influences.")
    unavailable_reason: Optional[str] = None


class BlendshapeTargetSpec(BaseModel):
    """One morph target to wire: an ordinary same-topology mesh."""

    # #797 row 40: a key the handler never reads is refused at the wire, not
    # dropped by pydantic's default `extra="ignore"` - the #764 lesson at the
    # nested level.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description=(
        "Weight name - becomes the attribute alias, the "
        "set_blendshape_weights key, and the exported Shape record name. "
        "Plain identifier."))
    target_mesh: str = Field(description=(
        "Same-topology copy of the base (maya_duplicate, then sculpt). "
        "CONSUMED: deleted once its deltas are wired."))


class TargetDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    max_delta: float = Field(description=(
        "MEASURED: the furthest any base vertex moves with this weight "
        "driven to 1 through the real deformer - never read off the "
        "target's own vertices. Near zero warns: the target is a duplicate "
        "that was never sculpted."))
    vertex_count: int


class CreateBlendshapeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    blend_shape: str = Field(description=(
        "The deformer node. One per mesh: creating again ADDS targets to "
        "it rather than stacking a second."))
    targets: List[TargetDelta]
    warnings: List[str] = Field(default_factory=list)


class TargetDisplacement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    weight: float = Field(description="Achieved weight, re-read after the write.")
    max_displacement: float = Field(description=(
        "What this weight landing moved, measured in call order against "
        "the state the previous entries left."))


class SetBlendshapeWeightsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    blend_shape: str
    weights: Dict[str, float] = Field(description=(
        "EVERY target's weight re-read from the node - including targets "
        "this call did not name."))
    max_displacement: float = Field(description=(
        "Overall before/after vertex move for the whole call - can be "
        "smaller than a per-target step when shapes oppose."))
    per_target: List[TargetDisplacement]
    warnings: List[str] = Field(default_factory=list)


class ApplyDeltaMushResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    delta_mush: str = Field(description=(
        "The deformer node, at the END of the chain (blendShape -> "
        "skinCluster -> deltaMush). One per mesh; delete_objects it to "
        "remove the relaxation."))
    worst_edge_ratio_before: Optional[float] = Field(default=None, description=(
        "MEASURED at the current pose before the mush: worst current-world "
        "/ bind edge-length ratio (the humanoid gate's tear currency). "
        "~1.0 when the rig is at rest."))
    worst_edge_ratio_after: Optional[float] = Field(default=None, description=(
        "The same ratio re-measured through the mush - the relaxation, "
        "as a number."))
    max_displacement: float = Field(description=(
        "Furthest any vertex moved when the mush landed, measured at the "
        "current pose. ~0 at rest (deltaMush is identity at the bind pose)."))
    warnings: List[str] = Field(default_factory=list)


class AddCorrectiveResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    blend_shape: str
    target: str
    joint: str
    interpolator: str = Field(description=(
        "The poseInterpolator shape driving the weight. One per driver "
        "joint - a second corrective on the same joint adds a pose to it. "
        "delete_objects the interpolator's transform to free every weight "
        "it drives."))
    pose_name: str
    pose_index: int
    weight_at_pose: float = Field(description=(
        "MEASURED: the weight re-read through the real graph with the "
        "joint AT the trigger rotation - ~1.0, or the call would have "
        "refused (an inert wire must not return ok)."))
    weight_at_rest: float = Field(description=(
        "The weight with the joint zeroed - ~0.0; larger warns that "
        "neighbouring poses overlap the neutral."))
    corrective_displacement: float = Field(description=(
        "Furthest any vertex moved when the corrective connected, at the "
        "trigger pose, through the full deformer chain."))
    warnings: List[str] = Field(default_factory=list)


class ShapeRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description=(
        "The weight alias maya_create_blendshape authored, cleaned from "
        "the file's channel name."))
    points: int = Field(description="Delta vertices the Shape record carries.")
    indexes: int = Field(description="Sparse vertex indexes alongside them.")


class ShapeFacts(BaseModel):
    """Blend-shape records read back OUT OF THE FILE, never from the scene."""

    model_config = ConfigDict(extra="ignore")

    blend_deformers: int
    channels: int
    shapes: List[ShapeRecord]
    unavailable_reason: Optional[str] = None


class ClipKeySpec(BaseModel):
    """One key of a clip: the phase-1 pose map at a moment in time."""

    time_s: float = Field(description=(
        "Seconds from the clip start. The first key must be at 0.0; times "
        "must be strictly increasing and should land on frames at the "
        "clip's fps."))
    rotations: Optional[Dict[str, List[float]]] = Field(
        default=None, description=(
            "Joint name -> [rx, ry, rz] DEGREES, local - exactly "
            "pose_skeleton's currency."))
    blend_weights: Optional[Dict[str, float]] = Field(
        default=None, description=(
            "Blendshape target name -> 0..1 - a blink in an idle, a bulge "
            "synced to a step."))
    root_position: Optional[List[float]] = Field(
        default=None, description=(
            "World position for the ROOT joint - the pelvis bob an honest "
            "walk needs, or authored root motion. Root only; bones do not "
            "translate."))


class ClipKeyMeasure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time_s: float
    max_displacement: float = Field(description=(
        "MEASURED at this key's frame against the evaluated first key - "
        "the scene's time was driven there and the vertices re-read."))


class BackFillReport(BaseModel):
    """Channels this clip introduced, pinned at rest across the clips that
    predate them - so those clips measure exactly what they measured when
    they were authored."""

    model_config = ConfigDict(extra="ignore")

    clips: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)


class AuthorClipResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root: str
    clip: str
    fps: int
    duration_s: float = Field(description=(
        "Re-read from the authored curves, never echoed."))
    frames: int = Field(description="Baked frame count: round(d*fps)+1.")
    keyed_joints: int
    keyed_weight_channels: List[str]
    root_position_keyed: bool
    interpolation: str
    loop: bool
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
    held_channels: List[str] = Field(default_factory=list, description=(
        "Channels this clip animates but does not key at one of its own "
        "boundary frames - pinned at the clip's own held value there so its "
        "authored motion is preserved, never at rest. Pinning rest would "
        "invent motion this clip never authored. padded_channels is the "
        "sibling case where rest is the honest pin because this clip never "
        "keys the channel at all."))
    back_filled: BackFillReport = Field(default_factory=BackFillReport,
                                        description=(
        "Channels this clip introduced, pinned at rest across earlier "
        "clips. Never a change to their motion - a restoration of it."))
    replaced: Optional[str] = Field(
        default=None, description=(
            "The clip this call re-authored (same name), re-appended at "
            "the tail. None for a new name."))
    per_key: List[ClipKeyMeasure]
    warnings: List[str] = Field(default_factory=list)


class DeleteClipResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root: str
    clip: Optional[str] = Field(default=None, description=(
        "Names ONE clip - the one removed on a named partial delete. When "
        "`name` was omitted and several clips existed, every one of them "
        "was torn down, but `clip` names only the FIRST of them (the "
        "pre-delete list, index 0); it does not enumerate the delete. Read "
        "`clips` (empty after a bulk delete) and `warnings` for the full "
        "story."))
    clips: List[str] = Field(default_factory=list, description=(
        "The clips left on the rig, in timeline order."))
    deleted_curves: int
    max_displacement: float
    warnings: List[str] = Field(default_factory=list)


class RetargetClipResult(BaseModel):
    """A mocap file's motion baked onto a `create_skeleton` biped (#774).

    Once this returns, the clip is indistinguishable from one `author_clip`
    produced - `preview_clip`/`measure_clip`/`delete_clip`/multi-take
    `export_fbx` all read it unchanged.
    """

    model_config = ConfigDict(extra="ignore")

    clip: str = Field(description="The clip name, as authored.")
    root: str = Field(description="Skeleton root joint the clip was baked onto.")
    frames: int = Field(description="Baked frame count.")
    fps: int = Field(description=(
        "The bake rate actually used - the nearest Maya time unit to the "
        "source capture's own rate when `fps` was left unset."))
    source_joints: int = Field(description=(
        "Joint count in the source mocap file (parsed BVH hierarchy, or "
        "imported FBX skeleton) - not the target rig's own joint count."))
    measures: dict = Field(description=(
        "measure_clip's (#773) full summary for the freshly-baked clip: "
        "per-joint kinematics, inferred contact runs and slide, L/R "
        "symmetry, loop closure. Every relative threshold in it is a "
        "fraction of RIG HEIGHT, the #773 convention - read `thresholds` "
        "inside this dict for the derived absolute numbers."))
    padded_channels: List[str] = Field(default_factory=list, description=(
        "Channels other clips on this rig declare and the bake does not "
        "cover - keyed at rest at this take's own boundary frames so the "
        "take is self-contained (#718's rule, run by this producer since "
        "#798; author_clip's field of the same name)."))
    held_channels: List[str] = Field(default_factory=list, description=(
        "Channels pinned at this take's own held value at a boundary it "
        "did not key - normally empty for a bake, which keys every frame."))
    back_filled: BackFillReport = Field(default_factory=BackFillReport,
                                        description=(
        "The baked joints (and the root's translation), pinned at their "
        "stance rest across every EARLIER clip's range so those clips "
        "measure exactly what they measured before this take existed."))
    warnings: List[str] = Field(default_factory=list)


class CleanClipResult(BaseModel):
    """Deterministic clip improvement with before/after numbers (#774).

    Two independent passes - `filter` (Savitzky-Golay smoothing) and
    `lock_contacts` (pin inferred ground-contact runs, re-solve the leg) -
    each optional, each measured. Any metric that got WORSE after cleanup is
    named in `warnings`, never turned into a failure: this call reports, the
    caller (or the eval gate) judges.
    """

    model_config = ConfigDict(extra="ignore")

    clip: str = Field(description="The clip that was cleaned.")
    root: str = Field(description="Skeleton root joint carrying the clip.")
    passes: List[str] = Field(description=(
        "Which of 'filter'/'lock_contacts' actually ran (a pass with "
        "nothing to do, e.g. no contact run detected, is still listed if "
        "it was enabled)."))
    before: dict = Field(description=(
        "measure_clip's (#773) full summary taken BEFORE either pass ran. "
        "Every relative threshold in it is a fraction of RIG HEIGHT, the "
        "#773 convention."))
    after: dict = Field(description=(
        "The same measure_clip summary taken AFTER both passes ran - "
        "compare against `before` to see what changed. Thresholds are "
        "fractions of rig height, same convention as `before`."))
    checkpoint_id: str = Field(description=(
        "Auto-checkpoint saved just before either pass mutated the scene; "
        "pass to maya_restore_checkpoint to undo this cleanup."))
    warnings: List[str] = Field(default_factory=list)


class TakeRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    duration_s: Optional[float] = None
    start_s: Optional[float] = Field(default=None, description=(
        "Where the take starts on the file's timeline, from its LocalTime "
        "ticks. Several takes share one timeline (#718)."))
    stop_s: Optional[float] = None


class AnimCurveTarget(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target: Optional[str] = Field(description=(
        "The joint (Model) or blendshape channel the curves drive."))
    property: str
    curves: int
    key_count: Optional[int] = None
    duration_s: Optional[float] = None
    take: Optional[str] = Field(default=None, description=(
        "The name of the AnimationStack (take) this curve record is "
        "attributed to, resolved structurally through the "
        "AnimationCurveNode -> AnimationLayer -> AnimationStack connection "
        "chain. A multi-take file carries a separate curve record per plug "
        "PER TAKE (#718 Task 10b, MEASURED) - one full-span record under "
        "Maya's own always-present default take (\"Take 001\"), plus one "
        "per named take carrying that take's own range. None when the "
        "chain is absent - never a guess."))


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


class AnimFacts(BaseModel):
    """Animation records read back OUT OF THE FILE, never from the scene."""

    model_config = ConfigDict(extra="ignore")

    stacks: int
    layers: int
    curves: int
    curve_nodes: int
    takes: List[TakeRecord]
    targets: List[AnimCurveTarget]
    clips: List[AnimClipFacts] = Field(default_factory=list, description=(
        "Per declared clip, what the file carries for it. One rig may hold "
        "several clips and they all export as named takes into this one "
        "file (#718)."))
    unavailable_reason: Optional[str] = None


class FileMapFact(BaseModel):
    """A file-backed map the scene claims, checked against the bytes."""

    model_config = ConfigDict(extra="ignore")

    material: str
    attr: str = Field(description="The shader attribute, e.g. 'baseColor'.")
    slot: Optional[str] = Field(default=None, description=(
        "The semantic slot name ('color', 'normal', ...) when the attribute "
        "maps back to one; null for an attribute outside the slot tables."))
    file_node: str
    basename: str
    on_disk: bool = Field(description=(
        "Whether the image existed on disk at export time."))
    found_in_file: bool = Field(description=(
        "Whether a Texture/Video record in the written FBX carries this "
        "basename. False REFUSES the export when the image is on disk - a "
        "file-backed map has never been measured to vanish, so its absence "
        "means the exporter regressed."))
    semantics_lost: List[str] = Field(default_factory=list, description=(
        "Wiring decisions FBX cannot carry: channel swizzle, reverse-invert, "
        "Raw colorspace. The image ships; the consumer re-creates these."))


class DroppedMapFact(BaseModel):
    """A map the scene carries that the FBX exporter cannot write at all."""

    model_config = ConfigDict(extra="ignore")

    material: str
    attr: str
    slot: Optional[str] = None
    terminal: str = Field(description="The procedural node, e.g. a noise.")
    terminal_type: str
    via: List[str] = Field(default_factory=list, description=(
        "Intermediate node types between the terminal and the shader."))
    meshes: List[str] = Field(default_factory=list, description=(
        "Meshes wearing this material. FileMapFact carries no equivalent "
        "field - deliberately: a dropped map is what needs mesh "
        "attribution to be actionable, a surviving file map does not."))


class TextureFacts(BaseModel):
    """Texture honesty (#714): what the scene claims, what the file carries.

    The one block in this result that is NOT purely byte-derived - and it
    says so deliberately: absence cannot be read from the bytes, so the
    scene's claim is what makes a dropped map nameable.
    """

    model_config = ConfigDict(extra="ignore")

    texture_records: int
    video_records: int
    file_maps: List[FileMapFact] = Field(default_factory=list)
    dropped_maps: List[DroppedMapFact] = Field(default_factory=list)
    unclaimed_records: List[str] = Field(default_factory=list, description=(
        "Basenames in the file no walked claim explains - the walk covers "
        "this toolbox's authored slots only."))
    unavailable_reason: Optional[str] = None


class ExportFbxResult(BaseModel):
    """What maya_export_fbx actually wrote, read back out of the file.

    Every field here is composed from the FBX bytes, never from the Maya scene.
    That is the point of the tool: the unit defect it guards is written by the
    exporter and is absent from the scene, so a scene-derived report would be
    confidently wrong in exactly the case that matters. `textures` is the one
    deliberate exception: a dropped or missing map's ABSENCE cannot be read
    from the bytes at all, so its report is composed from the scene's claim
    against the bytes rather than from the bytes alone - see TextureFacts.
    """

    model_config = ConfigDict(extra="ignore")

    path: str = Field(description="The file written, with forward slashes.")
    bytes: int = Field(description="Size on disk.")
    fbx_version: int = Field(description="FBX format version, e.g. 7700.")
    node_count: int = Field(description="Model records in the file.")
    mesh_count: int = Field(description="Geometry records in the file.")
    root_nodes: List[str] = Field(
        description=(
            "Nodes with no parent in the file. One for a rig; the demigol kit "
            "legitimately has 41, so this is reported, not policed."
        )
    )
    unit_scale_factor: float = Field(
        description=(
            "The file's own declaration, in centimetres per file unit. Always "
            "100.0 - the export is refused otherwise."
        )
    )
    metres_per_unit: float = Field(
        description="Always 1.0; the export is refused for any other value."
    )
    world_bounds_min: Optional[List[float]] = Field(
        default=None,
        description="XYZ minimum over every vertex, composed through the "
                    "parent chain. Null when bounds_unavailable_reason is "
                    "set - either the file holds no geometry, or the reader "
                    "could not compose the hierarchy (a non-default rotate "
                    "order, for instance): see that field for which.",
    )
    world_bounds_max: Optional[List[float]] = Field(
        default=None, description="XYZ maximum, same composition. Null "
                    "under the same condition as world_bounds_min.",
    )
    height_m: Optional[float] = Field(
        default=None,
        description=(
            "Y extent in metres - the number a consumer sees on import, and "
            "the one that tells a 4 m creature from a 4 cm one when every "
            "individual chunk is sub-metre. Null under the same condition as "
            "world_bounds_min."
        ),
    )
    bounds_unavailable_reason: Optional[str] = Field(
        default=None,
        description=(
            "Why world_bounds_min/world_bounds_max/height_m are null, when "
            "they are. Either 'the file holds no geometry', or the reader's "
            "own message when it could not compose the hierarchy - for "
            "example a node whose euler rotation order is not the default "
            "XYZ, which is ordinary rigging practice and not an empty file. "
            "None when the bounds were measured."
        ),
    )
    skin: Optional[SkinFacts] = Field(
        default=None,
        description="Skin facts when include_skins=true; null otherwise.")
    shapes: Optional["ShapeFacts"] = Field(
        default=None,
        description=(
            "Blend-shape facts when the scene declares targets or the file "
            "carries channels; null for a shape-less export. Shapes ride "
            "along automatically - there is no parameter to enable them."))
    animation: Optional[AnimFacts] = Field(
        default=None,
        description=(
            "Animation facts when include_animation=true; null otherwise. "
            "When false, the byte gate has asserted the file carries ZERO "
            "curve records even if the scene is animated."))
    textures: Optional[TextureFacts] = Field(
        default=None,
        description=(
            "Texture facts when the scene claims any map or the file carries "
            "any Texture record; null otherwise. Procedural networks are "
            "named in dropped_maps - Maya's FBX exporter drops them with no "
            "signal, which is what #714 exists to surface."))
    warnings: List[str] = Field(default_factory=list, description=(
        "Measured caveats about the written file - today, texture losses."))


class PixelCheck(BaseModel):
    """Whether the baked image actually sampled anything."""

    model_config = ConfigDict(extra="ignore")

    pixel_count: int = Field(description=(
        "Total pixels in the image (width x height). Always exact, even "
        "when the scan below short-circuited."))
    distinct_values_seen: Optional[int] = Field(default=None, description=(
        "What the plugin's streaming scan SAW before it stopped: 0 "
        "(unreadable), 1 (flat), 2 (non-uniform - it stops at the second "
        "value on purpose and never counts further). Not a count; the count "
        "is distinct_values."))
    distinct_values: Optional[int] = Field(default=None, description=(
        "EXACT distinct RGB values in the written file, counted by the server "
        "from the file itself (#866). None when the file could not be read "
        "here - see census_unavailable_reason."))
    luma_min: Optional[int] = Field(default=None, description="0..255 over the whole file.")
    luma_max: Optional[int] = None
    luma_mean: Optional[float] = None
    luma_stddev: Optional[float] = Field(default=None, description=(
        "Spread of the file's luma: a flat map is 0, a rich AO map reads tens."))
    census_unavailable_reason: Optional[str] = None
    non_uniform: Optional[bool] = Field(default=None, description=(
        "True when the image carries more than one distinct pixel value. "
        "False means the bake is flat - the network sampled nothing, which "
        "is what a UV-less mesh produces (Maya does not refuse it). None "
        "means the image could not be read; see unavailable_reason."))
    unavailable_reason: Optional[str] = None


class BakedMap(BaseModel):
    """One procedural network, now a file texture the FBX can carry."""

    model_config = ConfigDict(extra="ignore")

    material: str
    slot: str
    attr: str
    file: str = Field(description="Absolute path of the image written.")
    basename: str = Field(description=(
        "The name a consumer sees in the FBX's Texture/Video records - the "
        "same string maya_export_fbx reports in textures.file_maps."))
    resolution: int
    colorspace: str = Field(description=(
        "'Raw' for scalar and normal data, 'sRGB' for colour. Data read as "
        "colour renders quietly wrong."))
    wired_plug: str = Field(description=(
        "Which plug of the new file node drives the slot - the only two "
        "wirings _rewire produces: 'outColor' for a colour slot, or "
        "'outColorR' for a scalar slot or a normal slot's kept bump2d "
        "(bumpValue is a literal scalar there, not the tangent-space "
        "outAlpha wiring - that one was measured live to bake a flat, "
        "wrong surface, #714 Task 6)."))
    kept_intermediates: List[str] = Field(default_factory=list, description=(
        "Nodes deliberately preserved - a normal slot keeps its bump2d "
        "because bumpDepth is part of the authored look."))
    deleted_nodes: List[str] = Field(default_factory=list, description=(
        "The replaced procedural nodes. Nodes still feeding something else "
        "are left alone and named in warnings."))
    pixel_check: PixelCheck


class BakeTexturesResult(BaseModel):
    """What maya_bake_textures changed in the scene, and where the images went.

    The rewire is PERSISTENT: the next render shows exactly what an export
    will carry. Re-judge it before exporting - that is the whole point of
    baking as a scene edit rather than an export-time trick.
    """

    model_config = ConfigDict(extra="ignore")

    meshes: List[str]
    out_dir: str
    resolution: int
    baked: List[BakedMap] = Field(default_factory=list)
    skipped_file_backed: List[str] = Field(default_factory=list, description=(
        "Slots that already read from a file and needed no bake."))
    checkpoint_id: Optional[str] = Field(default=None, description=(
        "Taken before the scene was modified; maya_restore_checkpoint "
        "returns the pre-bake state. Null when every requested slot was "
        "already file-backed and nothing was baked - a checkpoint of no "
        "change would both misreport the call and spend a slot in the "
        "bounded checkpoint ring for nothing; see skipped_file_backed for "
        "what happened instead."))
    warnings: List[str] = Field(default_factory=list)


class MeshMapStats(BaseModel):
    """Whether a geometry-derived bake can be trusted (#770)."""

    model_config = ConfigDict(extra="ignore")

    pixel_count: int
    distinct_values_seen: Optional[int] = Field(default=None, description=(
        "What the plugin's streaming scan SAW before it stopped: 0, 1 or 2. "
        "It stops at the second value on purpose; this is not a count."))
    distinct_values: Optional[int] = Field(default=None, description=(
        "EXACT distinct RGB values in the written file, counted by the server "
        "from the file (#866): the number to trust a map by. None when the "
        "file could not be read here - see census_unavailable_reason."))
    luma_min: Optional[int] = None
    luma_max: Optional[int] = None
    luma_mean: Optional[float] = None
    luma_stddev: Optional[float] = Field(default=None, description=(
        "Spread of the file's luma over the whole image: 0 is flat, a rich "
        "AO map reads tens."))
    census_unavailable_reason: Optional[str] = None
    non_uniform: Optional[bool] = Field(default=None, description=(
        "False means the map is FLAT. Unlike maya_bake_textures, flat can "
        "be HONEST here (a lone convex mesh's AO is all-white; concave "
        "curvature on convex-only geometry is all-black, measured) - so "
        "flat maps ship with a warning instead of refusing."))
    blank: Optional[bool] = Field(default=None, description=(
        "True would have refused: every pixel transparent means the bake "
        "drew nothing (the #765 class). Shipped maps are always False."))


class BakedMeshMap(BaseModel):
    """One geometry-derived map, verified and written to disk."""

    model_config = ConfigDict(extra="ignore")

    mesh: str
    map: str = Field(description="ao, curvature, or world_normal.")
    file: str = Field(description="Absolute path of the PNG written.")
    basename: str
    resolution: int
    padded: bool = Field(description=(
        "True when the bake ran with extend_edges (shell borders padded so "
        "bilinear sampling does not bleed background at seams). False only "
        "for the AO bake of a mesh in a shared-material composite, where "
        "alpha must keep marking the real UV shells - padding floods alpha "
        "to 1.0 over the whole image (measured)."))
    stats: MeshMapStats
    curvature_radius: Optional[float] = Field(default=None, description=(
        "The world-space sampling radius this curvature map was baked with "
        "(#868); None on the other maps."))
    curvature_radius_source: Optional[str] = Field(default=None, description=(
        "'given', or 'default: 2% of <mesh>'s <D>-unit bounding-box "
        "diagonal' - the default follows the mesh, because an absolute one "
        "baked a flat map on a centimetre-scale creature."))
    bbox_diagonal: Optional[float] = Field(default=None, description=(
        "The mesh's world bounding-box diagonal at bake time, so a radius "
        "can be read as a fraction of it."))


class AppliedAo(BaseModel):
    """One material whose colour map now carries the baked contact shadow."""

    model_config = ConfigDict(extra="ignore")

    material: str
    attr: str
    file: str = Field(description="The composited colour map written.")
    basename: str
    file_node: str = Field(description=(
        "The new file node now driving the colour slot."))
    wearers: List[str] = Field(default_factory=list)
    replaced_file: Optional[str] = Field(default=None, description=(
        "The colour map the slot read before, when it was file-backed. "
        "That input file is NEVER overwritten - the composite is a new "
        "file next to it."))
    overlap_fraction: float = Field(default=0.0, description=(
        "Fraction of composited texels claimed by more than one wearer's "
        "UV shells - the AO multiplies twice there, which is wrong exactly "
        "there. Non-zero above 1% also lands in warnings."))
    deleted_nodes: List[str] = Field(default_factory=list)


class BakeMeshMapsResult(BaseModel):
    """What maya_bake_mesh_maps measured, wrote, and (with apply_ao) rewired.

    The bake itself mutates nothing - maps render through a shader that is
    never assigned. Only apply_ao edits the scene, and that edit is
    persistent on purpose: the next render shows the shipped contact
    shadow, so re-judge it before exporting.
    """

    model_config = ConfigDict(extra="ignore")

    meshes: List[str]
    out_dir: str
    resolution: int
    maps: List[str]
    baked: List[BakedMeshMap] = Field(default_factory=list)
    applied: List[AppliedAo] = Field(default_factory=list)
    checkpoint_id: Optional[str] = Field(default=None, description=(
        "Taken before the apply_ao rewire; null when nothing was applied - "
        "the bake phase alone changes no scene state worth checkpointing."))
    warnings: List[str] = Field(default_factory=list)


class AppliedEffect(BaseModel):
    """One wear/grime/grain effect as it actually landed (#775)."""

    model_config = ConfigDict(extra="ignore")

    kind: str
    strength: float
    scale: float
    changed_fraction: float = Field(description=(
        "Fraction of texels this effect actually touched. Below the "
        "tool's floor it still ships, but a warning names it - a caller "
        "asking for wear/grime/grain that produced almost nothing should "
        "know rather than ship a file that quietly does nothing."))


class ApplySurfaceDetailResult(BaseModel):
    """What maya_apply_surface_detail composited, wrote, and wired (#775)."""

    model_config = ConfigDict(extra="ignore")

    mesh: str
    effects: List[AppliedEffect]
    color_file: Optional[str] = Field(default=None, description=(
        "The new colour-detail PNG, when wear/grime were requested. The "
        "input colour map is never overwritten."))
    color_basename: Optional[str] = None
    height_file: Optional[str] = Field(default=None, description=(
        "The new height PNG driving a bump2d network, when grain was "
        "requested."))
    height_basename: Optional[str] = None
    file_nodes: List[str] = Field(default_factory=list, description=(
        "Every node this call created (file/place2dTexture/bump2d); on "
        "failure these are exactly what gets deleted before the error is "
        "raised."))
    checkpoint_id: Optional[str] = Field(default=None, description=(
        "Taken before the one mutation this tool makes; restore this to "
        "recover the pre-apply scene."))
    warnings: List[str] = Field(default_factory=list)


class SkeletonJoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the created joint.")
    position: List[float] = Field(
        description="MEASURED world position after creation, scene units.")
    parent: Optional[str] = None
    orient: List[float] = Field(
        description=(
            "The jointOrient that actually landed, in DEGREES - the default "
            "aims X at the first child, and orientation is where every rig "
            "surprise lives, so it is always reported."))


class CreateSkeletonResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root: str
    joints: List[SkeletonJoint]
    warnings: List[str] = Field(default_factory=list)


class SkinJointStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    joint: str
    vertices: int = Field(description="Vertices this joint meaningfully holds.")
    mean_weight: float


class BindSkinResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    root: str
    skin_cluster: str
    influences: List[str]
    unweighted_vertices: int = Field(
        description=(
            "Vertices NO joint owns. Must be 0 for a gate to pass: an "
            "unweighted vertex stays behind when the creature moves, and "
            "nothing looks wrong at bind time."))
    max_influences_exceeded: int
    per_joint: List[SkinJointStats] = Field(
        description=(
            "How to SEE a bind without a viewport: a joint owning zero "
            "vertices, or one joint owning everything, is a legible failure "
            "in these numbers."))
    warnings: List[str] = Field(default_factory=list)


class PosedJoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    world_position: List[float]


class MeshDisplacement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    max_displacement: float
    displaced_vertices: int


class PoseSkeletonResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    applied: int
    joints: List[PosedJoint] = Field(
        description="Every joint under the root with its ACHIEVED world position.")
    max_displacement: float = Field(
        description=(
            "How far the furthest skinned vertex actually moved, measured "
            "before/after from vertices (never bounding boxes). Near zero "
            "against the mesh's size means the pose did nothing and warnings "
            "says why."))
    displaced_vertices: int
    per_mesh: List[MeshDisplacement] = Field(
        default_factory=list,
        description=(
            "Displacement per bound mesh - the combined max can hide one "
            "inert mesh among several, so each is measured alone."))
    warnings: List[str] = Field(default_factory=list)


class ResetPoseResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reset: bool
    max_displacement: float = Field(
        description="How far the mesh moved coming back to the bind pose.")
    warnings: List[str] = Field(default_factory=list)


class PoseIkResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    achieved_position: List[float] = Field(
        description=(
            "Where the joint actually ENDED, measured from the scene after "
            "the bake - never the solver's claim."))
    residual: float = Field(
        description=(
            "Measured miss distance to the target. An unreachable target is "
            "a number here, not a silent stretch."))
    rotations: Dict[str, List[float]] = Field(
        description=(
            "The solve BAKED to plain FK: per-joint local euler DEGREES, "
            "keyed by long name - feed it straight to maya_pose_skeleton. "
            "No IK state survives in the scene."))
    chain: List[str] = Field(
        description="The joints that were solved, start..joint.")
    pole_used: Optional[List[float]] = Field(
        default=None,
        description=(
            "The pole world position the solve actually used: yours, or one "
            "derived from the chain's own bend plane, or null (straight "
            "chain, no pole - the fold direction was Maya's guess)."))
    kept: bool
    max_displacement: float
    displaced_vertices: int
    per_mesh: List[MeshDisplacement] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class InfluenceBucket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    influences: int
    vertices: int


class WeightReportResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    skin_cluster: str
    vertices: int
    max_influences: int = Field(
        description="The cluster's own ceiling, measured from the node.")
    unweighted_vertices: int
    unweighted_sample: List[int] = Field(
        description="First few unowned vertex ids - set_region_weights targets.")
    max_influences_exceeded: int
    exceeded_sample: List[int]
    max_weight_sum_error: float
    histogram: List[InfluenceBucket] = Field(
        description=(
            "Vertices bucketed by how many joints meaningfully hold them. "
            "'One joint owns everything' and 'weights smeared over eight "
            "joints' are both legible here."))
    per_joint: List[SkinJointStats]
    warnings: List[str] = Field(default_factory=list)


class MirrorWeightsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    skin_cluster: str
    axis: str
    direction: str
    mirrored_vertices: int = Field(
        description="Source-side vertices whose rows were written across.")
    on_plane_vertices: int
    unpaired_vertices: int = Field(
        description=(
            "Source vertices with no positional twin - an asymmetric mesh, "
            "left unchanged and warned about, never guessed."))
    changed_vertices: int = Field(
        description="MEASURED after re-reading the table, not computed.")
    unweighted_vertices: int
    warnings: List[str] = Field(default_factory=list)


class SmoothWeightsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    skin_cluster: str
    iterations: int
    smoothed_vertices: int
    changed_vertices: int = Field(
        description="MEASURED after re-reading the table.")
    unweighted_vertices: int
    max_influences_exceeded: int
    warnings: List[str] = Field(default_factory=list)


class SetRegionWeightsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mesh: str
    skin_cluster: str
    joint: str
    vertices_in_region: int
    changed_vertices: int = Field(
        description="MEASURED after re-reading the table.")
    sole_owner_vertices: int = Field(
        description=(
            "Vertices the joint solely owns: a weight below 1.0 has no other "
            "influence to hand the remainder to, so they stay fully owned "
            "(warned, never silent)."))
    unweighted_vertices: int
    max_influences_exceeded: int = Field(
        description=(
            "Vertices now holding more joints than the cluster's "
            "max_influences: a region blend can ADD an influence (nothing "
            "is dropped to make room), so this is how you see it."))
    warnings: List[str] = Field(default_factory=list)


class PhysicsOverride(BaseModel):
    """Design intent author_physics cannot measure: hierarchy and limits.

    extra='forbid' on purpose - a typo'd key here would otherwise silently
    author a LOCKED joint."""

    model_config = ConfigDict(extra="forbid")

    parent: Optional[str] = Field(
        default=None,
        description=(
            "Parent chunk (short name), for flat-sibling hierarchies where "
            "the DAG cannot say. Must be another chunk in the same call."))
    hinge_axis: Optional[List[float]] = Field(
        default=None,
        description=(
            "Chunk-local hinge direction [x, y, z]; normalized by the "
            "tool. Travels WITH hinge_range_deg."))
    hinge_range_deg: Optional[List[float]] = Field(
        default=None,
        description=(
            "[lo, hi] flex arc in DEGREES about hinge_axis, lo <= hi, "
            "0 = the authored rest pose. A one-sided range (e.g. a knee's "
            "[0, 110]) becomes a cone with neutral at the extreme."))
    twist_range_deg: Optional[List[float]] = Field(
        default=None,
        description=(
            "[lo, hi] twist DEGREES about the hinge. Default [0, 0] - "
            "locked."))


class ColliderFit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str = Field(description="box | sphere | capsule - always ONE primitive.")
    centre: List[float] = Field(
        description="Primitive centre in WORLD scene units.")
    rotation_deg: List[float] = Field(
        description=(
            "XYZ euler DEGREES of the mesh's principal frame - the fit is "
            "rotated to the sculpt, never axis-aligned."))
    size: Optional[List[float]] = Field(
        default=None, description="box only: full extents, largest first.")
    radius: Optional[float] = Field(
        default=None, description="sphere/capsule radius.")
    height: Optional[float] = Field(
        default=None,
        description="capsule only: cylinder segment EXCLUDING the two caps.")
    axis: Optional[List[float]] = Field(
        default=None, description="capsule only: world unit long axis.")
    volume_ratio: Optional[float] = Field(
        default=None,
        description=(
            "MEASURED primitive volume / |mesh volume|. Honesty metric: "
            "the delivered golem's worst was 2.35; above 2.4 warns. None "
            "when the mesh volume is unmeasurable."))
    max_escape: float = Field(
        description=(
            "MEASURED furthest vertex outside the primitive, scene units. "
            "Above 10% of the chunk's bbox diagonal warns."))


class PhysicsJoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    axis: List[float] = Field(
        description="Unit hinge axis - 'axis along the hinge' (the knee rule).")
    swing_axis: List[float] = Field(
        description="Deterministic unit perpendicular to axis.")
    swing1: float = Field(
        description="Symmetric half-arc DEGREES covering the flex range.")
    swing2: float = Field(description="Always 0 for hinge-derived cones.")
    twist_lo: float
    twist_hi: float
    swing_centre_deg: float = Field(
        description=(
            "Rotate the joint frame by this about `axis` and the "
            "+-swing1 cone covers exactly the authored [lo, hi]; a "
            "one-sided range puts neutral ON the cone edge - "
            "no-hyperextension as the range's own asymmetry."))
    source: str = Field(
        description="'override' (design data) or 'default_locked' (warned).")


class PhysicsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk: str
    parent: Optional[str] = Field(
        default=None,
        description="Nearest mesh-bearing ancestor chunk, or the override's.")
    mass: float = Field(
        description=(
            "|volume| x density. With the default density 1.0, mass "
            "NUMERICALLY EQUALS volume - the handoff ships volumes and "
            "the engine owns the real constant."))
    volume: float = Field(description="MEASURED |closed-mesh volume|, scene units^3.")
    signed_volume: float = Field(
        description="Negative means inward winding (the mirror trap) - warned.")
    com: List[float] = Field(
        description=(
            "Tetra-weighted SOLID centre of mass - the sculpt's, never a "
            "bbox centre (#640) and never a vertex average."))
    watertight: bool
    open_edges: int = Field(
        description="Boundary-edge count; non-zero makes volume unreliable (warned).")
    verts: int
    tris: int
    collider: ColliderFit
    joint: Optional[PhysicsJoint] = Field(
        default=None, description="null for a parentless (root) body.")


class AuthorPhysicsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bodies: List[PhysicsBody]
    density: float
    total_volume: float = Field(
        description="Sum of measured |volume| over every body in this call.")
    warnings: List[str] = Field(default_factory=list)


class ClipJointKinematics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path_length: float = Field(description="Total world distance travelled.")
    peak_speed: float = Field(description="Highest per-frame speed, units/s.")
    peak_speed_frame: int = Field(description="Frame index of that peak.")
    max_accel: float = Field(description="Largest |dv|/dt in the clip.")
    max_accel_frame: int = Field(description="Frame index of that spike.")
    height_range: List[float] = Field(description="[lowest, highest] world Y.")
    loop_closure: float = Field(
        description="World distance between the first and last frame - "
                    "near zero for a clip that loops cleanly."
    )


class ClipContact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    runs: List[List[int]] = Field(
        description="Inclusive [first, last] frame spans where this joint "
                    "reads as planted (near its lowest point and nearly "
                    "still). Inferred, not declared."
    )
    max_slide: float = Field(
        description="Furthest any single plant wanders in the ground plane. "
                    "A planted foot should hold; this is the number that "
                    "says whether it did."
    )


class ClipSymmetry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    left: str
    right: str
    peak_speed_ratio: float = Field(
        description="Larger peak over smaller: 1.0 = symmetric effort. The "
                    "#773 probe measured a popped key as 2.4 against its "
                    "mirror limb."
    )


class MeasureClipResult(BaseModel):
    """Motion metrics for one clip (#773).

    The numbers behind preview_clip's pictures. Unambiguous defects (a foot
    sliding through its plant) arrive as warnings; everything else is raw
    numbers with worst-frame indices, because 'too fast' is the caller's
    judgement, not the tool's.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    fps: int
    frames_sampled: int
    loop: bool
    rig_height: float = Field(
        description="World-Y span of the rig at the clip's first frame - "
                    "the scale every relative threshold hangs off."
    )
    thresholds: dict = Field(
        description="The derived absolute thresholds used, so every verdict "
                    "can be re-derived from the numbers."
    )
    joints: Dict[str, ClipJointKinematics]
    contacts: Dict[str, ClipContact]
    symmetry: List[ClipSymmetry] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
