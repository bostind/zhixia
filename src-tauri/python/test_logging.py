"""测试日志系统的基础功能。"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# 将当前目录加入路径
sys.path.insert(0, str(Path(__file__).parent))

# 隔离测试数据目录，避免污染真实环境
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="zhixia_test_"))
os.environ["ZHIXIA_DATA_DIR"] = str(_TEST_DATA_DIR)

# 重新加载 config 模块以获得隔离的配置
if "config" in sys.modules:
    del sys.modules["config"]
if "ingest_worker" in sys.modules:
    del sys.modules["ingest_worker"]

import config
from config import get_logger, setup_logging


def test_log_dir_created():
    """日志目录应在 setup_logging() 后自动创建。"""
    assert config.LOGS_DIR.exists()
    assert config.LOGS_DIR.name == "logs"


def test_logger_writes_to_file():
    """logger 写入的内容应出现在 backend.log 中。"""
    log_path = config.LOGS_DIR / "backend.log"
    if log_path.exists():
        try:
            log_path.unlink()
        except PermissionError:
            # Windows 下 RotatingFileHandler 可能持有句柄，直接清空内容
            log_path.write_text("", encoding="utf-8")

    logger = get_logger("test_module")
    test_msg = "This is a test log message from test_logger_writes_to_file"
    logger.info(test_msg)

    # 等待文件写入（RotatingFileHandler 是同步的，通常立即写入）
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert test_msg in content
    assert "[INFO]" in content
    assert "[zhixia.test_module]" in content


def test_log_level_filtering():
    """DEBUG 级别应写入文件，但可能不在 console（测试中我们只检查文件）。"""
    log_path = config.LOGS_DIR / "backend.log"
    marker = f"DEBUG_MARKER_{threading.current_thread().ident}"
    logger = get_logger("debug_test")
    logger.debug(marker)

    content = log_path.read_text(encoding="utf-8")
    assert marker in content


def test_rotating_file_handler():
    """验证 RotatingFileHandler 会按大小轮转日志文件。"""
    # 为了快速触发轮转，临时创建一个独立的小日志配置
    import logging
    from logging.handlers import RotatingFileHandler

    rotate_dir = _TEST_DATA_DIR / "rotate_test"
    rotate_dir.mkdir(parents=True, exist_ok=True)
    rotate_log = rotate_dir / "rotate.log"

    test_logger = logging.getLogger("zhixia.rotate_test")
    test_logger.handlers.clear()
    test_logger.setLevel(logging.DEBUG)

    handler = RotatingFileHandler(
        str(rotate_log),
        maxBytes=128,
        backupCount=10,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(message)s")
    )
    test_logger.addHandler(handler)

    # 写入足够长的日志以触发轮转
    for i in range(20):
        test_logger.info(f"LINE_{i}_" + "X" * 50)

    handler.close()
    test_logger.handlers.clear()

    # 验证产生了备份文件
    backups = list(rotate_dir.glob("rotate.log.*"))
    assert len(backups) >= 1, f"Expected at least 1 backup, found {backups}"
    assert rotate_log.exists()

    # 验证内容分散在原始文件和备份中
    all_content = rotate_log.read_text(encoding="utf-8")
    for b in backups:
        all_content += b.read_text(encoding="utf-8")
    # 首尾行都应能在合并后的内容里找到
    assert "LINE_0_" in all_content
    assert "LINE_19_" in all_content


def test_ingest_worker_uses_logger():
    """验证 ingest_worker 模块能正确获取 logger 且不再直接 print。"""
    source = (Path(__file__).parent / "ingest_worker.py").read_text(encoding="utf-8")
    # 允许 test 函数或 __main__ 中的 print，但业务代码中不应再有旧标签
    assert "print(f\"[WORKER]" not in source
    assert "print(f\"[CLEANUP]" not in source
    assert "print(f\"[ORPHAN]" not in source
    assert "print(f\"[SCAN]" not in source
    assert "get_logger" in source
    assert "logger.info" in source or "logger.error" in source or "logger.exception" in source


def test_main_api_uvicorn_log_config():
    """验证 main_api.py 中 uvicorn.run 传入了 log_config=None。"""
    source = (Path(__file__).parent / "main_api.py").read_text(encoding="utf-8")
    assert "log_config=None" in source


if __name__ == "__main__":
    test_log_dir_created()
    print("PASS: test_log_dir_created")

    test_logger_writes_to_file()
    print("PASS: test_logger_writes_to_file")

    test_log_level_filtering()
    print("PASS: test_log_level_filtering")

    test_rotating_file_handler()
    print("PASS: test_rotating_file_handler")

    test_ingest_worker_uses_logger()
    print("PASS: test_ingest_worker_uses_logger")

    test_main_api_uvicorn_log_config()
    print("PASS: test_main_api_uvicorn_log_config")

    print("\nAll logging tests passed!")
