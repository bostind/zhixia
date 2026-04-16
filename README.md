# 知匣 (Zhixia)

基于 Tauri 2.0 + React + Vite + Python 的桌面端个人文件认知代理。自动监控本地文件变化，提取内容并构建认知层（标签、摘要、关联），支持自然语言语义搜索。

## 技术栈

- **前端**：React + TypeScript + Vite
- **桌面壳**：Tauri 2.0 (Rust)
- **后端服务**：Python 3.12 + FastAPI（由 Rust 端启动管理生命周期）
- **本地模型**：`bge-small-zh-v1.5`（Sentence Transformer，离线嵌入）
- **混合检索**：ChromaDB 语义检索 + `rank-bm25` 关键词检索，RRF 融合
- **云端大模型**：OpenAI 兼容 API（用于生成 wiki 认知页和回答用户查询）
- **向量存储**：ChromaDB（本地持久化）
- **文件监控**：watchdog（递归监控目录变化）

## 支持格式

`.txt`、`.md`、`.pdf`、`.xlsx`、`.csv`、`.docx`、`.doc`、`.pptx`、`.ppt`

> `.doc` 和 `.ppt` 需要本地安装 Microsoft Office。

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
- **触发条件**：监控目录中出现新建/修改/移动的文件，或应用启动时/定时扫描/手动触发。
- **调用位置**：`src-tauri/python/ingest.py`
- **LLM 工作**：阅读文件内容前 1500 字符，生成结构化的 wiki 认知页（摘要、标签、关键实体、与已有文件的关联推断）。
- **产出**：`wiki/files/{hash}.md` + 向量库更新。
- **耗时**：约 3–15 秒/文件（取决于网络）。`ingest_worker` 保证同一文件在 cooldown 内和 hash 未变时不会重复调用 LLM。
- **失败防护**：若文本提取失败（如缺少依赖库），直接标记为 `标签: 解析失败`，不再调用 LLM 生成垃圾标签。

### 2. Query — 用户搜索提问时
- **触发条件**：用户在前端输入自然语言问题并点击"查询"。
- **调用位置**：`src-tauri/python/query.py`
- **前置步骤**：本地 BGE 模型将问题转为向量 → ChromaDB 召回 Top-10 相关文件 → BM25 关键词召回 Top-10 → RRF 融合取 Top-5 → 读取对应 wiki 页。
- **LLM 工作**：基于召回的 wiki 页内容，生成最终回答（文件路径 + 解释原因）。
- **耗时**：约 2–10 秒/问题。
- **降级**：LLM 超时或不可用时，自动返回 Top-3 文件路径列表，保证基本可用性。

### 不调用 LLM 的操作

| 操作 | 是否调用 LLM | 说明 |
|------|-------------|------|
| Embedding 向量化 | ❌ 否 | 本地 `bge-small-zh-v1.5` 模型，完全离线 |
| 文本提取 | ❌ 否 | `pdfplumber` / `python-docx` / `python-pptx` / `openpyxl` 等 |
| 向量相似度检索 | ❌ 否 | ChromaDB 本地 HNSW 检索 |
| 状态栏/文件列表刷新 | ❌ 否 | 本地文件计数和 JSON 配置读取 |
| 修改监控目录 | ❌ 否 | 纯本地配置持久化，仅重启 watchdog |

## 项目结构

```
zhixia/
├── src/                  # React 前端源码
│   ├── App.tsx           # 主界面 (Knowledge Nebula UI)
│   ├── App.css           # 星云主题样式
│   └── SettingsPanel.tsx # 设置面板
├── src-tauri/
│   ├── src/lib.rs        # Tauri Rust 入口（Python 进程管理）
│   ├── python/           # Python 后端 (FastAPI + 认知流水线)
│   │   ├── main_api.py   # FastAPI 服务入口
│   │   ├── ingest.py     # 文件消化 / wiki 生成
│   │   ├── query.py      # 用户查询 / LLM 回答生成
│   │   ├── vector_store.py   # ChromaDB 封装（含 client/embedding 缓存）
│   │   ├── bm25_index.py     # BM25 索引
│   │   ├── watcher.py        # 文件监控 (watchdog)
│   │   ├── ingest_worker.py  # ingest 任务队列 + hash 去重 + cooldown + 定时扫描
│   │   ├── extractor.py      # 文本提取 (txt/md/pdf/xlsx/pptx/docx)
│   │   ├── llm_client.py     # 大模型 API 封装
│   │   ├── build_backend.py  # PyInstaller 打包脚本
│   │   └── models/           # 本地 Embedding 模型
│   └── tauri.conf.json   # Tauri 配置
├── start-dev.bat         # Windows 一键开发启动脚本
└── test-restart.ps1      # 测试环境一键重置脚本
```

## 核心特性

### 标签智能聚类
Library 视图中的标签云会自动对语义相近的标签进行聚类：
- **包含关系**：`HTML页面开发` 自动包含 `HTML优化`
- **领域共享**：共享 `HTML`/`前端`/`MES` 等关键词的标签会归为同一类
- **字符相似度**：双字元 Jaccard 相似度捕获字面相近的标签（如 `页面优化` 和 `页面调整`）
- **别名归一化**：`CATL` 自动显示为 `宁德时代`，`H5` 自动显示为 `HTML`
- **Top 20 限制**：词云仅展示出现次数最多的前 20 个聚类标签，避免信息过载

### 中文标点兼容
标签支持 `,` `，` `、` 三种分隔符，后端保存时会自动统一为英文逗号。即使 LLM 输出中文逗号分隔的长串，也会被正确拆分统计。

### 搜索排除文件夹
LLM 回答中的文件夹路径（无扩展名）不会再被误识别为搜索结果卡片，只保留带扩展名的文件路径。

### 监控目录切换自动清理
修改监控目录后，后台会自动执行 `cleanup_orphans()`，删除旧目录遗留的向量、wiki 和索引，防止"幽灵文件"和过期标签残留。

### 后端启动预热
FastAPI 启动时会后台预加载 `bge-small-zh-v1.5` embedding 模型，避免前端首次请求时卡顿（从 ~19 秒降至毫秒级）。

## ingest 队列与去重机制

`ingest_worker.py` 负责管理文件分析队列：

1. **事件队列**：watchdog 感知变化后将文件路径推入线程安全队列。
2. **Worker 串行执行**：独立后台线程逐个消费任务。
3. **Cooldown（默认 30 分钟）**：同一文件 30 分钟内只入队一次。
4. **内容 Hash 去重**：对比 `mtime + size + MD5 content_hash`，内容未变则跳过。
5. **定时全量扫描**：每 30 分钟自动扫描监控目录兜底。
6. **删除/重命名自动清理**：文件被删除时自动清理对应向量、wiki、索引。
7. **手动分析**：界面上的 "🔄 手动分析" 按钮可强制全量重索引。

## 测试脚本

```powershell
# 清理数据、重置监控目录为 C:\Users\bob\Downloads\ceshi、重新启动 dev
.\test-restart.ps1
```

## 集成测试

```powershell
# 运行 API 集成测试（要求 dev 环境已启动）
cd tests
python integration_test.py
```

## 关键设计决策

- **BGE 查询前缀**：`vector_store.py` 中自动为查询拼接 `Represent this sentence for searching relevant passages:`，激活 BGE 最佳检索性能。
- **BM25 + 向量 RRF 融合**：`query.py` 同时发起语义检索和 BM25 关键词检索，使用 Reciprocal Rank Fusion (k=60) 融合结果。
- **启动扫描**：后端启动后自动扫描已有文件并触发 ingest。
- **递归监控**：`watcher.py` 使用 `recursive=True`，子目录文件也会被索引。
- **索引兼容性**：切换 Embedding 模型后必须删除旧 `chroma` 数据库重建索引。
- **向量库缓存**：`vector_store.py` 对 `PersistentClient`、`EmbeddingFunction`、`Collection` 做了全局单例缓存，避免重复加载模型。
- **错误降级**：LLM API 超时或断开时，`query.py` 自动降级为直接返回 Top-3 向量召回结果。
- **垃圾文件过滤**：自动忽略 `.lnk`、`.url`、截图、临时文件等常见干扰项。
- **启动预热**：后台线程在 uvicorn 启动时即预热 ChromaDB 和 embedding 模型，提升首次 API 响应速度。
