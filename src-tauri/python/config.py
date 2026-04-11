import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# 项目根目录：兼容 PyInstaller 打包后的路径
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = Path(sys._MEIPASS).resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

# 数据目录：支持通过环境变量覆盖（Tauri 会设置）
DATA_DIR = Path(os.getenv("ZHIXIA_DATA_DIR", str(BASE_DIR))).resolve()

def _resolve_dir(candidates):
    for c in candidates:
        p = Path.home() / c
        if p.exists():
            return p
    return None

_DESKTOP = _resolve_dir(["Desktop", "桌面"])
_DOWNLOADS = _resolve_dir(["Downloads", "下载"])
_DOCUMENTS = _resolve_dir(["Documents", "文档"])

_DEFAULT_WATCH_DIRS = [d for d in [_DESKTOP, _DOWNLOADS, _DOCUMENTS] if d is not None]


def _load_watch_dirs():
    config_file = DATA_DIR / "watch_dirs.json"
    if config_file.exists():
        try:
            paths = json.loads(config_file.read_text(encoding="utf-8"))
            dirs = [Path(p) for p in paths if Path(p).exists()]
            if dirs:
                return dirs
        except Exception:
            pass
    return _DEFAULT_WATCH_DIRS


# 监控目录（支持持久化覆盖）
WATCH_DIRS = _load_watch_dirs()


def save_watch_dirs(dirs: list):
    """持久化监控目录到数据目录下的 JSON 文件，并更新内存中的值。"""
    config_file = DATA_DIR / "watch_dirs.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps([str(Path(d).resolve()) for d in dirs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    global WATCH_DIRS
    WATCH_DIRS = [Path(d).resolve() for d in dirs]

# 支持的文件扩展名（小写）
SUPPORTED_EXTS = {".txt", ".md", ".pdf", ".xlsx", ".docx", ".doc", ".pptx", ".ppt", ".csv"}

# 垃圾文件过滤规则
JUNK_EXTS = {".lnk", ".url", ".tmp", ".crdownload", ".part", ".torrent"}
JUNK_NAME_PATTERNS = ["~$", ".", "Screenshot", "屏幕截图", "微信图片", "IMG_"]
MAX_INGEST_SIZE_BYTES = 20 * 1024 * 1024  # 20MB
MAX_EXCEL_ROWS = 500

# 认知层目录
WIKI_DIR = DATA_DIR / "wiki"
WIKI_FILES_DIR = WIKI_DIR / "files"
WIKI_INDEX = WIKI_DIR / "index.md"
WIKI_LOG = WIKI_DIR / "log.md"

# 向量数据库目录
CHROMA_DIR = DATA_DIR / "db" / "chroma"

# 文本提取长度限制（控制 token）
MAX_TEXT_LENGTH = 1800

# Ingest 控制配置
INGEST_COOLDOWN_SECONDS = 1800  # 同一文件触发 ingest 的最小间隔（默认 30 分钟）
INGEST_SCAN_INTERVAL_SECONDS = 1800  # 定时全量扫描间隔（默认 30 分钟）
INGEST_MANIFEST = DATA_DIR / "ingest_manifest.json"  # 内容 hash 去重清单

# 用户 LLM 设置文件（优先级高于 .env）
LLM_SETTINGS_PATH = DATA_DIR / "llm_settings.json"


def _load_llm_settings():
    """加载用户 LLM 设置，返回 dict。"""
    if LLM_SETTINGS_PATH.exists():
        try:
            return json.loads(LLM_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


_llm_settings = _load_llm_settings()

# LLM API 配置（.env 为默认值，用户设置文件优先级更高）
LLM_API_KEY = _llm_settings.get("api_key", os.getenv("LLM_API_KEY", ""))
LLM_BASE_URL = _llm_settings.get("base_url", os.getenv("LLM_BASE_URL", ""))
LLM_MODEL = _llm_settings.get("model", os.getenv("LLM_MODEL", "moonshot-v1-8k"))
LLM_INGEST_MODEL = _llm_settings.get("ingest_model", LLM_MODEL)
LLM_QUERY_MODEL = _llm_settings.get("query_model", LLM_MODEL)

# Query 答案缓存
QUERY_CACHE_PATH = DATA_DIR / "query_cache.json"
QUERY_CACHE_TTL_SECONDS = 86400  # 24 小时


def save_llm_settings(api_key: str, base_url: str, model: str, ingest_model: str = "", query_model: str = ""):
    """持久化用户 LLM 设置并更新内存中的值。"""
    global LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_INGEST_MODEL, LLM_QUERY_MODEL
    LLM_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "ingest_model": ingest_model or model,
        "query_model": query_model or model,
    }
    LLM_SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LLM_API_KEY = api_key
    LLM_BASE_URL = base_url
    LLM_MODEL = model
    LLM_INGEST_MODEL = payload["ingest_model"]
    LLM_QUERY_MODEL = payload["query_model"]


# 本地 Embedding 模型（已下载到项目目录，避免运行时联网）
EMBEDDING_MODEL = str(BASE_DIR / "models" / "bge-small-zh-v1.5")

# ================== 日志配置 ==================
import logging
from logging.handlers import RotatingFileHandler

LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_BACKEND_LOG_PATH = LOGS_DIR / "backend.log"


def setup_logging() -> logging.Logger:
    """配置并返回根 logger，供整个后端使用。"""
    root = logging.getLogger("zhixia")
    if root.handlers:
        return root

    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 Handler：10MB 轮转，保留 3 个备份
    file_handler = RotatingFileHandler(
        str(_BACKEND_LOG_PATH),
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # 控制台 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return root


def get_logger(name: str) -> logging.Logger:
    """获取以 zhixia 为前缀的命名 logger。"""
    return logging.getLogger(f"zhixia.{name}")


# 模块导入时自动初始化
setup_logging()
