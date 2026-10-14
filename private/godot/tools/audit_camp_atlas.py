"""Read-only native RGBA/frame inspection. Never edits, crops or resizes images."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image


def horizontal_registration(alpha, columns, rows, sample_width=None):
    """Find atlas sampling rectangles, without changing a single image pixel.

    Only accept clear vertical separators near the original grid. Prove every
    visible source pixel belongs to exactly one output frame; reject overlaps,
    cut silhouettes, missing frames or shapes wider than the guarded cell.
    """
    height, width = alpha.shape
    cell_w, cell_h = width // columns, height // rows
    window_w = sample_width or cell_w
    registrations = []
    for row in range(rows):
        band = alpha[row*cell_h:(row+1)*cell_h] >= 32
        occupied = band.any(axis=0)
        cuts = [0]
        for column in range(1, columns):
            expected = column*cell_w
            gaps = [x for x in range(max(4,expected-48),min(width-4,expected+49)) if not occupied[x-4:x+4].any()]
            if not gaps:
                return {'valid': False, 'reason': f'row {row}: no clear separator near column {column}'}
            cuts.append(min(gaps,key=lambda x:abs(x-expected)))
        cuts.append(width)
        bodies = []
        for column in range(columns):
            yy, xx = np.nonzero(band[:,cuts[column]:cuts[column+1]])
            if not xx.size:
                return {'valid':False,'reason':f'row {row} column {column}: empty'}
            bodies.append((int(xx.min())+cuts[column],int(xx.max())+cuts[column]+1))
        coverage = np.zeros_like(band,dtype=np.uint8)
        for column in range(columns):
            yy,xx = np.nonzero(band[:,cuts[column]:cuts[column+1]])
            if not xx.size:
                return {'valid':False,'reason':f'row {row} column {column}: empty'}
            left,right = int(xx.min())+cuts[column],int(xx.max())+cuts[column]+1
            previous_right = bodies[column-1][1] if column else 0
            next_left = bodies[column+1][0] if column+1 < columns else width
            earliest = max(0, right-(window_w-4), previous_right)
            latest = min(width-window_w, left-4, next_left-window_w)
            if earliest>latest:
                return {'valid':False,'reason':f'row {row} column {column}: silhouette does not fit'}
            x = max(earliest,min(column*cell_w,latest))
            yy2,xx2 = np.nonzero(band[:,x:x+window_w])
            bounds = [int(xx2.min()),int(yy2.min()),int(xx2.max())+1,int(yy2.max())+1]
            if bounds[0]<4 or bounds[1]<4 or bounds[2]>window_w-4 or bounds[3]>cell_h-4:
                return {'valid':False,'reason':f'row {row} column {column}: guarded rectangle contains adjacent or clipped art'}
            coverage[:,x:x+window_w] += 1
            registrations.append({'index':row*columns+column,'rect':[x,row*cell_h,window_w,cell_h],
                'bbox':bounds,'anchorX':cell_w//2+column*cell_w-x})
        if not np.all(coverage[band] == 1):
            return {'valid':False,'reason':f'row {row}: visible pixels omitted or duplicated'}
    return {'valid':True,'visiblePixelsPreservedExactlyOnce':True,'frames':registrations}


def inspect(path, columns=8, rows=4, sample_width=None):
    with Image.open(path) as source:
        rgba = np.asarray(source.convert('RGBA'))
        width, height = source.size
        native_mode = source.mode
    if width % columns or height % rows:
        raise ValueError('Atlas must divide into exact native cells')
    cell_w, cell_h = width // columns, height // rows
    frames = []
    alpha = rgba[:, :, 3]
    for row in range(rows):
        for column in range(columns):
            cell = alpha[row * cell_h:(row + 1) * cell_h, column * cell_w:(column + 1) * cell_w]
            yy, xx = np.nonzero(cell >= 32)
            strict_y, strict_x = np.nonzero(cell > 0)
            border = np.ones_like(cell, dtype=bool)
            border[4:-4, 4:-4] = False
            frames.append({'index': row * columns + column, 'rect': [column * cell_w, row * cell_h, cell_w, cell_h],
                'bbox': [int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1] if xx.size else None,
                'strictBounds': [int(strict_x.min()), int(strict_y.min()), int(strict_x.max()) + 1, int(strict_y.max()) + 1] if strict_x.size else None,
                'border4Nonzero': int(((cell > 0) & border).sum()),
                'edgePixels': int((cell[0] >= 32).sum() + (cell[-1] >= 32).sum() + (cell[:, 0] >= 32).sum() + (cell[:, -1] >= 32).sum()),
                'alphaZeroFraction': round(float((cell == 0).mean()), 4)})
    return {'file': str(Path(path).resolve()), 'bytes': Path(path).stat().st_size, 'size': [width, height],
        'nativeMode': native_mode, 'cell': [cell_w, cell_h], 'alphaZeroFraction': round(float((alpha == 0).mean()), 4),
        'alphaPartialFraction': round(float(((alpha > 0) & (alpha < 255)).mean()), 4), 'alphaMax': int(alpha.max()),
        'registration': horizontal_registration(alpha,columns,rows,sample_width), 'frames': frames}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', type=Path, nargs='+')
    parser.add_argument('--columns', type=int, default=8)
    parser.add_argument('--rows', type=int, default=4)
    parser.add_argument('--sample-width', type=int, help='Read-only UV window width; original PNG pixels stay unchanged')
    args = parser.parse_args()
    if args.columns < 1 or args.rows < 1:
        parser.error('Positive grid dimensions required')
    print(json.dumps([inspect(path, columns=args.columns, rows=args.rows, sample_width=args.sample_width) for path in args.images], indent=2))
