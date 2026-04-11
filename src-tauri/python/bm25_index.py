import json
from pathlib import Path
from typing import List, Dict

from rank_bm25 import BM25Okapi

import config
from config import get_logger

logger = get_logger(__name__)

CORPUS_PATH = config.DATA_DIR / "bm25_corpus.json"

_corpus: Dict[str, str] = {}
_bm25: BM25Okapi | None = None
_tokenized_corpus: List[List[str]] = []
_doc_ids: List[str] = []


def _tokenize(text: str) -> List[str]:
    """简单中文/英文混合分词：按非字母数字字符拆分。"""
    import re
    return [t.lower() for t in re.split(r"[^a-zA-Z0-9\u4e00-\u9fa5]+", text) if t.strip()]


def _save_corpus():
    CORPUS_PATH.write_text(json.dumps(_corpus, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_corpus():
    global _corpus
    if CORPUS_PATH.exists():
        try:
            _corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            _corpus = {}
    else:
        _corpus = {}


def _rebuild_index():
    global _bm25, _tokenized_corpus, _doc_ids
    _load_corpus()
    _doc_ids = list(_corpus.keys())
    _tokenized_corpus = [_tokenize(_corpus[did]) for did in _doc_ids]
    if _tokenized_corpus:
        _bm25 = BM25Okapi(_tokenized_corpus)
    else:
        _bm25 = None


def add_document(doc_id: str, text: str, filename: str = ""):
    """添加或更新文档到 BM25 索引。"""
    global _bm25
    combined = f"{filename} {text}".strip()
    _corpus[doc_id] = combined
    _save_corpus()
    _rebuild_index()


def delete_document(doc_id: str):
    """从 BM25 索引删除文档。"""
    global _bm25
    if doc_id in _corpus:
        del _corpus[doc_id]
        _save_corpus()
        _rebuild_index()


def query_documents(query_text: str, n_results: int = 10) -> List[Dict]:
    """BM25 关键词检索，返回相关文档列表。"""
    if _bm25 is None or not _tokenized_corpus:
        return []

    tokenized_query = _tokenize(query_text)
    if not tokenized_query:
        return []

    scores = _bm25.get_scores(tokenized_query)
    top_n = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n_results]

    docs = []
    for idx in top_n:
        if scores[idx] <= 0:
            continue
        did = _doc_ids[idx]
        docs.append({
            "id": did,
            "document": _corpus[did],
            "score": float(scores[idx]),
        })
    return docs


def rebuild():
    """强制从当前 corpus 重建 BM25 索引。"""
    _rebuild_index()
    return {"success": True, "docs_count": len(_doc_ids)}


# 模块加载时自动重建
_rebuild_index()
