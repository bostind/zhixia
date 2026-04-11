import hashlib
import json
import queue
import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Lock

import config
import ingest
import vector_store
import bm25_index
import extractor
import query
from config import get_logger

logger = get_logger(__name__)

# 从配置读取，若未定义则使用默认值
COOLDOWN_SECONDS = getattr(config, "INGEST_COOLDOWN_SECONDS", 1800)
SCAN_INTERVAL_SECONDS = getattr(config, "INGEST_SCAN_INTERVAL_SECONDS", 1800)
MANIFEST_PATH = getattr(config, "INGEST_MANIFEST", getattr(config, "DATA_DIR", Path(".")) / "ingest_manifest.json")
ERROR_LOG_PATH = getattr(config, "DATA_DIR", Path(".")) / "ingest_errors.json"

_manifest = {}
_manifest_lock = Lock()

_task_queue = queue.Queue()
_seen_set = set()
_seen_lock = Lock()

_last_enqueue_time = {}
_last_time_lock = Lock()

# Ingest 进度追踪（内存中，供 /ingest_progress 读取）
_INGEST_PROGRESS = {}
_progress_lock = Lock()

MAX_RETRIES = 3


def _is_junk(path: Path) -> bool:
    if path.suffix.lower() in config.JUNK_EXTS:
        return True
    for pattern in config.JUNK_NAME_PATTERNS:
        if path.name.startswith(pattern):
            return True
    return False


def _load_error_log() -> dict:
    if ERROR_LOG_PATH.exists():
        try:
            return json.loads(ERROR_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_error_log(errors: dict):
    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ERROR_LOG_PATH.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_progress(key: str, status: str, detail: str = ""):
    with _progress_lock:
        _INGEST_PROGRESS[key] = {
            "status": status,
            "detail": detail,
            "updated_at": datetime.now().isoformat(),
        }
        # 只保留最近 50 条
        if len(_INGEST_PROGRESS) > 50:
            oldest = sorted(_INGEST_PROGRESS.items(), key=lambda x: x[1]["updated_at"])[:len(_INGEST_PROGRESS) - 50]
            for k, _ in oldest:
                del _INGEST_PROGRESS[k]


def get_progress() -> list:
    with _progress_lock:
        return [{"path": k, **v} for k, v in _INGEST_PROGRESS.items()]


def _load_manifest():
    global _manifest
    if MANIFEST_PATH.exists():
        try:
            _manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            _manifest = {}
    else:
        _manifest = {}


def _save_manifest():
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(_manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _compute_hash(file_path: Path) -> str:
    try:
        return hashlib.md5(file_path.read_bytes()).hexdigest()
    except Exception:
        return ""


def _should_enqueue(file_path: Path) -> bool:
    """检查 cooldown、mtime、size 和 content hash，决定是否需要入队。"""
    key = str(file_path.resolve())
    now = time.time()

    with _last_time_lock:
        last_time = _last_enqueue_time.get(key, 0)
        if now - last_time < COOLDOWN_SECONDS:
            return False
        _last_enqueue_time[key] = now

    # 快速路径：mtime + size 没变则跳过
    try:
        stat = file_path.stat()
    except Exception:
        return False

    mtime = stat.st_mtime
    size = stat.st_size

    with _manifest_lock:
        record = _manifest.get(key)
        if record and record.get("mtime") == mtime and record.get("size") == size:
            return False

        # hash 检查
        content_hash = _compute_hash(file_path)
        if record and record.get("content_hash") == content_hash:
            return False

    return True


def enqueue(file_path: Path):
    """由 watcher 事件调用，将文件加入 ingest 队列。"""
    if not file_path.is_file():
        return
    if _is_junk(file_path):
        return
    if file_path.suffix.lower() not in config.SUPPORTED_EXTS:
        return
    if not _should_enqueue(file_path):
        return

    key = str(file_path.resolve())
    with _seen_lock:
        if key in _seen_set:
            return
        _seen_set.add(key)
    _update_progress(key, "queued")
    _task_queue.put(key)


def force_enqueue(file_path: Path):
    """强制入队（用于手动全局分析），不检查 cooldown 和 hash。"""
    if not file_path.is_file():
        return
    if _is_junk(file_path):
        return
    if file_path.suffix.lower() not in config.SUPPORTED_EXTS:
        return

    key = str(file_path.resolve())
    with _last_time_lock:
        _last_enqueue_time[key] = time.time()
    with _seen_lock:
        if key not in _seen_set:
            _seen_set.add(key)
            _task_queue.put(key)
    _update_progress(key, "queued")


def _update_manifest(file_path: Path):
    try:
        stat = file_path.stat()
    except Exception:
        return
    key = str(file_path.resolve())
    with _manifest_lock:
        _manifest[key] = {
            "content_hash": _compute_hash(file_path),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "last_ingest_at": datetime.now().isoformat(),
        }
        _save_manifest()


def _process_one(file_path_str: str):
    path = Path(file_path_str)
    if not path.exists():
        return
    logger.info("Processing: %s", path)
    key = str(path.resolve())
    _update_progress(key, "processing")
    try:
        ingest.process_file(path)
        _update_manifest(path)
        # 更新 BM25 索引
        text = extractor.extract_text(path)
        bm25_index.add_document(hashlib.md5(key.encode("utf-8")).hexdigest()[:16], text, filename=path.name)
        _update_progress(key, "done")
        # 文件内容变化后，清空 query 缓存
        try:
            query.clear_query_cache()
        except Exception:
            pass
        # 清除错误记录
        errors = _load_error_log()
        if key in errors:
            del errors[key]
            _save_error_log(errors)
    except Exception:
        logger.exception("Failed to ingest %s", path)
        _update_progress(key, "error", detail=str(sys.exc_info()[1]))
        errors = _load_error_log()
        errors[key] = errors.get(key, 0) + 1
        _save_error_log(errors)


def _worker_loop():
    logger.info("Ingest worker started.")
    while True:
        try:
            task = _task_queue.get(timeout=5)
        except queue.Empty:
            continue
        try:
            _process_one(task)
        finally:
            with _seen_lock:
                _seen_set.discard(task)
            _task_queue.task_done()


def _periodic_scan_loop():
    """定时全量扫描，作为 watchdog 事件的兜底，并自动重试之前失败的文件。"""
    while True:
        time.sleep(SCAN_INTERVAL_SECONDS)
        logger.info("Periodic scan started")
        errors = _load_error_log()
        for d in config.WATCH_DIRS:
            if not d.exists():
                continue
            for f in d.rglob("*"):
                if f.is_file() and f.suffix.lower() in config.SUPPORTED_EXTS:
                    key = str(f.resolve())
                    err_count = errors.get(key, 0)
                    if err_count >= MAX_RETRIES:
                        continue
                    enqueue(f)
        logger.info("Periodic scan queued files")


def start_worker():
    _load_manifest()
    t_worker = Thread(target=_worker_loop, daemon=True)
    t_worker.start()
    t_scan = Thread(target=_periodic_scan_loop, daemon=True)
    t_scan.start()


def cleanup(file_path: Path):
    """文件被删除或重命名时，清理对应的向量、wiki、索引和日志记录。"""
    key = str(file_path.resolve())
    doc_id = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
    wiki_path = config.WIKI_FILES_DIR / f"{doc_id}.md"
    relative_link = f"files/{doc_id}.md"

    logger.info("Cleanup %s (doc_id=%s)", file_path, doc_id)

    # 0. 清空 query 缓存
    try:
        query.clear_query_cache()
    except Exception:
        pass

    # 1. 删除向量
    try:
        vector_store.delete_document(doc_id)
        logger.info("Vector removed: %s", doc_id)
    except Exception:
        logger.exception("Vector remove skipped")

    # 2. 删除 BM25 索引
    try:
        bm25_index.delete_document(doc_id)
        logger.info("BM25 removed: %s", doc_id)
    except Exception:
        logger.exception("BM25 remove skipped")

    # 3. 删除 wiki 文件
    try:
        if wiki_path.exists():
            wiki_path.unlink()
            logger.info("Wiki removed: %s", wiki_path)
    except Exception:
        logger.exception("Wiki remove failed")

    # 4. 从 index.md 中移除对应行
    try:
        if config.WIKI_INDEX.exists():
            lines = config.WIKI_INDEX.read_text(encoding="utf-8").splitlines()
            new_lines = [l for l in lines if not l.strip().startswith(f"- [[{relative_link}|")]
            if len(new_lines) != len(lines):
                config.WIKI_INDEX.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                logger.info("Index updated")
    except Exception:
        logger.exception("Index update failed")

    # 5. 追加删除日志
    try:
        config.WIKI_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"## [{ts}] DELETED | {file_path.name}\n\n"
        if not config.WIKI_LOG.exists():
            config.WIKI_LOG.write_text("# 知匣 变更日志\n\n", encoding="utf-8")
        with config.WIKI_LOG.open("a", encoding="utf-8") as f:
            f.write(entry)
        logger.info("Log appended")
    except Exception:
        logger.exception("Log append failed")

    # 6. 从 manifest 和进度中移除
    try:
        with _manifest_lock:
            if key in _manifest:
                del _manifest[key]
                _save_manifest()
                logger.info("Manifest updated")
    except Exception:
        logger.exception("Manifest update failed")

    # 7. 清除 cooldown、seen 和进度记录
    with _last_time_lock:
        _last_enqueue_time.pop(key, None)

    with _seen_lock:
        _seen_set.discard(key)

    _update_progress(key, "deleted")


def _parse_path_from_wiki(wiki_path: Path) -> str:
    """从 wiki 内容中解析原始文件路径。"""
    try:
        for line in wiki_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("- **路径**:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def cleanup_orphans():
    """启动时反向清理：删除物理路径已不存在的文件的向量和 wiki。"""
    logger.info("Scanning for orphaned entries...")
    removed = 0

    # 1. 基于 manifest 反向清理
    with _manifest_lock:
        keys = list(_manifest.keys())
    for key in keys:
        path = Path(key)
        if not path.exists():
            cleanup(path)
            removed += 1

    # 2. 基于向量库反向清理（覆盖 manifest 之外的情况）
    try:
        collection = vector_store.get_collection()
        data = collection.get()
        if data and data.get("ids"):
            for i, doc_id in enumerate(data["ids"]):
                meta = data["metadatas"][i] if data.get("metadatas") else {}
                stored_path = meta.get("path", "")
                if stored_path and not Path(stored_path).exists():
                    cleanup(Path(stored_path))
                    removed += 1
    except Exception:
        logger.exception("Vector scan failed")

    # 3. 基于 wiki 文件反向清理（覆盖 chroma 重建后遗留的孤儿 wiki）
    try:
        if config.WIKI_FILES_DIR.exists():
            for wiki_file in config.WIKI_FILES_DIR.glob("*.md"):
                stored_path = _parse_path_from_wiki(wiki_file)
                if stored_path:
                    if not Path(stored_path).exists():
                        cleanup(Path(stored_path))
                        removed += 1
                else:
                    # 解析不到路径，直接删除孤儿 wiki
                    wiki_file.unlink()
                    removed += 1
                    logger.info("Removed orphaned wiki (no path): %s", wiki_file)
    except Exception:
        logger.exception("Wiki scan failed")

    logger.info("Cleanup complete, removed %d orphaned entries.", removed)


def reindex_all() -> int:
    """强制将所有已有文件加入队列，并重建 BM25 索引。"""
    count = 0
    for d in config.WATCH_DIRS:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix.lower() in config.SUPPORTED_EXTS:
                force_enqueue(f)
                count += 1
    bm25_index.rebuild()
    try:
        query.clear_query_cache()
    except Exception:
        pass
    return count
