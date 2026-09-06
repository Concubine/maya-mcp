"""Build a real hide albedo: countershading + mottling + AO + edge wear.

The detail pass only produced a bump map and a near-flat colour composite, which is
why the creature reads identically at full-body distance. Large-scale ALBEDO
variation is what changes a distant read.
"""
import numpy as np
from PIL import Image, ImageFilter

D = "D:/devel/maya-mcp/evals/kethran_run/kethran2/maps/"
N = 2048
rng = np.random.default_rng(11)


def load(name, size=N, mode="L"):
    im = Image.open(D + name).convert(mode)
    if im.size != (size, size):
        im = im.resize((size, size), Image.BILINEAR)
    return np.asarray(im).astype(np.float32) / 255.0


def smooth_noise(cells, blur):
    """Low-res random field upscaled + blurred = smooth blotches."""
    a = rng.random((cells, cells)).astype(np.float32)
    im = Image.fromarray((a * 255).astype(np.uint8)).resize((N, N), Image.BICUBIC)
    im = im.filter(ImageFilter.GaussianBlur(blur))
    v = np.asarray(im).astype(np.float32) / 255.0
    return (v - v.mean()) / (v.std() + 1e-6)   # zero-mean, unit-ish


ao = load("body_ao.png")
wn = np.asarray(Image.open(D + "body_world_normal.png").convert("RGB")
                .resize((N, N), Image.BILINEAR)).astype(np.float32) / 255.0
curv = np.asarray(Image.open(D + "body_curvature.png").convert("RGB")
                  ).astype(np.float32) / 255.0

up   = np.clip((wn[..., 1] - 0.5) * 2.0, 0, 1)   # world +Y  -> dorsal
down = np.clip((0.5 - wn[..., 1]) * 2.0, 0, 1)   # world -Y  -> ventral
convex = curv[..., 1]                            # green = convex ridges

# --- base hide, LINEAR ---------------------------------------------------
base = np.array([0.076, 0.046, 0.026], np.float32)      # dark, saturated warm brown
belly = np.array([0.165, 0.128, 0.096], np.float32)     # pale dusty underside

# UV-space noise breaks at island borders on a box-projected atlas, so keep it
# FINE only (seams imperceptible) and take all large-scale variation from the
# geometric masks (AO, world normal), which are continuous across islands.
medium = smooth_noise(60, 3)      # small mottling
fine   = smooth_noise(190, 1)     # micro break-up

mott = 1.0 + 0.075 * medium + 0.065 * fine
mott = np.clip(mott, 0.7, 1.35)[..., None]

# countershading: dark on top, pale underneath  (geometric => seam-free)
t = np.clip(down * 1.05, 0, 1)[..., None]
alb = base[None, None, :] * (1.0 - t) + belly[None, None, :] * t
alb = alb * (1.0 - 0.26 * up[..., None])          # extra darkening dorsally

alb = alb * mott

# warm the shoulders/back slightly, cool the underside
warm = np.stack([1.0 + 0.10 * up, 1.0 + 0.015 * up, 1.0 - 0.06 * up], -1)
alb = alb * warm

# Ambient occlusion seated into the colour. KEEP THIS GENTLE: the AO map has
# tonal steps between UV islands, and multiplying it in hard prints those steps
# on the model as angular patches.
alb = alb * (0.84 + 0.16 * ao)[..., None]

# pale keratinous wear on ridges (crest plates, bony prominences). The curvature
# map also lights up boolean seams, so a high gain here draws the seams too.
wear = np.clip(convex * 0.7, 0, 1)[..., None]
alb = alb * (1.0 - wear) + np.array([0.26, 0.225, 0.185], np.float32)[None, None, :] * wear

alb = np.clip(alb, 0.0, 1.0)

# --- linear -> sRGB, write ----------------------------------------------
srgb = np.where(alb <= 0.0031308, alb * 12.92, 1.055 * np.power(alb, 1 / 2.4) - 0.055)
out = (np.clip(srgb, 0, 1) * 255).astype(np.uint8)
Image.fromarray(out, "RGB").save(D + "hide_albedo.png")

lum = alb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
print("wrote hide_albedo.png")
print("linear luma  min %.4f  mean %.4f  max %.4f" % (lum.min(), lum.mean(), lum.max()))
print("contrast ratio max/min: %.1fx" % (lum.max() / max(lum.min(), 1e-5)))
print("distinct 8-bit colours:", len(np.unique(out.reshape(-1, 3), axis=0)))
