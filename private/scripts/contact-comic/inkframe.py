"""Generic hand-inked comic frame, rendered as one 9-slice RGBA layer with a transparent interior.

The element paints its own fill (CSS background); this layer adds what a pen would: a wobbling ink
line, the drawn shadow (an outlined extrusion, a solid ink block or a dry-brush stroke), a halftone
patch in the bottom-right corner and an optional speech-tail wedge at the bottom-left.

Geometry is in CSS px at the element's size in the concept, rendered at K x. `render(spec)` returns
the image and the CSS numbers (canvas pads and the 9-slice widths).
"""
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

K = 3


def hexc(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], np.float32)


def sdpoly(xs, ys, P):
    """Signed distance to a convex or concave polygon (negative inside)."""
    d = np.full(xs.shape, np.inf, np.float32)
    sign = np.ones(xs.shape, np.float32)
    n = len(P)
    for i in range(n):
        (ax, ay), (bx, by) = P[i], P[i - 1]
        ex, ey = bx - ax, by - ay
        wx, wy = xs - ax, ys - ay
        t = np.clip((wx * ex + wy * ey) / (ex * ex + ey * ey), 0, 1)
        d = np.minimum(d, np.hypot(wx - ex * t, wy - ey * t))
        c1 = ys >= ay
        c2 = ys < by
        c3 = ex * wy > ey * wx
        flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
        sign = np.where(flip, -sign, sign)
    return sign * d


def render(spec):
    rng = np.random.default_rng(spec.get('seed', 7))
    W, H = float(spec['w']), float(spec['h'])
    r = spec.get('radius', 6)
    ink = spec['ink']
    sh = spec.get('shadow') or {'type': 'none', 'dx': 0, 'dy': 0}
    dots = spec.get('dots')
    tail = spec.get('tail')
    dx, dy = sh.get('dx', 0), sh.get('dy', 0)
    slant = spec.get('slant', 0)
    poly = spec.get('poly')
    spine = spec.get('spine')
    dot_list = dots if isinstance(dots, list) else ([dots] if dots else [])
    PL, PT = int(np.ceil(max(-dx, 0))) + 2, int(np.ceil(max(-dy, 0))) + 2
    PR = int(np.ceil(max(dx, 0))) + 2
    PB = int(np.ceil(max(dy, 0, (tail['h'] + tail.get('y', 0)) if tail else 0))) + 3
    if spec.get('pad'):                           # a shared canvas for layers composited together
        PT, PR, PB, PL = (max(a, b) for a, b in zip((PT, PR, PB, PL), spec['pad']))
    CW, CH = int(W) + PL + PR, int(H) + PT + PB
    ys, xs = np.mgrid[0:CH * K, 0:CW * K].astype(np.float32)
    xs = (xs + .5) / K - PL
    ys = (ys + .5) / K - PT

    def field(sx, sy, amp=1.0):
        g = rng.standard_normal(xs.shape).astype(np.float32)
        f = gaussian_filter(g, (sy * K, sx * K), mode='wrap')
        return f / (f.std() + 1e-6) * amp

    def sdrr(x0, y0, x1, y1, rr):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        qx = np.abs(xs - cx) - ((x1 - x0) / 2 - rr)
        qy = np.abs(ys - cy) - ((y1 - y0) / 2 - rr)
        return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - rr

    def cover(s):
        return np.clip(-s * K + .5, 0, 1)

    alpha = np.zeros(xs.shape, np.float32)

    # colour accumulates premultiplied so layers blend correctly on a transparent canvas
    prem = np.zeros(xs.shape + (3,), np.float32)

    def paint(col, a):
        nonlocal prem, alpha
        a = np.clip(a, 0, 1)
        c = (hexc(col) if isinstance(col, str) else col)
        prem = prem * (1 - a[..., None]) + c * a[..., None]
        alpha = a + alpha * (1 - a)

    def shape(ox, oy):
        # the card's outline, optionally with its top edge dropping toward the left (slant) or as a free polygon
        if poly:
            return sdpoly(xs - ox, ys - oy, poly)
        if not slant:
            return sdrr(ox, oy, W + ox, H + oy, r)
        x = np.clip((xs - ox) / W, 0, 1)
        top = slant * (1 - x)
        yw = (ys - oy - top) * H / (H - top) + oy
        cx, cy = ox + W / 2, oy + H / 2
        qx = np.abs(xs - cx) - (W / 2 - r)
        qy = np.abs(yw - cy) - (H / 2 - r)
        return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r

    top_line, bottom_line = spec.get('top_line'), spec.get('bottom_line')

    def top_at(x):
        # a polygon's top and bottom edges, as piecewise-linear [x, y] points, place the corner dots
        if top_line:
            return np.interp(x, [p[0] for p in top_line], [p[1] for p in top_line])
        return slant * (1 - np.clip(x / W, 0, 1)) if slant else 0

    def bottom_at(x):
        if bottom_line:
            return np.interp(x, [p[0] for p in bottom_line], [p[1] for p in bottom_line])
        return H

    d = shape(0, 0)
    wob = field(14, 14, ink.get('wobble', .3))
    centre = -ink['w'] / 2 + .1 + wob
    side = {
        'top': np.clip(1 - (ys - top_at(xs)) / 8, 0, 1), 'left': np.clip(1 - xs / 8, 0, 1),
        'bottom': np.clip(1 - (bottom_at(xs) - ys) / 8, 0, 1), 'right': np.clip(1 - (W - xs) / 8, 0, 1),
    }
    width = ink['w'] + sum(ink.get(k, 0) * v for k, v in side.items()) + field(9, 9, ink.get('vary', .22))
    width = np.clip(width, .9, ink['w'] * 2.2)
    inside = np.clip((centre - width / 2 - d) * K, 0, 1)

    # ── shadow (beneath everything) ──
    only_dots = spec.get('only_dots')             # the halftone alone, as a layer shown separately
    kind = 'none' if only_dots else sh.get('type', 'none')
    if kind != 'none':
        ds = shape(dx, dy) + field(10, 3, sh.get('rough', .15))
        body = cover(ds) * (1 - cover(d - centre))           # only where the card does not cover it
        if kind == 'extrude':
            ow = sh.get('outline_w', 1.1)
            edge = np.clip((ow - np.abs(ds + ow / 2)) * K + .5, 0, 1)
            paint(sh['fill'], body)
            if sh.get('texture'):                            # faint dry-brush streaks in the band
                prem += (field(18, .6, sh['texture']) * body)[..., None]
            # the band darkens where it meets the card's line and its own outline
            near_card = np.clip(1 - (d - centre - width / 2) / sh.get('shade_w', 1.3), 0, 1)
            near_out = np.clip(1 - (-ds - ow) / sh.get('shade_w', 1.3), 0, 1)
            paint(sh['outline'], body * np.maximum(near_card * .6, near_out * .35))
            paint(sh['outline'], edge * cover(ds - .2) * (1 - cover(d - centre)))
        elif kind == 'solid':
            paint(sh['fill'], body)
            tint = sh.get('tint')
            if tint:                                         # patches of a second colour wandering along the band
                blob = field(tint.get('sx', 40), tint.get('sy', 40), 1)
                paint(tint['color'], body * np.clip(blob * tint.get('amp', .6) + tint.get('bias', 0), 0, tint.get('max', .9)))
        elif kind == 'dry':
            t = np.clip(xs / W, 0, 1)
            s = np.clip(ys / H, 0, 1)
            is_b = np.clip((ys - (H - 3)) / 3, 0, 1)
            base = np.interp(t, *sh['bottom']) * is_b + np.interp(s, *sh['right']) * (1 - is_b)
            dens = np.clip(base + field(26, .55, .22) * is_b + field(.55, 26, .18) * (1 - is_b), 0, 1)
            ks = np.array([k for k, _ in sh['ramp']], np.float32)
            cs = np.stack([hexc(c) for _, c in sh['ramp']])
            col = np.stack([np.interp(dens, ks, cs[:, i]) for i in range(3)], -1)
            paint(col, body * np.clip(dens * 3.3 - .15, 0, 1))
    tail_line = None
    if tail:
        # a speech-bubble wedge hanging off the bottom-left: filled like the card, outlined in ink,
        # and breaking the card's bottom line where it joins
        x0, tw, th, ty = tail['x'], tail['w'], tail['h'], tail.get('y', 0)
        P = [(x0, H - 1), (x0 + tw, H - 1), (x0 - tail.get('lean', 5), H + ty + th)]
        sd = sdpoly(xs, ys, P)
        tw_ink = tail.get('ink_w', ink['w'])
        if tail.get('fill'):
            paint(tail['fill'], cover(sd))
        tail_line = np.clip((tw_ink / 2 - np.abs(sd + tw_ink / 2 - .2)) * K + .5, 0, 1) * (ys > H - .5)
        tail_hole = cover(sd + tw_ink) * (ys > H - 4)

    if spec.get('fill') and not only_dots:
        paint(spec['fill'], cover(d - centre))
    for g in spec.get('glow', []):
        # a colour washing in from one edge: strongest on the line p0-p1, gone `w` px inside it
        (ax, ay), (bx, by) = g['p0'], g['p1']
        ex, ey = bx - ax, by - ay
        ln = np.hypot(ex, ey)
        dist = np.abs((xs - ax) * ey - (ys - ay) * ex) / ln
        t = np.clip(((xs - ax) * ex + (ys - ay) * ey) / ln ** 2, 0, 1)
        along = np.interp(t, *g['along']) if g.get('along') else 1
        paint(g['color'], cover(d - centre) * np.clip(1 - dist / g['w'], 0, 1) ** g.get('pow', 1) * g.get('alpha', 1) * along)
    if spine:
        # a coloured band down the left side, ruled off by a second ink line
        paint(spine['color'], cover(d - centre) * np.clip((spine['w'] - xs) * K + .5, 0, 1))

    # ── halftone patches in the corners, inside the line ──
    for dots in dot_list:
        pitch, ang = dots['pitch'], np.deg2rad(dots.get('angle', 45))
        ca, sa = np.cos(ang), np.sin(ang)
        u = (xs * ca + ys * sa) / pitch
        v = (-xs * sa + ys * ca) / pitch
        ui, vi = np.round(u), np.round(v)
        cx = (ui * ca - vi * sa) * pitch
        cy = (ui * sa + vi * ca) * pitch
        corner = dots.get('corner', 'br')
        dr = W - cx if corner[1] == 'r' else cx - (spine['w'] if spine else 0)
        db = bottom_at(cx) - cy if corner[0] == 'b' else cy - top_at(cx)
        pn = dots.get('norm', 2)
        g = np.clip(1 - ((np.maximum(dr, 0) / dots['rx']) ** pn + (np.maximum(db, 0) / dots['ry']) ** pn) ** (1 / pn), 0, 1) ** dots.get('falloff', .8)
        if dots.get('edge'):
            # dots running on along the side edge (down it), the top/bottom edge (along it), or both
            along = dots.get('edge_along', 'both')
            down = np.exp(-np.maximum(dr - 4, 0) / dots['edge']) * np.clip(1 - db / dots['ry'] / 1.6, 0, 1)
            across = np.exp(-np.maximum(db - 4, 0) / dots['edge']) * np.clip(1 - dr / dots['rx'] / 1.6, 0, 1)
            g = np.maximum(g, {'side': down, 'rule': across}.get(along, np.maximum(down, across)))
        h1 = np.modf(np.abs(np.sin(ui * 12.9898 + vi * 78.233) * 43758.5453))[0].astype(np.float32)
        h2 = np.modf(np.abs(np.sin(ui * 39.3468 + vi * 11.135) * 24634.6345))[0].astype(np.float32)
        g = np.where(h1 < g * dots.get('keep', 1.3), g, 0)
        rad = dots['r'] * np.sqrt(np.clip(g, 0, 1)) * (.75 + .45 * h2)
        dist = np.hypot(xs - cx, ys - cy)
        if dots.get('smear'):
            # some dots are dragged into short vertical strokes, as a dry pen does
            h3 = np.modf(np.abs(np.sin(ui * 7.13 + vi * 91.7) * 15731.743))[0].astype(np.float32)
            ln = np.where(h3 < dots['smear'] * g, pitch * (.3 + .5 * h3 / max(dots['smear'], 1e-3)), 0)
            sd = np.hypot(xs - cx, np.maximum(np.abs(ys - cy) - ln / 2, 0)) + (ln > 0) * rad * .45
            dist = np.minimum(dist, sd)
        cov = np.clip((rad - dist) * K + .5, 0, 1) * (rad > .05) * inside * dots.get('alpha', 1)
        paint(dots['color'], cov)

    # ── the ink line, with optional corner overshoot strokes ──
    line = np.clip((width / 2 - np.abs(d - centre)) * K + .5, 0, 1)
    if spine:
        sw = spine.get('ink_w', ink['w'] * .8)
        line = np.maximum(line, np.clip((sw / 2 - np.abs(xs - spine['w'] - sw / 2 + field(12, 12, .15))) * K + .5, 0, 1) * inside)
    for (cx0, cy0, ex, ey, ln) in spec.get('overshoot', []):
        # a straight stroke continuing an edge past its corner: from (cx0,cy0) along (ex,ey) for ln px
        px, py = xs - cx0, ys - cy0
        tt = np.clip(px * ex + py * ey, 0, ln)
        dist = np.hypot(px - tt * ex, py - tt * ey)
        taper = 1 - tt / ln
        line = np.maximum(line, np.clip((ink['w'] * .45 * taper + .2 - dist) * K + .5, 0, 1))
    inner = spec.get('inner')
    if inner:
        # a second, lighter line just inside the top and left edges, fading along them
        off = inner.get('off', 2.2)
        l2 = np.clip((inner['w'] / 2 - np.abs(d - (centre - width / 2 - off))) * K + .5, 0, 1)
        along = np.maximum(np.clip(1 - ys / (off + 3), 0, 1) * np.clip(1 - xs / (W * .7), 0, 1),
                           np.clip(1 - xs / (off + 3), 0, 1) * np.clip(1 - ys / (H * .9), 0, 1))
        paint(inner['color'], l2 * np.clip(along * 1.6, 0, 1) * inner.get('alpha', 1))
    if tail_line is not None:
        if tail.get('fill'):
            line = line * (1 - tail_hole)
        line = np.maximum(line, tail_line)
    if only_dots:
        pass
    elif ink.get('color2'):
        # the line darkens toward the named sides (a pen pressed harder along the bottom and right)
        wmix = np.clip(sum(ink['mix'].get(k, 0) * v for k, v in side.items()), 0, 1)[..., None]
        paint(hexc(ink['color']) * (1 - wmix) + hexc(ink['color2']) * wmix, line)
    else:
        paint(ink['color'], line)

    out = np.zeros(xs.shape + (4,), np.uint8)
    a = np.clip(alpha, 0, 1)
    col = np.where(a[..., None] > 1e-4, prem / np.maximum(a[..., None], 1e-4), 0)
    out[..., :3] = np.clip(col, 0, 255) * (a[..., None] > 1 / 255)
    out[..., 3] = np.round(a * 255)
    img = Image.fromarray(out, 'RGBA')

    # 9-slice widths (CSS px, measured on the canvas): corners hold the rounding, the dots and the tail
    def need(side):
        out = 0
        for dd in dot_list:
            c = dd.get('corner', 'br')
            reach = 1.6 if dd.get('edge') else 1      # edge dots run on along both sides of the corner
            if side in ('t', 'b') and c[0] == side:
                out = max(out, dd['ry'] * reach + 2 + (slant if side == 't' else 0))
            if side in ('l', 'r') and c[1] == side:
                out = max(out, dd['rx'] * reach + 2 + (spine['w'] if spine and side == 'l' else 0))
        return out
    ends = spec.get('ends', 0)                    # a polygon's ragged ends stay in the side slices
    sl_t = int(np.ceil(PT + max(r + 3, slant + ink['w'] * 2 + 3, need('t'))))
    sl_l = int(np.ceil(PL + max(r + 3, (tail['x'] + tail['w'] + 3) if tail else 0, spine['w'] + 4 if spine else 0, ends, need('l'))))
    sl_r = int(np.ceil(PR + max(r + 3, ends, need('r'))))
    sl_b = int(np.ceil(PB + max(r + 3, need('b'))))
    if spec.get('slices'):                        # explicit widths (t, r, b, l) from the element's edge
        t, rr, b, l = spec['slices']
        sl_t, sl_r, sl_b, sl_l = PT + t, PR + rr, PB + b, PL + l
    # opposing slices must leave a middle band, or the edges vanish
    sl_b = min(sl_b, CH - sl_t - 2)
    sl_r = min(sl_r, CW - sl_l - 2)
    return img, {'pad': (PT, PR, PB, PL), 'slice': (sl_t, sl_r, sl_b, sl_l), 'size': (CW, CH)}


def save(spec, path):
    img, meta = render(spec)
    img.save(path, 'WEBP', quality=90, alpha_quality=95, method=6)
    return meta
