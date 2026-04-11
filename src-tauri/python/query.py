import hashlib
import json
import time
from pathlib import Path
from typing import List, Dict

import config
from config import get_logger
import vector_store
import bm25_index
import llm_client

logger = get_logger(__name__)


def _cache_key(question: str) -> str:
    return hashlib.md5(question.strip().encode("utf-8")).hexdigest()


def _load_cache() -> Dict[str, Dict]:
    if not config.QUERY_CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(config.QUERY_CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        logger.exception("Failed to load query cache")
        return {}


def _save_cache(data: Dict[str, Dict]):
    config.QUERY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.QUERY_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_query_cache():
    """清空 query 答案缓存。应在文件增删改、reindex 后调用。"""
    if config.QUERY_CACHE_PATH.exists():
        config.QUERY_CACHE_PATH.unlink(missing_ok=True)


def _get_cached_answer(question: str) -> str | None:
    cache = _load_cache()
    key = _cache_key(question)
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > config.QUERY_CACHE_TTL_SECONDS:
        return None
    return entry.get("answer")


def _set_cached_answer(question: str, answer: str):
    cache = _load_cache()
    cache[_cache_key(question)] = {"answer": answer, "ts": time.time()}
    _save_cache(cache)


def _read_wiki_pages(doc_ids: List[str]) -> List[str]:
    """根据 doc_id（即文件 hash）读取对应的 wiki 页内容。"""
    pages = []
    for did in doc_ids:
        wiki_path = config.WIKI_FILES_DIR / f"{did}.md"
        if wiki_path.exists():
            pages.append(wiki_path.read_text(encoding="utf-8"))
        else:
            pages.append(f"[Wiki page not found for id: {did}]")
    return pages


def _build_query_prompt(question: str, wiki_pages: List[str], file_metas: List[Dict], chat_context: List[Dict] = None) -> str:
    files_context = ""
    for i, (page, meta) in enumerate(zip(wiki_pages, file_metas), 1):
        files_context += f"\n## 候选文件 {i}: {meta.get('filename', '未知文件')}\n"
        files_context += f"路径: {meta.get('path', '未知路径')}\n"
        files_context += f"Wiki 摘要:\n{page}\n"

    history_text = ""
    if chat_context:
        for msg in chat_context:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            history_text += f"{role}: {content}\n"

    prompt = f"""{history_text}用户的问题是：
"{question}"

以下是向量检索和关键词检索召回的相关文件信息：
{files_context}

请根据以上信息回答用户的问题。回答要求：
1. 如果找到了相关文件，每个文件必须单独一行输出绝对路径，格式严格为：PATH: C:\\完整\\路径\\文件名.txt
   然后再解释为什么这个文件符合用户的描述。
2. 如果有两个文件在内容上有直接关联（例如涉及同一个人、同一个项目、同一个金额），请额外输出一行：RELATION: 文件名A -> 文件名B | 关联理由
3. 如果没有找到明确相关的文件，请诚实说明。
4. 如果有多个相关文件，按相关程度排序，并分别说明。
5. 回答要简洁、直接，避免过度发挥。
"""
    return prompt


def _rrf_fuse(vector_results: List[Dict], bm25_results: List[Dict], k: int = 60, n: int = 5) -> List[Dict]:
    """使用 Reciprocal Rank Fusion 融合向量检索和 BM25 检索结果。"""
    scores = {}
    info = {}

    for rank, r in enumerate(vector_results):
        did = r["id"]
        scores[did] = scores.get(did, 0) + 1 / (k + rank + 1)
        info[did] = r

    for rank, r in enumerate(bm25_results):
        did = r["id"]
        scores[did] = scores.get(did, 0) + 1 / (k + rank + 1)
        if did not in info:
            info[did] = r

    sorted_ids = sorted(scores.keys(), key=lambda did: scores[did], reverse=True)
    fused = []
    for did in sorted_ids[:n]:
        entry = dict(info[did])
        entry["rrf_score"] = scores[did]
        fused.append(entry)
    return fused


def answer(question: str, n_results: int = 5, context: List[Dict] = None) -> str:
    """回答用户问题：召回 → 读 wiki → LLM 生成答案（带缓存）。"""
    # 0. 查缓存（仅在没有上下文时启用缓存，避免多轮对话被错误命中）
    if not context:
        cached = _get_cached_answer(question)
        if cached is not None:
            logger.debug("Cache hit for question: %s", question[:40])
            return cached

    # 1. 向量召回
    vector_results = vector_store.query_documents(question, n_results=10)
    # 2. BM25 召回
    bm25_results = bm25_index.query_documents(question, n_results=10)
    # 3. RRF 融合
    results = _rrf_fuse(vector_results, bm25_results, k=60, n=n_results)

    if not results:
        return "未找到任何相关文件。请尝试上传更多文档后再提问。"

    doc_ids = [r["id"] for r in results]
    file_metas = []
    for did in doc_ids:
        # 优先从向量结果取 metadata，否则简单兜底
        meta = next((r["metadata"] for r in vector_results if r["id"] == did), None)
        if meta is None:
            meta = {"filename": "未知", "path": "", "summary": "", "tags": ""}
        file_metas.append(meta)

    # 4. 读取 wiki 页
    wiki_pages = _read_wiki_pages(doc_ids)

    # 5. 调用 LLM
    prompt = _build_query_prompt(question, wiki_pages, file_metas, chat_context=context)
    try:
        answer_text = llm_client.chat_completion(
            system_prompt="你是一个个人文件管理助手，擅长根据用户的问题从已有文件中定位最相关的答案。",
            user_prompt=prompt,
            temperature=0.3,
            model=config.LLM_QUERY_MODEL,
        )
    except llm_client.LLMError:
        logger.warning("LLM unavailable, falling back to path list")
        # 降级：直接返回 Top-3 文件路径（降级结果不入缓存，因为下次 LLM 可能恢复）
        paths = [m.get("path", "") for m in file_metas[:3] if m.get("path")]
        if not paths:
            return "未找到任何相关文件。请尝试上传更多文档后再提问。"
        return "\n".join(f"PATH: {p}" for p in paths) + "\n（LLM 服务暂时不可用，仅返回最相关的文件路径）"

    # 6. 写入缓存（仅在没有上下文时缓存）
    if not context:
        _set_cached_answer(question, answer_text)
    return answer_text


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python query.py '你的问题'")
        sys.exit(1)
    q = sys.argv[1]
    logger.info("Query: %s", q)
    print(answer(q))
