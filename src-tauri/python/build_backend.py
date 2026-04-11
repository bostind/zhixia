"""
Build script: Package Python backend into a standalone executable with PyInstaller.
Output goes to ../python-dist/zhixia-backend/
"""
import sys
import os
from pathlib import Path

# Use the project venv python
_HERE = Path(__file__).parent.resolve()
_DIST_DIR = (_HERE / ".." / "python-dist").resolve()

hiddenimports = [
    # FastAPI / web
    "fastapi",
    "fastapi.middleware.cors",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "pydantic",
    "pydantic.deprecated.decorator",
    "pydantic_settings",
    "starlette",
    "starlette.middleware",
    "starlette.routing",
    # ChromaDB
    "chromadb",
    "chromadb.utils",
    "chromadb.utils.embedding_functions",
    "chromadb.telemetry.product.posthog",
    # Transformers / torch
    "transformers",
    "transformers.models.auto",
    "transformers.models.auto.modeling_auto",
    "transformers.models.auto.tokenization_auto",
    "sentence_transformers",
    "torch",
    "torch.nn",
    "torch.jit",
    "safetensors",
    "safetensors.torch",
    "tokenizers",
    "huggingface_hub",
    "huggingface_hub.file_download",
    # Others
    "rank_bm25",
    "pdfplumber",
    "pdfminer",
    "pdfminer.high_level",
    "pypdfium2",
    "openpyxl",
    "docx",
    "docx.api",
    "pptx",
    "pptx.util",
    "pptx.presentation",
    "openai",
    "watchdog",
    "watchdog.observers",
    "watchdog.events",
    "sklearn",
    "sklearn.utils",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors",
    "sklearn.neighbors.typedefs",
    "sklearn.neighbors.quad_tree",
    "sklearn.tree",
    "sklearn.tree._utils",
    "scipy",
    "scipy.sparse",
    "scipy.sparse.csgraph",
    "scipy.special",
    "scipy.special._ufuncs_cxx",
    "numpy",
    "pandas",
    "PIL",
    "PIL._imagingtk",
    "PIL._tkinter_finder",
    "dotenv",
    # Own modules (force inclusion)
    "config",
    "query",
    "vector_store",
    "ingest",
    "watcher",
    "ingest_worker",
    "bm25_index",
    "extractor",
    "llm_client",
    "csv",
]

datas = [
    # Models
    (str(_HERE / "models" / "bge-small-zh-v1.5"), "models/bge-small-zh-v1.5"),
]

# PyInstaller command line args
args = [
    str(_HERE / "main_api.py"),
    "--name", "zhixia-backend",
    "--onedir",
    "--noconfirm",
    "--clean",
    "--distpath", str(_DIST_DIR),
    "--workpath", str(_DIST_DIR / ".." / "build"),
    "--specpath", str(_DIST_DIR / ".." / "build"),
]

for hi in hiddenimports:
    args.extend(["--hidden-import", hi])

for src, dst in datas:
    args.extend(["--add-data", f"{src};{dst}"])

print("[build_backend] Running pyinstaller with args:")
print(" ".join(args))

from PyInstaller.__main__ import run
run(args)

print(f"[build_backend] Done. Output at {_DIST_DIR / 'zhixia-backend'}")
