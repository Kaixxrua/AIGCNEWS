"""独立爬虫包装器集合。

每个爬虫继承 BaseCrawler，封装 source_*.py 中的底层采集函数，
提供统一接口、异常隔离和标准化 CrawlResult 输出。
"""

from backend.app.services.ingestion.crawlers.arxiv_crawler import ArxivCrawler
from backend.app.services.ingestion.crawlers.dailyhot_crawler import DailyHotCrawler
from backend.app.services.ingestion.crawlers.github_crawler import GitHubCrawler
from backend.app.services.ingestion.crawlers.hackernews_crawler import HackerNewsCrawler
from backend.app.services.ingestion.crawlers.news_crawler import NewsCrawler
from backend.app.services.ingestion.crawlers.producthunt_crawler import (
    ProductHuntCrawler,
)
from backend.app.services.ingestion.crawlers.x_crawler import XCrawler

__all__ = [
    "ArxivCrawler",
    "DailyHotCrawler",
    "GitHubCrawler",
    "NewsCrawler",
    "ProductHuntCrawler",
    "HackerNewsCrawler",
    "XCrawler",
]
