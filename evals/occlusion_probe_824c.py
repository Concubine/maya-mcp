"""Probe #824 part 3: gate check 6 drew 0 red px for isolate=[|red] +
target=|red from the back, where probe part 2 (I_isolate) drew 14884.
Same call, repeated, with the pixels classified and the frames kept.

Run:  MAYA_MCP_PORT=9878 python evals/occlusion_probe_824c.py
"""
import base64
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import occlusion_probe_824 as p1  # noqa: E402

OUT = p1.OUT


def classify(png_b64, name):
    import numpy as np
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(png_b64)))
    img.save(os.path.join(OUT, name + ".png"))
    a = np.asarray(img.convert("RGBA")).astype(int)
    r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    return {"red": int(((r > 120) & (g < 90) & (b < 90)).sum()),
            "blue": int(((b > 120) & (r < 90) & (g < 90)).sum()),
            "green": int(((g > 120) & (r < 90) & (b < 90)).sum()),
            "opaque": int((al > 0).sum()),
            "distinct": int(len(np.unique(a.reshape(-1, 4), axis=0)))}


def main():
    p1.ok("new_scene", {"confirm": True})
    p1.py(p1.LIB + "\nr = 1")
    p1.py("r = red_blue_scene()")
    rows = []
    for i in range(3):
        res = p1.ok("capture_viewport", {"angles": ["back"], "target": ["|red"], "isolate": ["|red"],
                                         "resolution": 256, "shading": "flatShaded"})
        img = res["images"][0]
        rows.append({"try": i, "blank": img.get("blank"), "pixels": classify(img["png_b64"], "C_isolate_%d" % i),
                     "camera": res["camera_positions"][0]["position"], "warnings": res["warnings"]})
    # and the same without target (isolate alone), and with smoothShaded
    res = p1.ok("capture_viewport", {"angles": ["back"], "isolate": ["|red"], "resolution": 256, "shading": "flatShaded"})
    rows.append({"try": "isolate_only", "pixels": classify(res["images"][0]["png_b64"], "C_isolate_only")})
    res = p1.ok("capture_viewport", {"angles": ["back"], "target": ["|red"], "isolate": ["|red"], "resolution": 256})
    rows.append({"try": "smooth", "pixels": classify(res["images"][0]["png_b64"], "C_isolate_smooth")})
    print(json.dumps(rows, indent=1))
    with open(os.path.join(OUT, "findings_c.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1)


if __name__ == "__main__":
    main()
