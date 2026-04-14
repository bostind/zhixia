"""
Build script: Package Python backend into a standalone executable with PyInstaller.
Output goes to ../python-dist/zhixia-backend/
"""
import sys
import os
import shutil
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
    "chromadb.api.rust",
    "chromadb.api.segment",
    "chromadb.config",
    "chromadb_rust_bindings",
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
    "--windowed",        # 隐藏后端命令行窗口
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

# 强制收集 chromadb 及其 Rust 扩展（避免打包遗漏）
args.extend(["--collect-all", "chromadb"])
args.extend(["--collect-all", "chromadb_rust_bindings"])

print("[build_backend] Running pyinstaller with args:")
print(" ".join(args))

from PyInstaller.__main__ import run
run(args)

print(f"[build_backend] Done. Output at {_DIST_DIR / 'zhixia-backend'}")

# ================================
# Post-build cleanup: remove dev/runtime data & bloated test files
# ================================
backend_dir = _DIST_DIR / "zhixia-backend"
internal_dir = backend_dir / "_internal"

def rm_tree(path: Path):
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        print(f"[cleanup] removed dir: {path}")

def rm_file(path: Path):
    if path.exists():
        path.unlink(missing_ok=True)
        print(f"[cleanup] removed file: {path}")

def rm_glob(root: Path, pattern: str):
    for p in root.rglob(pattern):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)

# 1. 注意：不要清理 _HERE 下的 data/db/wiki/logs，这会破坏开发环境。
#    开发数据应保留在 ZHIXIA_DATA_DIR 指定的目录中。

# 2. 清理 PyInstaller 输出中的测试/示例冗余数据（大幅减小体积）
if internal_dir.exists():
    # sklearn 测试数据
    rm_tree(internal_dir / "sklearn" / "datasets" / "tests")
    rm_tree(internal_dir / "sklearn" / "datasets" / "data")
    rm_tree(internal_dir / "sklearn" / "tests")
    rm_tree(internal_dir / "sklearn" / "cluster" / "tests")
    rm_tree(internal_dir / "sklearn" / "linear_model" / "tests")
    rm_tree(internal_dir / "sklearn" / "metrics" / "tests")
    rm_tree(internal_dir / "sklearn" / "neighbors" / "tests")
    rm_tree(internal_dir / "sklearn" / "tree" / "tests")

    # pyarrow 测试数据
    rm_tree(internal_dir / "pyarrow" / "tests")

    # torch 冗余数据（仅保留推理所需核心模块）
    rm_tree(internal_dir / "torch" / "_export" / "db")
    rm_tree(internal_dir / "torch" / "testing" / "_internal")
    rm_tree(internal_dir / "torch" / "distributed" / "elastic" / "multiprocessing")
    rm_tree(internal_dir / "torch" / "utils" / "data" / "datapipes")
    rm_tree(internal_dir / "torch" / "utils" / "data" / "backward_compatibility")
    rm_tree(internal_dir / "torch" / "testing")
    rm_tree(internal_dir / "torch" / "distributed")
    rm_tree(internal_dir / "torch" / "_inductor")
    rm_tree(internal_dir / "torch" / "bin")
    rm_tree(internal_dir / "torch" / "onnx")
    rm_tree(internal_dir / "torch" / "_export")
    rm_tree(internal_dir / "torch" / "fx")
    rm_tree(internal_dir / "torch" / "_functorch")
    rm_tree(internal_dir / "torch" / "ao")
    rm_tree(internal_dir / "torch" / "profiler")
    rm_tree(internal_dir / "torch" / "package")
    rm_tree(internal_dir / "torch" / "compiler")
    rm_tree(internal_dir / "torch" / "_strobelight")
    rm_tree(internal_dir / "torch" / "monitor")
    rm_tree(internal_dir / "torch" / "contrib")
    rm_tree(internal_dir / "torch" / "nativert")
    rm_tree(internal_dir / "torch" / "func")
    rm_tree(internal_dir / "torch" / "_awaits")
    rm_tree(internal_dir / "torch" / "accelerator")
    rm_tree(internal_dir / "torch" / "mtia")
    rm_tree(internal_dir / "torch" / "xpu")
    rm_tree(internal_dir / "torch" / "mps")
    rm_tree(internal_dir / "torch" / "cpu")
    rm_tree(internal_dir / "torch" / "cuda")
    rm_tree(internal_dir / "torch" / "numa")
    rm_tree(internal_dir / "torch" / "futures")
    rm_tree(internal_dir / "torch" / "signal")
    rm_tree(internal_dir / "torch" / "_vendor")
    rm_tree(internal_dir / "torch" / "_lazy")
    rm_tree(internal_dir / "torch" / "_logging")
    rm_tree(internal_dir / "torch" / "_numpy")
    rm_tree(internal_dir / "torch" / "_decomp")
    rm_tree(internal_dir / "torch" / "_prims")
    rm_tree(internal_dir / "torch" / "_prims_common")
    rm_tree(internal_dir / "torch" / "_subclasses")
    rm_tree(internal_dir / "torch" / "_higher_order_ops")
    rm_tree(internal_dir / "torch" / "_refs")
    rm_tree(internal_dir / "torch" / "_library")
    rm_tree(internal_dir / "torch" / "quantization")
    rm_tree(internal_dir / "torch" / "optim")
    rm_tree(internal_dir / "torch" / "nested")
    rm_tree(internal_dir / "torch" / "distributions")
    rm_tree(internal_dir / "torch" / "masked")
    rm_tree(internal_dir / "torch" / "fft")
    rm_tree(internal_dir / "torch" / "linalg")
    rm_tree(internal_dir / "torch" / "special")
    rm_tree(internal_dir / "torch" / "_dynamo")
    rm_tree(internal_dir / "torch" / "export")
    # 注意：保留 torch/lib, torch/nn, torch/utils, torch/jit, torch/autograd, torch/backends

    # transformers 自带数据集
    rm_tree(internal_dir / "transformers" / "data" / "datasets")
    rm_tree(internal_dir / "transformers" / "data" / "metrics")
    rm_tree(internal_dir / "transformers" / "data" / "processors")

    # pandas / numpy / scipy 测试
    rm_tree(internal_dir / "pandas" / "tests")
    rm_tree(internal_dir / "numpy" / "tests")
    rm_tree(internal_dir / "numpy" / "core" / "tests")
    rm_tree(internal_dir / "numpy" / "f2py" / "tests")
    rm_tree(internal_dir / "numpy" / "linalg" / "tests")
    rm_tree(internal_dir / "numpy" / "ma" / "tests")
    rm_tree(internal_dir / "numpy" / "matrixlib" / "tests")
    rm_tree(internal_dir / "numpy" / "polynomial" / "tests")
    rm_tree(internal_dir / "numpy" / "random" / "tests")
    rm_tree(internal_dir / "scipy" / "tests")
    for sub in ["cluster", "constants", "fft", "integrate", "interpolate", "io", "linalg", "ndimage", "optimize", "signal", "sparse", "spatial", "special", "stats"]:
        rm_tree(internal_dir / "scipy" / sub / "tests")

    # 清理 __pycache__ 和 .pyc
    rm_glob(internal_dir, "__pycache__")
    rm_glob(internal_dir, "*.pyc")
    rm_glob(internal_dir, "*.pyo")
    # 清理编译时文件（运行时不需要）
    rm_glob(internal_dir, "*.lib")
    rm_glob(internal_dir, "*.h")
    rm_glob(internal_dir, "*.hpp")
    rm_glob(internal_dir, "*.cmake")
    rm_glob(internal_dir, "CMakeLists.txt")

print("[cleanup] Post-build cleanup finished.")
