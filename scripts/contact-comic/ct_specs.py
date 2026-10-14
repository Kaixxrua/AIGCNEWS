"""Contact page frames (contact-C concept, measured at 1536x1024). Usage: ct_specs.py <asset dir> <meta json>

Everything is drawn in page px of the concept, relative to the element's box; `night()` gives the dark theme copy.
"""
import json
import sys
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
import inkframe

OUT, META = sys.argv[1], sys.argv[2]
INK = '#040506'
NAVY = '#15233d'
NIGHT_INK = '#cfd4cb'
NIGHT_FILL = '#292a2d'
LIME = '#c1f61c'
NIGHT_LIME = '#b4d956'


def night(spec):
    s = json.loads(json.dumps(spec))
    s['ink']['color'] = s['ink'].get('night', NIGHT_INK)
    s['ink'].pop('color2', None)
    if s.get('fill'):
        s['fill'] = s.get('night_fill', NIGHT_FILL)
    sh = s.get('shadow')
    if sh and sh['type'] == 'solid':
        sh['fill'] = sh.get('night', '#000000')
    for d in s.get('dots') or []:
        d.update(color=d.get('night', NIGHT_INK), alpha=d.get('alpha', 1) * d.get('night_alpha', .35))
    for g in s.get('glow') or []:
        g.update(color=g.get('night', '#3a3d40'), alpha=g.get('alpha', 1) * .6)
    return s


def dots(corner, rx, ry, color=INK, **kw):
    d = dict(corner=corner, color=color, pitch=5, r=1.4, rx=rx, ry=ry, angle=45, norm=1.6, keep=2.2, falloff=.6, alpha=.9)
    d.update(kw)
    return d


# ── the scene frame: a 3px ink line whose top climbs 52px from left to right and whose foot drops 15px, on a solid
# block 6px right and 7.5px down. Drawn compressed (the middle is stretched by the 9-slice); the corners keep the
# concept's slopes and the middle segments are steepened so they meet them again once stretched to 1491px.
FW = 1491
L, R, T, B = 165, 135, 178, 132
MW, MH = 260, 160
W, H = L + MW + R, T + MH + B
st, sb = 52 / FW, 15 / FW
top = [(0, 52), (L, 52 - st * L), (W - R, st * R), (W, 0)]
bot = [(0, H - 15), (L, H - 15 + sb * L), (W - R, H - sb * R), (W, H)]
FRAME = dict(w=W, h=H, seed=301, poly=top + bot[::-1], top_line=top, bottom_line=bot, slices=(T, R, B, L),
             ink=dict(color=INK, w=3.2, bottom=.3, vary=.18, wobble=.16),
             shadow=dict(type='solid', dx=6, dy=7.5, fill=INK, rough=.12))
# the halftone that sits over the still poster: dense and heavy top-left and bottom-left, finer top-right
FRAME_DOTS = dict(FRAME, only_dots=True, dots=[
    dots('tl', 160, 118, color='#15202e', pitch=5.4, r=1.75, keep=2.4, falloff=.5, alpha=.92, night_alpha=.55),
    dots('tr', 128, 96, color='#15202e', pitch=5, r=1.2, keep=1.6, falloff=.75, alpha=.85, night_alpha=.55),
    dots('bl', 160, 112, color='#15202e', pitch=5.6, r=1.95, keep=2.4, falloff=.45, alpha=.92, night_alpha=.55),
])

# ── the contact card: a white parallelogram whose top climbs to the right and whose sides lean left toward the
# foot, a 2.8px line on a 9px/8px ink block, cyan dots top-right and lime dots bottom-right
CARD = dict(w=435, h=212, seed=302, fill='#fdfcf7', poly=[(18, 18), (435, 0), (420, 212), (0, 212)],
            slices=(34, 64, 40, 28), top_line=[(0, 18.8), (435, 0)],
            ink=dict(color=INK, w=2.8, bottom=.4, vary=.16, wobble=.14),
            shadow=dict(type='solid', dx=9, dy=8, fill=INK, rough=.1),
            dots=[dots('tr', 44, 26, color='#2cb8dc', pitch=4.2, r=1.25, norm=1.4, keep=1.8, alpha=.95),
                  dots('br', 62, 34, color='#c4ea16', pitch=4.2, r=1.35, norm=1.4, keep=1.8, alpha=.95)])

# ── the note slip riding on the card's top-left: white, its top climbing to the right, a nick of a tail at its
# lower-left corner dropping onto the card, a 5px block to the right and a thin one under it
NOTE = dict(w=312, h=50, seed=303, fill='#fefdf6', pad=(3, 8, 9, 3), slices=(14, 16, 14, 22),
            poly=[(5, 10), (311, 1), (304, 39), (12.5, 48.4), (6.8, 54.2), (8.4, 48.8), (1, 49.2)],
            ink=dict(color=INK, w=2.4, bottom=.5, vary=.14, wobble=.14),
            shadow=dict(type='solid', dx=4.6, dy=2.2, fill=INK, rough=.08))

# ── "优先入口": a lime slip leaning right on a 3px block; the join button: a wider lime block on a 5px/4px block
BADGE = dict(w=94, h=28, seed=304, fill='#cdf33e', night_fill=NIGHT_LIME, poly=[(5, 1), (93, 0), (89, 27), (1, 28)],
             slices=(10, 12, 10, 12), ink=dict(color=INK, w=2, bottom=.4, vary=.14, wobble=.14),
             shadow=dict(type='solid', dx=3, dy=3, fill=INK, rough=.08))
CTA = dict(w=208, h=47, seed=305, fill=LIME, night_fill=NIGHT_LIME, poly=[(6, 2), (207, 1), (204, 44), (2, 46)],
           slices=(12, 14, 12, 14), ink=dict(color=INK, w=2.2, bottom=.5, vary=.14, wobble=.14),
           shadow=dict(type='solid', dx=5, dy=4, fill=INK, rough=.08))
# the QR code's white box, a 2.4px line on a 6px/5px block
QR = dict(w=131, h=134, seed=306, fill='#ffffff', night_fill='#ffffff', poly=[(4, 3), (130, 1), (127, 132), (2, 133)],
          slices=(12, 14, 12, 12), ink=dict(color=INK, w=2.4, bottom=.4, vary=.14, wobble=.14),
          shadow=dict(type='solid', dx=6, dy=5, fill=INK, rough=.08))

# ── the scene's own controls (not in the concept): white slips on the same ink, the chooser a card like the
# contact card, its options thin-ruled boxes (lime when chosen)
ACT = dict(w=112, h=42, seed=307, fill='#fdfcf7', poly=[(1.5, 1.5), (112, 0), (110.5, 40), (0, 42)],
           slices=(10, 12, 10, 10), ink=dict(color=INK, w=2.2, bottom=.4, vary=.14, wobble=.14),
           shadow=dict(type='solid', dx=4, dy=4, fill=INK, rough=.08))
TAG = dict(w=76, h=29, seed=308, fill='#fdfcf7', poly=[(1.5, 2.5), (76, 0), (74.5, 28), (0, 29)],
           slices=(9, 10, 9, 10), ink=dict(color=INK, w=2, bottom=.3, vary=.14, wobble=.14),
           shadow=dict(type='solid', dx=2.4, dy=2.4, fill=INK, rough=.08))
PANEL = dict(w=448, h=420, radius=3, seed=309, fill='#fdfcf7', slices=(40, 64, 44, 30),
             ink=dict(color=INK, w=2.8, bottom=.4, vary=.16, wobble=.14),
             shadow=dict(type='solid', dx=8, dy=8, fill=INK, rough=.1),
             dots=[dots('tr', 56, 34, color='#2cb8dc', pitch=4.2, r=1.25, norm=1.4, keep=1.8, alpha=.95),
                   dots('br', 60, 36, color='#c4ea16', pitch=4.2, r=1.35, norm=1.4, keep=1.8, alpha=.95)])
OPT = dict(w=400, h=64, radius=3, seed=310, fill='#fdfcf7', slices=(10, 10, 10, 10),
           ink=dict(color=INK, w=1.8, bottom=.3, vary=.12, wobble=.12))
OPT_ON = dict(OPT, seed=311, fill='#eefbc0', night_fill='#3a4424', ink=dict(color=INK, w=2.2, bottom=.4, vary=.12, wobble=.12),
              shadow=dict(type='solid', dx=3, dy=3, fill=INK, rough=.08))

SPECS = {'frame': FRAME, 'frame-dots': FRAME_DOTS, 'card': CARD, 'note': NOTE, 'badge': BADGE, 'cta': CTA, 'qr': QR,
         'act': ACT, 'tag': TAG, 'panel': PANEL, 'opt': OPT, 'opt-on': OPT_ON}


# ── the title's lime brush: a band climbing to the right with dry, streaked ends, and a dark dry flick at its left
def brush(night_mode=False, K=3):
    BW, BH = 340, 62
    rng = np.random.default_rng(312)
    ys, xs = np.mgrid[0:BH * K, 0:BW * K].astype(np.float32)
    xs, ys = (xs + .5) / K, (ys + .5) / K

    def field(sx, sy):
        f = gaussian_filter(rng.standard_normal(xs.shape).astype(np.float32), (sy * K, sx * K), mode='wrap')
        return f / (f.std() + 1e-6)

    # the band's axis runs from (12, 49) to (330, 23); u along it, v across it
    ax, ay, bx, by = 12, 49, 330, 23
    ln = np.hypot(bx - ax, by - ay)
    ex, ey = (bx - ax) / ln, (by - ay) / ln
    u = ((xs - ax) * ex + (ys - ay) * ey) / ln
    v = -(xs - ax) * ey + (ys - ay) * ex
    half = np.interp(u, [0, .15, .8, 1], [11.5, 12, 10, 8.5])
    streak = field(40, .45)                      # long bristle streaks along the stroke
    # the body is solid; the bristles only fray its long edges and break up its two ends
    edge = half + field(10, 10) * .5 + np.clip(streak, -3, 0) * .5 * (np.abs(v) > half - 3)
    body = np.clip((edge - np.abs(v)) * K * .8, 0, 1)
    endw = np.clip(np.minimum(u / .09, (1 - u) / .07), 0, 1)       # 0 at the tips, 1 once past the dry ends
    dry = np.clip((streak + 1.1) * 1.4 - (1 - endw) * 2.2 + endw * 3, 0, 1)
    tip = np.clip(np.minimum(u + .02, 1.01 - u) * 60, 0, 1)
    a = body * dry * tip
    lime = np.array([int(c, 16) for c in (('b4d956' if night_mode else 'cbe63c')[i:i + 2] for i in (0, 2, 4))], np.float32)
    col = np.broadcast_to(lime, xs.shape + (3,)).copy()
    col *= (1 + field(30, 2)[..., None] * .025)
    # the dark flick: two short dry strokes leaning up-right under the band's left end
    flick = np.zeros_like(xs)
    for (x0, y0, x1, y1, w) in ((5, 58, 19, 33, 2.1), (12, 59, 22, 43, 1.5)):
        px, py = xs - x0, ys - y0
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        t = np.clip((px * dx + py * dy) / L2, 0, 1)
        d = np.hypot(px - t * dx, py - t * dy)
        ww = w * (1 - .6 * t)
        flick = np.maximum(flick, np.clip((ww - d) * K + .5, 0, 1) * np.clip(.9 + field(2, 6) * .25, 0, 1))
    navy = np.array([0xcf, 0xd4, 0xcb] if night_mode else [0x12, 0x1f, 0x38], np.float32)
    out_a = flick + a * (1 - flick)
    out_c = (navy * flick[..., None] + col * (a * (1 - flick))[..., None]) / np.maximum(out_a[..., None], 1e-4)
    img = np.zeros(xs.shape + (4,), np.uint8)
    img[..., :3] = np.clip(out_c, 0, 255)
    img[..., 3] = np.round(np.clip(out_a, 0, 1) * 255)
    Image.fromarray(img, 'RGBA').save(f'{OUT}/ct-brush{"-night" if night_mode else ""}.webp', 'WEBP', quality=90,
                                      alpha_quality=95, method=6)
    return {'size': (BW, BH)}


css = {}
only = sys.argv[3:] or list(SPECS) + ['brush']
for name in only:
    if name == 'brush':
        css['brush'] = brush()
        brush(True)
        continue
    spec = SPECS[name]
    css[name] = inkframe.save(spec, f'{OUT}/ct-{name}.webp')
    inkframe.save(night(spec), f'{OUT}/ct-{name}-night.webp')
for k, v in css.items():
    print(k, v)
try:
    old = json.load(open(META))
except (OSError, ValueError):
    old = {}
old.update(css)
json.dump(old, open(META, 'w'), indent=1)
