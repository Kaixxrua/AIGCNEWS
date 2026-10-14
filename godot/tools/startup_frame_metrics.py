"""Read-only pixel comparison of matched QHD captures; never modifies images.

Metrics supplement personal full-frame inspection, not a visual pass. Clock,
framing, DPR, day/night and internal render scale must be verified separately.
Dragon/creature poses can differ even at clock zero; use regional results too.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


REGIONS = {
    "full_frame": (0, 0, 2560, 1440),
    "castle": (1370, 90, 2050, 400),
    "meadow": (380, 400, 1820, 735),
    "water": (1890, 670, 2190, 815),
    "right_tree": (2070, 855, 2410, 1240),
}


def compare(before, after):
    frames = []
    for path in (before, after):
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (2560, 1440):
                raise ValueError("Both inputs must be actual 2560x1440 PNGs")
            frames.append(np.asarray(image.convert("RGB"), dtype=np.float32))
    results = {}
    for name, (x0, y0, x1, y1) in REGIONS.items():
        a, b = (frame[y0:y1, x0:x1] for frame in frames)
        delta = b - a
        absolute = np.abs(delta)
        results[name] = {
            "bounds": [x0, y0, x1, y1],
            "rgbMeanAbsoluteDifference255": round(float(absolute.mean()), 5),
            "rgbRmse255": round(float(np.sqrt(np.mean(delta * delta))), 5),
            "p99MaxChannelDifference255": round(float(np.percentile(absolute.max(axis=2), 99)), 3),
            "fractionPixelsWithinOneLevel": round(float((absolute.max(axis=2) <= 1).mean()), 6),
            "meanRgbBefore": np.round(a.mean(axis=(0, 1)), 3).tolist(),
            "meanRgbAfter": np.round(b.mean(axis=(0, 1)), 3).tolist(),
        }
    return {"before": str(before.resolve()), "after": str(after.resolve()),
            "dimensions": [2560, 1440], "regions": results,
            "note": "Pixel metrics only. No resizing, image edits or automatic visual acceptance."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(compare(args.before, args.after), indent=2)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(report + "\n")
    print(report)
