#!/usr/bin/env python3
"""把 contact 场景私有化 overlay 套用到公共仓前端树。

用法:
  python3 apply.py <公共仓前端根>          # 套用（构建前）
  python3 apply.py <公共仓前端根> --check  # 只核对目标文件是否与 overlay 一致

overlay 文件与公共仓路径一一对应（OVERLAY_ROOT 下相对路径 = 前端 src/ 下相对路径）。
"""
import shutil
import sys
from pathlib import Path

OVERLAY_ROOT = Path(__file__).parent / 'files'
FILES = [
    'components/contact/scene/spriteArt.ts',
    'components/contact/scene/spriteArt.test.ts',
    'components/contact/scene/ContactFieldScene.ts',
]


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    src_root = Path(sys.argv[1]).resolve() / 'src'
    check = '--check' in sys.argv
    if not src_root.is_dir():
        print(f'目标不存在: {src_root}')
        sys.exit(1)
    bad = 0
    for rel in FILES:
        overlay = OVERLAY_ROOT / rel
        target = src_root / rel
        if check:
            same = target.exists() and target.read_bytes() == overlay.read_bytes()
            print(f'{"OK " if same else "DIFF"} {rel}')
            bad += 0 if same else 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(overlay, target)
            print(f'applied {rel}')
    sys.exit(1 if check and bad else 0)


if __name__ == '__main__':
    main()
