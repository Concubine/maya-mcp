# CMU mocap fixtures (#774)

Two small clips from the **CMU Graphics Lab Motion Capture Database**
(http://mocap.cs.cmu.edu/), converted to BVH, used here as fixtures for
`tests/test_mocapmath.py`'s `TestCmuFixtures` and (later) #774's Task 7
retarget gate.

## Funding acknowledgment (as requested by the database)

> The data used in this project was obtained from mocap.cs.cmu.edu.
> The database was created with funding from NSF EIA-0196217.

## Files

- `cmu_walk.bvh` - Subject 07, trial 01 ("walk"). 317 frames, 120fps
  (Frame Time 0.0083333s), 241,649 bytes.
- `cmu_idle.bvh` - Subject 113, trial 21 ("Standing Still"). 1,368 frames,
  120fps (Frame Time 0.0083333s), 1,040,156 bytes.

Both are plain-text BVH (`HIERARCHY` first line), well under the 2 MB
fixture ceiling, and use CMU's raw joint naming: `Hips`, `LHipJoint`,
`LeftUpLeg`, `LeftLeg`, `LeftFoot`, `LeftToeBase`, `RHipJoint`, `RightUpLeg`,
`RightLeg`, `RightFoot`, `RightToeBase`, `LowerBack`, `Spine`, `Spine1`,
`Neck`, `Neck1`, `Head`, `LeftShoulder`, `LeftArm`, `LeftForeArm`,
`LeftHand`, `LeftFingerBase`, `LeftHandIndex1`, `LThumb`, `RightShoulder`,
`RightArm`, `RightForeArm`, `RightHand`, `RightFingerBase`,
`RightHandIndex1`, `RThumb`. `mocapmath.CMU_HIK_MAP` maps the 15 slots
`resolve_hik_map` needs directly against this naming - no aliasing needed,
because CMU's own names already match the HumanIK slot names for exactly
the 15 joints the retargeter requires.

## Verified sanity numbers (measured, not assumed)

The fixture-selection distinction ("walk" vs "idle") was checked by reading
the root joint's translation channels (columns 0/2 of each motion row - X
and Z, since CMU's Hips channel order is `Xposition Yposition Zposition
Zrotation Yrotation Xrotation`) across the whole clip, not by trusting the
CMU catalog's one-line label:

- `cmu_walk.bvh` root travels from `(8.87, -31.71)` (X, Z) at frame 0 to
  `(9.53, 31.75)` at the last frame - about 63 units of net Z travel.
- `cmu_idle.bvh` root stays within `(-5.64 .. -4.81, 33.02 .. 34.41)`
  throughout - under 1.4 units of total drift, more than 10x less than the
  walk clip's travel over a *4x longer* clip.

`tests/test_mocapmath.py::TestCmuFixtures::test_walk_root_translates_more_than_idle`
asserts this 10x ratio directly against the shipped files so a future
fixture swap cannot silently invert which clip is which.

## Conversion provenance

CMU's own database ships `.asf`/`.amc`, not BVH. These files came from
**una-dinosauria/cmu-mocap** (https://github.com/una-dinosauria/cmu-mocap,
MIT-licensed mirror), which republishes the BVH conversion of the CMU
dataset originally produced by Bruce Hahne / the cgspeed conversion project,
"to have the data available through http requests" per that repo's own
README. CMU's database places no restrictions on use of the data itself
(see the database's own terms at mocap.cs.cmu.edu); this repo carries no
license file from CMU because none is required for redistribution of derived
motion data under CMU's stated terms.

Exact source URLs used:

- `cmu_walk.bvh` <- https://raw.githubusercontent.com/una-dinosauria/cmu-mocap/master/data/007/07_01.bvh
- `cmu_idle.bvh` <- https://raw.githubusercontent.com/una-dinosauria/cmu-mocap/master/data/113/113_21.bvh

Subject/trial catalog cross-checked against that repo's own
`cmu-mocap-index-text.txt`, which labels subject 7 "various expressions and
human behaviors" (trial 01: "walk") and subject 113 (trial 21: "Standing
Still").
