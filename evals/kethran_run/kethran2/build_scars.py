"""Paint healed scar tissue into the hide albedo.

The scars were CUT as geometry first (maya_sculpt_ops soft_move chains). This
script takes the UV coordinates of the vertices those strokes actually moved --
exported from Maya as scar_uv.json -- and splats pale, depigmented scar tissue
at exactly those texels. Registration is therefore exact and needs no bake.

Writes a NEW filename rather than overwriting: Maya's file node caches an
image by path, so overwriting in place renders bit-identical frames (N-12).
"""
import json
import numpy as np
from PIL import Image, ImageFilter

D = "D:/devel/maya-mcp/evals/kethran_run/kethran2/maps/"
SRC = D + "hide_albedo_v2.png"
DST = D + "hide_albedo_v3.png"
N = 2048

rng = np.random.default_rng(29)

srgb = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32) / 255.0
if srgb.shape[0] != N:
    srgb = np.asarray(Image.open(SRC).convert("RGB").resize((N, N), Image.BILINEAR)).astype(np.float32) / 255.0
# work in LINEAR, the same space build_albedo.py mixed in
lin = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)

pts = json.load(open(D + "scar_uv.json"))
print("scar UV samples:", len(pts))

# --- splat the strokes into a mask -------------------------------------
mask = np.zeros((N, N), np.float32)
R = 13                                  # px @2048. Measured: at R=17 the strokes came
                                        # out ~0.5% of body pixels and vanished at
                                        # full-body framing even though the texels were
                                        # right. Scars have to be wide to read.
yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
disc = np.clip(1.0 - np.sqrt(xx ** 2 + yy ** 2) / R, 0, 1) ** 1.6

for u, v, w in pts:
    px = int(round(u * (N - 1)))
    py = int(round((1.0 - v) * (N - 1)))     # image origin is top-left, UV is bottom-left
    x0, x1 = max(0, px - R), min(N, px + R + 1)
    y0, y1 = max(0, py - R), min(N, py + R + 1)
    if x1 <= x0 or y1 <= y0:
        continue
    sub = disc[(y0 - (py - R)):(y1 - (py - R)), (x0 - (px - R)):(x1 - (px - R))]
    np.maximum(mask[y0:y1, x0:x1], sub * float(w), out=mask[y0:y1, x0:x1])

print("mask coverage %.4f  max %.3f" % (float((mask > 0.02).mean()), float(mask.max())))

# close the gaps between per-vertex splats so a stroke is a LINE, not beads
im = Image.fromarray((mask * 255).astype(np.uint8))
im = im.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(7))
im = im.filter(ImageFilter.GaussianBlur(1.6))
mask = np.asarray(im).astype(np.float32) / 255.0

# break the edge up so it is not a clean airbrushed stripe
grit = rng.random((N, N)).astype(np.float32)
grit = np.asarray(Image.fromarray((grit * 255).astype(np.uint8))
                  .filter(ImageFilter.GaussianBlur(1.0))).astype(np.float32) / 255.0
mask = np.clip(mask * (0.84 + 0.32 * grit), 0, 1)

# --- scar tissue: paler, greyer, slightly pink; NOT white --------------
scar = np.array([0.330, 0.258, 0.228], np.float32)      # linear; ~4x the hide's
                                                        # 0.076 base, which is what a
                                                        # depigmented scar actually is
core = np.clip((mask - 0.30) / 0.70, 0, 1)              # only the centre goes full
t = np.clip(mask * 0.92 + core * 0.35, 0, 1)[..., None]

out = lin * (1.0 - t) + scar[None, None, :] * t

# a thin darker line down the very centre of the deepest strokes -- healed
# tissue puckers and keeps a seam
seam = np.clip((mask - 0.80) / 0.20, 0, 1)[..., None]
out = out * (1.0 - 0.30 * seam)

out = np.clip(out, 0.0, 1.0)
enc = np.where(out <= 0.0031308, out * 12.92, 1.055 * np.power(out, 1 / 2.4) - 0.055)
img = (np.clip(enc, 0, 1) * 255).astype(np.uint8)
Image.fromarray(img, "RGB").save(DST)

# --- scar tissue is SMOOTH: flatten the hide's grain along every stroke --
# This is the strongest cue of the two. Hide grain is a bump map; healed scar
# tissue has none, so a scar reads as a slick channel through rough skin.
HSRC = D + "body_height.png"
HDST = D + "body_height_v2.png"
h = np.asarray(Image.open(HSRC).convert("L")).astype(np.float32)
if h.shape[0] != N:
    h = np.asarray(Image.open(HSRC).convert("L").resize((N, N), Image.BILINEAR)).astype(np.float32)
h = h / 255.0
flat = float(np.median(h))
k = np.clip(np.power(mask, 1.6) * 1.05, 0, 1)   # flatten only the core,
                                                # so a scar is a line not a wet patch
h_out = h * (1.0 - k) + (flat - 0.10 * k) * k          # flatten, and sink slightly
h_out = np.clip(h_out, 0, 1)
Image.fromarray((h_out * 255).astype(np.uint8), "L").save(HDST)
print("wrote", HDST, " median height %.3f" % flat)

lum_before = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
lum_after = out @ np.array([0.2126, 0.7152, 0.0722], np.float32)
print("wrote", DST)
print("linear luma  before mean %.4f   after mean %.4f" % (lum_before.mean(), lum_after.mean()))
print("pixels changed by >2/255: %.4f" % float((np.abs(img.astype(np.int16) -
      (np.clip(np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1/2.4) - 0.055), 0, 1) * 255)
      .astype(np.int16)).max(axis=2) > 2).mean()))
print("distinct 8-bit colours:", len(np.unique(img.reshape(-1, 3), axis=0)))
