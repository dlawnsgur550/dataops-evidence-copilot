"""Checkpoint lexical retrieval, not the proposed BM25+dense/RRF production RAG."""
import hashlib
import re
from pathlib import Path

from .models import RetrievalHit


class LocalRunbooks:
    version = "lexical-v1"

    async def search(self, query: str) -> list[RetrievalHit]:
        terms = set(re.findall(r"[\w]+", query.lower()))
        scored = []
        for path in sorted((Path(__file__).parent / "runbooks").glob("*.md")):
            content = path.read_text()
            score = len(terms & set(re.findall(r"[\w]+", content.lower())))
            if score:
                scored.append((score, path.stem, content))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [RetrievalHit(doc_id=doc, doc_version="1", chunk_id=doc + ":whole", rank=i,
                             content_hash=hashlib.sha256(content.encode()).hexdigest(), content=content)
                for i, (_, doc, content) in enumerate(scored[:3], 1)]
