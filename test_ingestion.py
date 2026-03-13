from backend.app.services.ingestion.source_arxiv_mcp import fetch_latest_papers


def main() -> None:
    papers = fetch_latest_papers(limit=10)
    for index, paper in enumerate(papers[:3], start=1):
        print(f"{index}. {paper['title']}")


if __name__ == "__main__":
    main()
