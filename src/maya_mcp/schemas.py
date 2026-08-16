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
