# The crown and the terrace lip (Demigol #654, revision 4, 2026-08-21)

Renders of the two contexts revision 4 adds, shot from the angles they are actually seen from
rather than from a front elevation. Kit lit with Demigol's own sun direction
(`(-0.321, -0.766, -0.557)`), 60° vertical FOV, atlas sampled unfiltered at full 4096.

| file | camera | what to look at |
|---|---|---|
| `crown_street.png` | 20 m out, 1.8 m eye | does the building **end**, seen from where a soldier stands |
| `crown_airborne.png` | 26 m out, 23 m up | the golem is airborne constantly; this is the roofline it sees |
| `crown_detail.png` | level with the caps, 40 mm | all four crowns side by side — the "four buildings or one inconsistent roofline" question |
| `terrace_underside.png` | from below | the underside, which is the whole reason the context exists |

## The defect the renders caught, and the gate that now catches it

The first build of the crowns was a **stack** — wall segment, cornice, parapet segment, coping —
with the bands between them left un-modelled. Three of the four had a slot straight through the
cell. It showed up as the brick crown's dentils silhouetted against black sky with daylight
between them.

Nothing else could have found it. Every piece was inside its triangle budget, inside the
envelope, inside the oversail band, UV-clean, and the contact sheet rendered 0 blank tiles.

The kit already knew the answer everywhere else — `slab(front=BACK)` plus bands from `BACK` to
`FACE`, one continuous body with relief in front of it. **A crown is a facade piece that happens
to stop.** All six pieces now follow it, and
`tests/test_demigol_generators.py::TestKitWallBodyContinuity` asserts that no wall-context piece
has a gap in its body. That gate was checked against the real defect before being trusted: fed
the original stacked crown it reports
`{'kit_infill_crown_a': [(0.1, 0.19), (0.45, 0.46), (1.18, 1.21)]}`.

Its one named exemption is `kit_steel_lobby_a`, an I-section column wearing a hazard band — you
are *meant* to see between its flanges.

## A second thing the gates caught before any render

The four crowns' copings were originally **battered** with `taper`. `taper` flares X and Z
together, so a full-width tapered box pulls its own ends in from the cell face and opens a notch
between one crown and the next — and a roofline is precisely a run where that notch would repeat
across a whole building. The taper-trap gate, written by revision 3, fired on all four.

They are **stepped** instead: two untapered bands of different projection, which gives the same
light-catching top edge for one extra box and meets its neighbours exactly.

## Open question for the user — a taste call, not a defect

The four crowns are tonally similar: three of them put a pale `trim` coping over a pale parapet,
and only `kit_brick_crown_a` carries its own body colour up into the cap. Across a district that
may read as **one roofline with inconsistent trim** rather than as four buildings ending
differently — which is the exact risk the delivery set out to test, and the reason the four are
photographed side by side in `crown_detail.png`.

If they should diverge harder, the lever is cheap: the parapet is a single tonal band
(`plate(..., BACK, FACE, patch)`), so giving each family its own parapet patch is a one-word
change per piece and no new triangles.
