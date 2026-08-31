"""#771 mini-probe: do the baked DeformPercent VALUES track the elbow angle?

Reimports probe_driven.fbx into the agent Maya and evaluates every blendShape
weight per frame. A constant curve = the bake is a lie; a 0 -> 1 -> 0 arc
tracking the keyed 0 -> -90 -> 0 elbow = the bake is real.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_call import call, structured_result  # noqa: E402

OUT_DIR = os.path.abspath(os.path.dirname(__file__))
PATH = os.path.join(OUT_DIR, "probe_driven.fbx").replace("\\", "/")

frame = call("execute_python", {"code": r"""
import json
cmds.file(new=True, force=True)
cmds.file(%r, i=True)
bs = cmds.ls(type='blendShape')
rep = {'blendshape_nodes': bs, 'all_anim_curves': len(cmds.ls(type='animCurve'))}
if bs:
    node = bs[0]
    aliases = cmds.listAttr(node + '.w', multi=True) or []
    rep['aliases'] = aliases
    vals = {}
    for f in (1, 6, 12, 18, 24):
        cmds.currentTime(f)
        vals[f] = {a: round(cmds.getAttr('%%s.%%s' %% (node, a)), 4)
                   for a in aliases}
    rep['weights_by_frame'] = vals
    rep['weight_curve_conns'] = cmds.listConnections(
        node + '.' + aliases[0], source=True, plugs=True) if aliases else []
json.dumps(rep)
""" % PATH}, timeout_s=180)

result = frame.get("result") or {}
if frame.get("status") != "ok" or result.get("traceback"):
    print(json.dumps(frame, indent=2, default=str)[:4000])
    raise SystemExit(1)
print(json.dumps(json.loads(structured_result(result)), indent=2, sort_keys=True))
