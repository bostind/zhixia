import time
import sys
from pathlib import Path
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

import config
import ingest_worker
from config import get_logger

logger = get_logger(__name__)


def _is_junk(path: Path) -> bool:
    """判断是否为垃圾文件。"""
    if path.suffix.lower() in config.JUNK_EXTS:
        return True
    for pattern in config.JUNK_NAME_PATTERNS:
        if path.name.startswith(pattern):
            return True
    return False


def _is_supported_ext(path: Path) -> bool:
    """检查后缀和临时文件名（不检查文件是否存在），用于 delete/move 事件。"""
    if _is_junk(path):
        return False
    return path.suffix.lower() in config.SUPPORTED_EXTS


def is_supported_file(path: Path) -> bool:
    """检查文件是否属于支持的类型，并排除临时文件。"""
    if not path.is_file():
        return False
    if _is_junk(path):
        return False
    return path.suffix.lower() in config.SUPPORTED_EXTS


class FileEventHandler(FileSystemEventHandler):
    """处理文件系统事件，将有效文件推入 ingest 任务队列。"""

    def on_created(self, event: FileSystemEvent):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if is_supported_file(path):
            logger.info("CREATED | %s", path)
            ingest_worker.enqueue(path)

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if is_supported_file(path):
            logger.info("MODIFIED | %s", path)
            ingest_worker.enqueue(path)

    def on_moved(self, event: FileSystemEvent):
        if event.is_directory:
            return
        src = Path(event.src_path)
        dest = Path(event.dest_path)
        # 先清理旧路径的向量和 wiki（文件已移动，旧路径不存在，用 _is_supported_ext）
        if _is_supported_ext(src):
            logger.info("MOVED_CLEANUP | %s -> %s", src, dest)
            ingest_worker.cleanup(src)
        if is_supported_file(dest):
            logger.info("MOVED | %s <- %s", dest, src)
            ingest_worker.enqueue(dest)

    def on_deleted(self, event: FileSystemEvent):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if _is_supported_ext(path):
            logger.info("DELETED | %s", path)
            ingest_worker.cleanup(path)


class WatcherManager:
    """管理文件监控的生命周期，支持动态重启。"""

    def __init__(self):
        self.observer = None
        self.event_handler = FileEventHandler()
        self._running = False

    def start(self):
        self.stop()
        self.observer = Observer()
        valid_dirs = []
        for d in config.WATCH_DIRS:
            if d.exists():
                self.observer.schedule(self.event_handler, str(d), recursive=True)
                valid_dirs.append(d)
                logger.info("Monitoring: %s", d)
            else:
                logger.warning("Skipped (not exists): %s", d)

        if valid_dirs:
            self.observer.start()
            self._running = True
            logger.info("Started.")
        else:
            logger.warning("No valid directories to watch.")

    def stop(self):
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join()
            except Exception:
                logger.exception("Stop error")
            finally:
                self.observer = None
                self._running = False
                logger.info("Stopped.")

    def restart(self):
        logger.info("Restarting...")
        self.start()


# 全局实例，供 main_api.py 调用
watcher_manager = WatcherManager()


def start_watching():
    """启动文件监控（兼容旧入口）。"""
    watcher_manager.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher_manager.stop()


if __name__ == "__main__":
    start_watching()
