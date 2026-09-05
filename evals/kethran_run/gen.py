import json, math, sys

N = 18


def ring(z, top, bot, hw, keel=0.25, topflat=0.18, sag=0.0):
    pts = []
    cy = (top + bot) * 0.5
    ry = (top - bot) * 0.5
    for i in range(N):
        t = 2.0 * math.pi * i / N
        u = math.cos(t)
        y = cy + ry * u
        w = (1.0 - topflat * u * u) if u > 0 else (1.0 - keel * (abs(u) ** 2.0))
        x = hw * math.sin(t) * w
        if u < -0.25:
            y -= sag * (abs(u) - 0.25) / 0.75
        pts.append([round(x, 2), round(y, 2), round(z, 2)])
    return pts


# ONE loft, rump -> nose. 16 sections is the tool's cap.
# z, top_y, bot_y, halfwidth, keel, sag
SPINE = [
    (-120, 172, 128, 22, 0.35, 0),   # rump / tail root
    (-100, 187, 114, 42, 0.30, 0),   # ischium
    (-72, 191, 102, 53, 0.22, 3),    # hip, widest aft
    (-38, 188, 96, 47, 0.12, 6),     # loin
    (-6, 191, 90, 53, 0.10, 8),      # belly
    (26, 200, 86, 60, 0.24, 4),      # rear ribcage
    (52, 212, 84, 64, 0.44, 0),      # deep chest / brisket
    (74, 221, 90, 57, 0.50, 0),      # withers hump
    (94, 212, 104, 47, 0.50, 0),     # base of neck
    (112, 200, 114, 40, 0.42, 0),    # neck
    (128, 191, 120, 35, 0.34, 0),    # neck
    (140, 187, 124, 30, 0.28, 0),    # throatlatch - narrows
    (156, 186, 116, 34, 0.14, 0),    # cheek / masseter - swells, jaw drops
    (172, 177, 112, 29, 0.10, 0),    # below the eye
    (192, 165, 112, 21, 0.14, 0),    # muzzle
    (214, 153, 120, 14, 0.20, 0),    # nose
]

print(json.dumps([ring(z, t, b, hw, keel=k, sag=s) for (z, t, b, hw, k, s) in SPINE]))
