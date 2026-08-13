"""Result models for maya-mcp tools.

These validate what comes back from the plugin before it reaches the client,
and give every tool a real structured-output schema. Extra keys from newer
plugin versions are ignored rather than fatal.
"""

from __future__ import annotations

from typing import List, Optional

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
