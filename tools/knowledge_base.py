import json
import re
from pathlib import Path
from typing import Any


KNOWLEDGE_BASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "knowledge_base.json"
)


def _tokenize(text: str) -> set[str]:
    """Convert text into a normalized set of searchable words."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _load_knowledge_base() -> list[dict[str, Any]]:
    """Load support articles from the local JSON file."""
    if not KNOWLEDGE_BASE_PATH.exists():
        raise FileNotFoundError(
            f"Knowledge base not found: {KNOWLEDGE_BASE_PATH}"
        )

    with KNOWLEDGE_BASE_PATH.open("r", encoding="utf-8") as file:
        articles = json.load(file)

    if not isinstance(articles, list):
        raise ValueError("Knowledge base must contain a JSON list.")

    return articles


def search_knowledge_base(query: str) -> dict[str, Any]:
    """
    Search the local support knowledge base.

    Ranking is based on deterministic token overlap.
    This is a simulated search function, not semantic retrieval.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Query must be a non-empty string.")

    query_tokens = _tokenize(query)

    if not query_tokens:
        return {
            "query": query,
            "result_count": 0,
            "results": []
        }

    articles = _load_knowledge_base()
    ranked_results = []

    for article in articles:
        searchable_text = " ".join([
            article.get("title", ""),
            article.get("category", ""),
            " ".join(article.get("keywords", [])),
            article.get("content", "")
        ])

        article_tokens = _tokenize(searchable_text)
        matching_tokens = query_tokens.intersection(article_tokens)

        if not matching_tokens:
            continue

        score = len(matching_tokens) / len(query_tokens)

        ranked_results.append({
            "id": article["id"],
            "category": article["category"],
            "title": article["title"],
            "content": article["content"],
            "score": round(score, 4)
        })

    # Deterministic ordering: highest score first, then article ID.
    ranked_results.sort(
        key=lambda item: (-item["score"], item["id"])
    )

    results = ranked_results[:3]

    return {
        "query": query,
        "result_count": len(results),
        "results": results
    }
