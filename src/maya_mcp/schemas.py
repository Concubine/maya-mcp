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
            "Metres one scene unit becomes in an exported FBX. 1.0 (linear_unit "
            "'cm') is the ONLY value that produces a metre-true delivery - it is "
            "the authoring convention every mesh out of this repo uses, where "
            "the numbers you pass mean metres. 100.0 (linear_unit 'm') is the "
            "100x defect of maya-mcp #629, which no in-Maya measurement can see. "
            "Null means the unit was not recognised - never assume 1.0."
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


class TransformedObject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    translate: List[float]
    rotate: List[float]
    scale: List[float]
    pivot: Optional[List[float]] = Field(
        default=None,
        description="World-space rotate pivot after the call - the point this "
                    "object turns about, which is what a ragdoll reads. Same "
                    "meaning as AssembledObject.pivot.",
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
    method: str = Field(description="Which path ran: polyRetopo, polyRemesh, or polyReduce.")
    warnings: List[str] = Field(default_factory=list)
    original: Optional[str] = Field(
        default=None,
        description="Long name of the hidden pre-remesh duplicate, when keep_original=true.",
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

    angle: str
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
    samples: int
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
                    "applied at all (an omitted single-part chunk); otherwise "
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
    warnings: List[str] = Field(default_factory=list)


class CombineResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Canonical long name of the merged object.")
    inputs: int = Field(description="How many meshes were consumed.")
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
    unavailable_reason: Optional[str] = None


class BlendshapeTargetSpec(BaseModel):
    """One morph target to wire: an ordinary same-topology mesh."""

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
    meshes: List[str] = Field(default_factory=list)


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
    confidently wrong in exactly the case that matters.
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
