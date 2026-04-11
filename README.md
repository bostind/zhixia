# 知匣 (Zhixia)

基于 Tauri 2.0 + React + Vite 的桌面端个人文件认知代理。

## 技术栈

- **前端**：React + TypeScript + Vite
- **桌面壳**：Tauri 2.0 (Rust)
- **后端服务**：Python 3.12 + FastAPI (由 Rust 端启动管理生命周期)
- **本地模型**：`bge-small-zh-v1.5` (Sentence Transformer，离线嵌入)
- **混合检索**：ChromaDB 语义检索 + `rank-bm25` 关键词检索，RRF 融合
- **云端大模型**：OpenAI 兼容 API (用于生成 wiki 认知页和回答用户查询)
- **向量存储**：ChromaDB (本地持久化)
- **文件监控**：watchdog (递归监控目录变化)

## 快速启动

```bash
# Windows (自动处理 MSVC 环境、端口清理、启动 dev)
.\start-dev.bat
```

或者直接：

```bash
npm install
npm run tauri dev
```

## LLM (AI 大模型) 调用时机

程序**仅在以下两个时刻**调用云端大模型，其余操作均为本地计算：

### 1. Ingest — 新文件被消化时
- **触发条件**：监控目录中出现新建/修改/移动的 `.txt` / `.md` / `.pdf` / `.xlsx` 文件，或应用启动时/定时扫描/手动触发时对已有文件做处理。
- **调用位置**：`src-tauri/python/ingest.py`
- **LLM 工作**：阅读文件内容，生成结构化的 wiki 认知页（摘要、标签、关键实体、与已有文件的关联推断）。
- **产出**：`wiki/files/{hash}.md` + 向量库更新。
- **耗时**：约 3–15 秒/文件（取决于文件大小和网络）。`ingest_worker` 会保证同一文件在 cooldown 内和 hash 未变时不会重复调用 LLM。

### 2. Query — 用户搜索提问时
- **触发条件**：用户在前端输入自然语言问题并点击"查询"。
- **调用位置**：`src-tauri/python/query.py`
- **前置步骤**：本地 BGE 模型将问题转为向量 → ChromaDB 召回 Top-5 相关文件 → 读取对应的 wiki 页。
- **LLM 工作**：基于召回的 wiki 页内容，生成最终回答（文件路径 + 解释原因）。
- **耗时**：约 2–10 秒/问题。

### 不调用 LLM 的操作

| 操作 | 是否调用 LLM | 说明 |
|------|-------------|------|
| Embedding 向量化 | ❌ 否 | 本地 `bge-small-zh-v1.5` 模型，完全离线 |
| 文本提取 (txt/md/pdf/xlsx) | ❌ 否 | 直接读取文本、使用 `pdfplumber` 解析或使用 `openpyxl` 读取 Excel |
| 向量相似度检索 | ❌ 否 | ChromaDB 本地 HNSW 检索 |
| 状态栏/文件列表刷新 | ❌ 否 | 本地文件计数和 JSON 配置读取 |
| 修改监控目录 | ❌ 否 | 纯本地配置持久化，仅重启 watchdog |

## 项目结构

```
zhixia/
├── src/                  # React 前端源码
│   ├── App.tsx           # 主界面 (Knowledge Nebula UI)
│   └── App.css           # 星云主题样式
├── src-tauri/
│   ├── src/main.rs       # Tauri Rust 入口
│   ├── python/           # Python 后端 (FastAPI + 认知流水线)
│   │   ├── main_api.py   # FastAPI 服务入口
│   │   ├── ingest.py     # 文件消化 / wiki 生成
│   │   ├── query.py      # 用户查询 / LLM 回答生成
│   │   ├── vector_store.py   # ChromaDB 封装
│   │   ├── watcher.py        # 文件监控 (watchdog)
│   │   ├── ingest_worker.py  # ingest 任务队列 + hash 去重 + cooldown + 定时扫描
│   │   ├── extractor.py  # 文本提取 (txt/md/pdf/xlsx)
│   │   ├── llm_client.py # 大模型 API 封装
│   │   └── models/       # 本地 Embedding 模型
│   └── tauri.conf.json   # Tauri 配置
├── start-dev.bat         # Windows 一键开发启动脚本
└── test-restart.ps1      # 测试环境一键重置脚本
```

## ingest 队列与去重机制

为防止编辑器保存导致重复调用 LLM，后端引入了 `ingest_worker.py`：

1. **事件队列**：watchdog 感知到文件变化后，不再直接调用 LLM，而是将文件路径推入线程安全的任务队列。
2. **Worker 串行执行**：一个独立后台线程从队列中逐个消费任务，避免并发和资源竞争。
3. **Cooldown（默认 30 分钟）**：同一个文件在 30 分钟内只会被加入队列一次，防止编辑器疯狂保存时反复触发 LLM。
4. **内容 Hash 去重**：对于 cooldown 窗口外的文件，系统会对比 `mtime + size + MD5 content_hash`。如果文件内容确实没有变化，直接跳过 ingest。
5. **定时全量扫描**：每 30 分钟自动扫描所有监控目录，作为 watchdog 事件的兜底。
6. **删除/重命名自动清理**：文件被删除或重命名时，`cleanup()` 会自动移除旧路径对应的向量、wiki、索引和日志记录。启动时还会执行 `cleanup_orphans()`，清理物理文件已不存在的遗留数据。
7. **手动分析**：界面上的 "🔄 手动分析" 按钮会调用 `POST /reindex`，强制将所有已有文件加入队列，绕过 cooldown 和 hash 检查。

## 测试脚本

```powershell
# 清理数据、重置监控目录为 C:\Users\bob\Downloads\ceshi、重新启动 dev
.\test-restart.ps1
```

## 集成测试

```powershell
# 运行 19 case API 集成测试（要求 dev 环境已启动）
cd tests
python integration_test.py
```

## 关键设计决策

- **BGE 查询前缀**：`vector_store.py` 中自动为查询拼接 `Represent this sentence for searching relevant passages:`，以激活 BGE 模型的最佳检索性能。
- **BM25 + 向量 RRF 融合**：`query.py` 同时发起语义检索和 BM25 关键词检索，使用 Reciprocal Rank Fusion (k=60) 融合结果，显著提升细节形容词和专有名词的召回率。
- **启动扫描**：`main_api.py` 会在后端启动后自动扫描监控目录中的已有文件并触发 ingest，避免仅依赖 watchdog 事件导致旧文件漏索引。
- **递归监控**：`watcher.py` 使用 `recursive=True`，子目录中的文件也会被自动索引。
- **索引兼容性**：切换 Embedding 模型后，必须删除旧 `chroma` 数据库重建索引，否则向量空间不匹配会导致召回结果完全错乱。
- **Ingest Worker 队列**：`ingest_worker.py` 将 watchdog 事件异步化、串行化，配合 cooldown 和内容 hash 去重，避免编辑器保存导致 LLM 重复调用。
- **手动分析兜底**：`POST /reindex` 提供全局强制重索引能力，用户可随时触发全量分析。
- **删除/重命名清理**：文件移动或删除时自动清理向量、wiki、BM25 索引和 manifest。
- **错误降级**：LLM API 超时或断开时，`query.py` 自动降级为直接返回 Top-3 向量召回结果，保证基本可用性。
- **垃圾文件过滤**：自动忽略 `.lnk`、`.url`、截图、临时文件等桌面常见干扰项。
- **删除/重命名清理**：`ingest_worker.cleanup()` 在文件被删除或重命名时，自动清理对应的 ChromaDB 向量、wiki 页、index 和 manifest 记录；启动时还会执行 `cleanup_orphans()` 反向扫描，清理历史遗留的幽灵数据。
