import sqlite3
import os

DB_PATH = "./data/sqlite/app.db"

if not os.path.exists(DB_PATH):
    print(f"❌ 错误：找不到数据库文件: {DB_PATH}")
    print(f"当前工作目录: {os.getcwd()}")
else:
    print(f"✅ 找到数据库文件: {DB_PATH}")
    try:
        import sys

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        if "--query" in sys.argv:
            idx = sys.argv.index("--query") + 1
            if idx >= len(sys.argv):
                raise ValueError("--query 后缺少 SQL")
            sql = sys.argv[idx]
            cursor.execute(sql)
            rows = cursor.fetchall()
            if rows:
                for row in rows:
                    print(row)
            else:
                print("(no rows)")
            conn.close()
            sys.exit(0)

        # 1. documents 总行数
        cursor.execute("SELECT count(*) FROM documents")
        count = cursor.fetchone()[0]
        print(f"📊 documents 表中的数据行数: {count}")

        if count > 0:
            # 2. 最新 3 条
            cursor.execute(
                "SELECT id, title, created_at FROM documents ORDER BY created_at DESC LIMIT 3"
            )
            rows = cursor.fetchall()
            print("\n🔍 最新 3 条数据:")
            for row in rows:
                print(f"   - [{row[2]}] {row[1]} (ID: {row[0]})")

            # 3. 检查 score 分布（top_documents 按 score 排序）
            cursor.execute("SELECT count(*) FROM documents WHERE score > 0")
            scored = cursor.fetchone()[0]
            print(f"\n📈 score > 0 的文档数: {scored} / {count}")

            cursor.execute("SELECT MAX(score), MIN(score), AVG(score) FROM documents")
            stats = cursor.fetchone()
            print(
                f"   score 范围: max={stats[0]:.4f}, min={stats[1]:.4f}, avg={stats[2]:.4f}"
            )

            # 4. published_date 分布
            cursor.execute(
                "SELECT published_date, count(*) FROM documents GROUP BY published_date ORDER BY published_date DESC LIMIT 5"
            )
            dates = cursor.fetchall()
            print("\n📅 published_date 分布 (最近 5 个日期):")
            for d in dates:
                print(f"   - {d[0]}: {d[1]} 篇")
        else:
            print("⚠️ 表是空的！数据采集步骤没有写入 SQLite。")

        conn.close()
    except Exception as e:
        print(f"❌ 读取数据库出错: {e}")
