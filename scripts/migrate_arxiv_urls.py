#!/usr/bin/env python3
"""M13 数据迁移脚本：更新数据库中 Arxiv 文档的 URL 为 HF 社区页面。

用法：
    python scripts/migrate_arxiv_urls.py [--dry-run]

功能：
  1. 查找 source='arxiv' 且 url 包含 'arxiv.org' 的旧记录
  2. 从 url 中提取 arxiv ID
  3. 将 url 更新为 https://huggingface.co/papers/{id}
  4. --dry-run 模式只打印变更，不写入数据库
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

# 将项目根目录加入 Python 路径
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.repositories.sqlite_repo import SQLiteRepository  # noqa: E402

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")


def extract_arxiv_id(url: str) -> str | None:
    m = _ARXIV_ID_RE.search(url or "")
    return m.group(1) if m else None


def old_doc_id(url: str) -> str:
    """旧版 _doc_id：基于 url 生成 hash（用于找到旧记录的 ID）。"""
    return hashlib.md5(url.encode()).hexdigest()


def new_doc_id(arxiv_id: str) -> str:
    """新版 _doc_id：基于 arxiv_id 生成 hash。"""
    return hashlib.md5(f"arxiv:{arxiv_id}".encode()).hexdigest()


def main(dry_run: bool = False) -> None:
    db = SQLiteRepository()

    with db._connect() as conn:
        rows = conn.execute(
            "SELECT id, url, title FROM documents WHERE source='arxiv' AND url LIKE '%arxiv.org%'"
        ).fetchall()

    print(f"找到 {len(rows)} 条需要迁移的 Arxiv 文档。")

    updated = 0
    skipped = 0

    with db._connect() as conn:
        for row in rows:
            old_id = row["id"]
            old_url = row["url"]
            title = row["title"] or ""

            arxiv_id = extract_arxiv_id(old_url)
            if not arxiv_id:
                print(f"  ⚠ 无法提取 arxiv_id，跳过: {old_url[:80]}")
                skipped += 1
                continue

            new_url = f"https://huggingface.co/papers/{arxiv_id}"
            calculated_new_id = new_doc_id(arxiv_id)

            print(f"  [{arxiv_id}]")
            print(f"    旧 URL: {old_url}")
            print(f"    新 URL: {new_url}")
            print(f"    旧 ID:  {old_id}  →  新 ID: {calculated_new_id}")
            print(f"    标题:   {title[:60]}")

            if not dry_run:
                try:
                    # 先检查新 ID 是否已存在（防止冲突）
                    existing = conn.execute(
                        "SELECT id FROM documents WHERE id=?", (calculated_new_id,)
                    ).fetchone()

                    if existing:
                        # 新 ID 已存在：只需更新旧记录的 url，然后删除重复
                        conn.execute(
                            "UPDATE documents SET url=? WHERE id=?",
                            (new_url, calculated_new_id),
                        )
                        if old_id != calculated_new_id:
                            conn.execute("DELETE FROM documents WHERE id=?", (old_id,))
                        print(f"    → 新 ID 已存在，更新 URL 并清理旧记录 ✓")
                    else:
                        # Step 1: 先更新 url（用旧 id 定位）
                        conn.execute(
                            "UPDATE documents SET url=? WHERE id=?",
                            (new_url, old_id),
                        )
                        # Step 2: 再更新 id（url 已是新值）
                        conn.execute(
                            "UPDATE documents SET id=? WHERE id=?",
                            (calculated_new_id, old_id),
                        )
                        print(f"    → 更新成功 ✓")
                    updated += 1
                except Exception as e:
                    print(f"    → 更新失败: {e}")
                    skipped += 1
            else:
                print(f"    → [DRY RUN] 不写入")
                updated += 1

            print()

    if dry_run:
        print(f"[DRY RUN] 将更新 {updated} 条，跳过 {skipped} 条。")
        print("运行不带 --dry-run 参数以实际执行迁移。")
    else:
        print(f"迁移完成：更新 {updated} 条，跳过 {skipped} 条。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="迁移 Arxiv 文档 URL 为 HF 社区页面")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印变更，不写入数据库",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
