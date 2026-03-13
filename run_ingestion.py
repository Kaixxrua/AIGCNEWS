import asyncio
import logging
import sys
import os

# 确保能找到 backend 模块
sys.path.append(os.path.join(os.path.dirname(__file__), "."))

from backend.app.services.ingestion.pipeline import run_ingestion_pipeline_async

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
        # limit=10 表示每个源抓取 10 条
        # enable_ai_scoring=False：跳过 LLM 评分，避免 429 限流，尽快完成入库
        stats = await run_ingestion_pipeline_async(limit=10, enable_ai_scoring=False)

        logger.info("✅ Ingestion Completed Successfully!")
        logger.info("📊 Ingestion Stats:")
        for source, count in stats.items():
            logger.info(f"   - {source.upper()}: {count} items")

    except Exception as e:
        logger.error(f"❌ Ingestion Failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
