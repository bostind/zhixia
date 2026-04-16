"""
知匣 FastAPI 服务入口
由 Tauri Rust 端启动和管理生命周期
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

# 确保当前目录在路径中
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

import config
from config import get_logger
import query
import vector_store
import ingest
import watcher
import ingest_worker
import bm25_index

# 创建必要的数据目录
config.WIKI_FILES_DIR.mkdir(parents=True, exist_ok=True)
config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="知匣 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启动后台文件监控（非阻塞）
watcher_thread = None

def _run_watcher():
    logger = get_logger(__name__)
    try:
        watcher.watcher_manager.start()
        # 保持线程存活，防止守护线程退出
        while True:
            time.sleep(1)
    except Exception as e:
        logger.error("Watcher thread error: %s", e)

watcher_thread = threading.Thread(target=_run_watcher, daemon=True)
watcher_thread.start()

# 启动 ingest worker（队列 + hash 去重 + cooldown + 定时扫描）
ingest_worker.start_worker()


def _warmup_vector_store():
    """后台预热向量库，避免首次 API 请求时加载模型卡顿。"""
    logger = get_logger(__name__)
    try:
        start = time.time()
        vector_store.get_collection()
        logger.info("Vector store warmed up in %.2fs", time.time() - start)
    except Exception as e:
        logger.warning("Vector store warmup failed (will retry on first request): %s", e)


warmup_thread = threading.Thread(target=_warmup_vector_store, daemon=True)
warmup_thread.start()


def _startup_ingest():
    """启动时反向清理孤儿数据，再扫描已有文件推入队列。"""
    logger = get_logger(__name__)
    time.sleep(2)
    logger.info("Cleaning up orphaned entries...")
    ingest_worker.cleanup_orphans()
    logger.info("Scanning existing files...")
    for d in config.WATCH_DIRS:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix.lower() in config.SUPPORTED_EXTS:
                ingest_worker.enqueue(f)
    logger.info("Initial scan complete.")

startup_thread = threading.Thread(target=_startup_ingest, daemon=True)
startup_thread.start()


class QueryRequest(BaseModel):
    question: str
    n_results: int = 5
    context: List[dict] = []


class QueryResponse(BaseModel):
    answer: str


class FileItem(BaseModel):
    id: str
    filename: str
    path: str
    summary: Optional[str] = None
    tags: Optional[str] = None
    ext: Optional[str] = None


class FileListResponse(BaseModel):
    files: List[FileItem]
    count: int


class WatchDirsRequest(BaseModel):
    dirs: List[str]


class SettingsRequest(BaseModel):
    api_key: str
    base_url: str
    model: str
    ingest_model: str = ""
    query_model: str = ""


class FeedbackRequest(BaseModel):
    query: str
    file_path: str
    feedback: str


class TagsRequest(BaseModel):
    tags: str


class BatchActionRequest(BaseModel):
    action: str  # "delete" | "reindex"
    ids: List[str]


@app.post("/reindex")
def reindex():
    """强制将所有已有文件加入 ingest 队列，触发全局手动分析。"""
    count = ingest_worker.reindex_all()
    return {"success": True, "queued": count}


@app.post("/bm25_rebuild")
def bm25_rebuild():
    """手动重建 BM25 索引。"""
    return bm25_index.rebuild()


@app.get("/ingest_progress")
def ingest_progress():
    """返回当前 ingest 任务进度。"""
    return {"progress": ingest_worker.get_progress()}


@app.get("/settings")
def get_settings():
    """返回当前 LLM 设置（API Key 脱敏）。"""
    key = config.LLM_API_KEY
    masked_key = f"****{key[-4:]}" if len(key) >= 4 else ("****" if key else "")
    return {
        "api_key": masked_key,
        "base_url": config.LLM_BASE_URL,
        "model": config.LLM_MODEL,
        "ingest_model": config.LLM_INGEST_MODEL,
        "query_model": config.LLM_QUERY_MODEL,
    }


@app.post("/settings")
def save_settings(req: SettingsRequest):
    """保存用户 LLM 设置。"""
    # 如果 api_key 是脱敏值或为空（前端未修改），保留原值避免覆盖
    api_key = req.api_key
    if not api_key or api_key.startswith("****"):
        api_key = config.LLM_API_KEY
    config.save_llm_settings(api_key, req.base_url, req.model, req.ingest_model, req.query_model)
    # 重置 LLM client 缓存
    import llm_client
    llm_client._client = None
    return {"success": True}


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    """收集用户反馈。"""
    log_path = config.DATA_DIR / "feedback_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": time.time(),
        "query": req.query,
        "file_path": req.file_path,
        "feedback": req.feedback,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"success": True}


def _test_llm_connection() -> dict:
    """测试 LLM 连接是否可用。"""
    import llm_client
    try:
        client = llm_client.get_client()
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
            timeout=10,
        )
        if resp and resp.choices:
            return {"ok": True, "message": "连接正常"}
        return {"ok": False, "message": "LLM 返回异常"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "data_dir": str(config.DATA_DIR),
        "llm_ok": None,
        "llm_message": "Use /test_llm for LLM connectivity check",
    }


@app.get("/test_llm")
def test_llm():
    """手动测试 LLM 配置是否可连通。"""
    return _test_llm_connection()


@app.post("/query", response_model=QueryResponse)
def ask(req: QueryRequest):
    answer = query.answer(req.question, n_results=req.n_results, context=req.context)
    return QueryResponse(answer=answer)


@app.get("/files", response_model=FileListResponse)
def list_files():
    try:
        collection = vector_store.get_collection()
        data = collection.get()
        files = []
        if data and data.get("ids"):
            for i, doc_id in enumerate(data["ids"]):
                meta = data["metadatas"][i] if data.get("metadatas") else {}
                _path = meta.get("path", "")
                _ext = Path(_path).suffix.lstrip(".").lower() if _path else ""
                files.append(
                    FileItem(
                        id=doc_id,
                        filename=meta.get("filename", "未知"),
                        path=_path,
                        summary=meta.get("summary", ""),
                        tags=meta.get("tags", ""),
                        ext=_ext,
                    )
                )
        return FileListResponse(files=files, count=len(files))
    except Exception as e:
        return FileListResponse(files=[], count=0)


@app.post("/files/{doc_id}/tags")
def update_tags(doc_id: str, req: TagsRequest):
    """更新文件标签：同步更新向量库 metadata 和 wiki 文件。"""
    logger = get_logger(__name__)
    try:
        collection = vector_store.get_collection()
        data = collection.get(ids=[doc_id])
        if not data or not data.get("ids"):
            return {"success": False, "error": "Document not found"}

        meta = data["metadatas"][0] if data.get("metadatas") else {}
        normalized_tags = req.tags.replace("，", ",").replace("、", ",")
        meta["tags"] = normalized_tags
        vector_store.update_metadata(doc_id, meta)

        # 同步更新 wiki 文件中的标签行
        wiki_path = config.WIKI_FILES_DIR / f"{doc_id}.md"
        if wiki_path.exists():
            lines = wiki_path.read_text(encoding="utf-8").splitlines()
            new_lines = []
            for line in lines:
                if line.strip().startswith("- **标签**:"):
                    new_lines.append(f"- **标签**: {req.tags}")
                else:
                    new_lines.append(line)
            wiki_path.write_text("\n".join(new_lines), encoding="utf-8")

        logger.info("Updated tags for %s: %s", doc_id, req.tags)
        return {"success": True}
    except Exception:
        logger.exception("Failed to update tags for %s", doc_id)
        return {"success": False, "error": str(sys.exc_info()[1])}


@app.post("/files/batch_action")
def batch_action(req: BatchActionRequest):
    """批量删除索引或强制重新分析。"""
    logger = get_logger(__name__)
    if req.action not in {"delete", "reindex"}:
        return {"success": False, "error": "Invalid action"}

    collection = vector_store.get_collection()
    processed = 0
    errors = []

    for doc_id in req.ids:
        try:
            data = collection.get(ids=[doc_id])
            meta = data["metadatas"][0] if data and data.get("metadatas") else {}
            file_path = meta.get("path", "")
            if not file_path:
                errors.append(f"{doc_id}: no path in metadata")
                continue

            path = Path(file_path)
            if req.action == "delete":
                ingest_worker.cleanup(path)
            else:  # reindex
                ingest_worker.force_enqueue(path)
            processed += 1
        except Exception as e:
            logger.exception("Batch action %s failed for %s", req.action, doc_id)
            errors.append(f"{doc_id}: {e}")

    logger.info("Batch %s completed: %s/%s", req.action, processed, len(req.ids))
    return {"success": True, "action": req.action, "processed": processed, "errors": errors}


@app.post("/ingest")
def manual_ingest(path: str):
    target = Path(path)
    if not target.exists():
        return {"success": False, "error": "File not found"}
    try:
        wiki_path = ingest.process_file(target)
        return {"success": True, "wiki_path": wiki_path}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/watch_dirs")
def get_watch_dirs():
    """返回当前监控目录列表。"""
    return {"dirs": [str(d) for d in config.WATCH_DIRS]}


@app.post("/watch_dirs")
def set_watch_dirs(req: WatchDirsRequest):
    """更新监控目录并重启文件监控，同时后台清理旧目录留下的孤儿索引。"""
    valid = [Path(d) for d in req.dirs if Path(d).exists()]
    config.save_watch_dirs(valid)
    watcher.watcher_manager.restart()

    def _cleanup_after_switch():
        time.sleep(1)
        logger = get_logger(__name__)
        logger.info("Watch dirs changed, cleaning up orphaned entries...")
        ingest_worker.cleanup_orphans()
        logger.info("Post-switch cleanup complete.")

    threading.Thread(target=_cleanup_after_switch, daemon=True).start()
    return {"dirs": [str(d) for d in valid]}


@app.get("/status")
def get_status():
    """返回监控目录和索引进度。"""
    watch_dirs = [str(d) for d in config.WATCH_DIRS if d.exists()]
    total_files = 0
    for d in config.WATCH_DIRS:
        if d.exists():
            total_files += sum(1 for f in d.rglob("*") if f.is_file() and f.suffix.lower() in config.SUPPORTED_EXTS)
    indexed_files = 0
    if config.WIKI_FILES_DIR.exists():
        indexed_files = len(list(config.WIKI_FILES_DIR.glob("*.md")))
    return {
        "watch_dirs": watch_dirs,
        "total_files": total_files,
        "indexed_files": indexed_files,
    }


if __name__ == "__main__":
    port = int(os.getenv("ZHIXIA_API_PORT", "8765"))
    # 使用统一的日志配置覆盖 uvicorn 默认日志
    logger = get_logger("uvicorn")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        log_config=None,
    )
