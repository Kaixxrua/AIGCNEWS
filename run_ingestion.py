import asyncio
import logging
import os
import sys

# 确保能找到 backend 模块
sys.path.append(os.path.join(os.path.dirname(__file__), "."))

from backend.app.core.postgres_database import postgres_database
from backend.app.repositories.application_repository_factory import (
    create_application_repositories,
)
from backend.app.services.ingestion.composition import provide_ingestion_dependencies
from backend.app.services.ingestion.pipeline import (
    join_background_pdf_threads,
    run_ingestion_pipeline_async,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("🚀 Starting Multi-Source Ingestion (Arxiv + GitHub + News)...")
    try:
        await asyncio.to_thread(postgres_database.open)
        repositories = create_application_repositories(postgres=postgres_database)
        try:
            # limit=10 表示每个源抓取 10 条
            stats = await run_ingestion_pipeline_async(
                limit=10,
                dependencies=provide_ingestion_dependencies(
                    repositories=repositories,
                ),
            )
            # CLI 是一次性进程：退出前必须等后台 Arxiv PDF 线程（落盘 + 向量化）
            # 跑完，否则 daemon 线程随进程退出被杀。该线程要写 documents 表，
            # 因此 join 必须在 postgres_database.close() 之前。
            await asyncio.to_thread(join_background_pdf_threads)
        finally:
            postgres_database.close()

        logger.info("✅ Ingestion Completed Successfully!")
        logger.info("📊 Ingestion Stats:")
        for source, count in stats.items():
            logger.info(f"   - {source.upper()}: {count} items")

    except Exception as e:
        logger.error(f"❌ Ingestion Failed: {e}", exc_info=True)
        # CLI 供 cron/systemd 调用：失败必须非零退出，调用方才能感知失败。
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
