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


class SceneGraphResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objects: List[SceneObject]
    total: int = Field(description="Total matching objects before pagination.")
    cursor: Optional[str] = Field(
        default=None, description="Pass back to fetch the next page; None when complete."
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


class CheckpointResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    checkpoint_id: str = Field(description="Stem NNN_label; pass to maya_restore_checkpoint.")
    path: str = Field(description="Saved .ma file path.")


class RestoreResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    restored: str
    pre_restore_checkpoint: str = Field(
        description="Auto-checkpoint of the state before restoring, in case you change your mind."
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


class OpenSceneResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    opened: str = Field(description="Absolute path to the scene file that was opened.")
    pre_checkpoint: Optional[str] = Field(
        default=None,
        description="Checkpoint id saved just before the discarded scene was replaced; "
        "pass to maya_restore_checkpoint to recover it.",
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
