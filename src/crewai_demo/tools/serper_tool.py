import os
from typing import Any

import httpx
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class SerperSearchInput(BaseModel):
    query: str = Field(..., description="Search query")
    num_results: int = Field(10, ge=1, le=20, description="Number of results (1-20)")


class SerperSearchTool(BaseTool):
    name: str = "Serper Search"
    description: str = (
        "Searches the web via Serper.dev (Google Search API) and returns titles, links, and snippets."
    )
    args_schema: type[BaseModel] = SerperSearchInput

    def _run(self, query: str, num_results: int = 10) -> str:
        api_key = os.getenv("SERPER_API_KEY")
        if not api_key:
            raise RuntimeError("Missing SERPER_API_KEY in environment/.env")

        payload: dict[str, Any] = {"q": query, "num": num_results}
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}

        with httpx.Client(timeout=30.0) as client:
            resp = client.post("https://google.serper.dev/search", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("organic") or []
        if not results:
            return "No results."

        lines: list[str] = []
        for i, r in enumerate(results[:num_results], start=1):
            title = r.get("title") or ""
            link = r.get("link") or ""
            snippet = r.get("snippet") or ""
            lines.append(f"{i}. {title}\n{link}\n{snippet}".strip())

        return "\n\n".join(lines)

