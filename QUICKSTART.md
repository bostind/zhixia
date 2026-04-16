# 知匣 (Zhixia) 初始使用安装指引

> 面向第一次使用知匣的用户，从环境准备到成功搜索的完整步骤。

---

## 一、环境准备

在 Windows 电脑上，你需要提前安装以下环境：

| 组件 | 最低版本 | 下载/说明 |
|------|---------|----------|
| **Node.js** | 18.x | https://nodejs.org/ (LTS 版) |
| **Python** | 3.12 | https://www.python.org/downloads/release/python-3128/ |
| **Rust** | 最新 stable | https://rustup.rs/ |
| **MSVC BuildTools 2022** | — | Visual Studio Installer → "使用 C++ 的桌面开发" 工作负载 |
| **Git** | — | 用于克隆项目 |

**验证命令**（在 PowerShell 或 CMD 中执行）：
```powershell
node -v        # 应输出 v18.x 或更高
npm -v         # 应输出 9.x 或更高
python --version   # 应输出 Python 3.12.x
cargo --version    # 应输出 cargo 1.x
```

---

## 二、安装项目依赖

### 1. 前端依赖
进入项目根目录，执行：
```bash
cd zhixia
npm install
```

### 2. 后端 Python 环境
项目使用独立的虚拟环境 `filemind_mvp\venv`，已经包含所有依赖。如果你需要全新安装：
```powershell
cd filemind_mvp
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

---

## 三、配置 LLM（最关键的一步）

知匣需要调用云端大模型来**阅读文件并生成标签/摘要**，以及**回答你的搜索问题**。当前默认对接的是 **火山方舟 (Volces Ark)**。

### 步骤：
1. 登录 [火山方舟控制台](https://console.volcengine.com/ark/)
2. 开通模型服务，获取 **API Key**
3. 在"在线推理"页面创建一个推理接入点，复制 **Endpoint ID**（格式如 `ep-2025xxxxxxxxx`）
4. 首次启动应用后，点击左侧边栏的 **⚙️ 设置**
5. 填入以下信息：
   - **API Key**: `sk-xxxxxxxxxxxxx`
   - **Base URL**: `https://ark.cn-beijing.volces.com/api/v3`
   - **Model / Ingest Model / Query Model**: 都填写你的 **Endpoint ID**（不是模型名称，是 `ep-` 开头的那串 ID）

> ⚠️ **常见错误**：如果填的是模型名称（如 `doubao-1-5-pro-32k-250115`）而不是 Endpoint ID，会导致文件分析时一直超时或报 401。

---

## 四、启动应用

### 开发模式（推荐日常调试）
直接双击运行项目根目录下的：
```
start-dev.bat
```

它会自动完成：
- 清理占用端口 1420 / 8765 的僵尸进程
- 初始化 MSVC 编译环境
- 启动 Python 后端服务
- 启动 Vite + Tauri 桌面窗口

窗口弹出后，稍等几秒（后台在预热向量模型），即可开始使用。

### 生产打包（构建安装包）
如果你要生成 `.msi` 安装包：
```bash
# 第一步：重新打包 Python 后端（耗时约 20-40 分钟）
cd src-tauri\python
e:\Users\bob\Documents\BobBase\aizsk\filemind_mvp\venv\Scripts\python.exe build_backend.py

# 第二步：构建前端 + Tauri 安装包
cd ..
cd ..
npm run tauri build
```
打包产物位于 `src-tauri/target/release/bundle/msi/`。

---

## 五、首次使用流程

### 1. 监控目录
默认会自动监控以下目录中的文件：
- 桌面 (`Desktop`)
- 下载 (`Downloads`)
- 文档 (`Documents`)

你可以在**设置页**修改监控目录。将支持的文件放入这些目录后，知匣会自动识别并分析。

### 2. 支持的文件格式
- `.txt` / `.md` — 直接读取
- `.pdf` — 提取全部页面文字
- `.xlsx` / `.csv` — 提取表格内容
- `.docx` — 提取 Word 段落
- `.pptx` — 提取每页 Slide 文字
- `.doc` / `.ppt` — 需要电脑安装 Microsoft Office 才能读取

### 3. 文件自动分析
文件放入监控目录后：
- 后端 `ingest_worker` 会自动将文件加入队列
- 调用 LLM 生成**标签**、**摘要**和**关键实体**
- 分析完成后，文件会出现在 **索引库** 中
- 同一文件 30 分钟内不会重复分析（防止编辑器频繁保存导致浪费 Token）

> 如果已有大量历史文件，可以点击搜索框下方的 **"🔄 手动分析"** 按钮，强制全部分析一次。

### 4. 查看索引库
点击左侧边栏的 **🗂️ 索引库**：
- 上方显示统计卡片（已索引文件数、标签数、类型分布）
- 中间是**标签云**，点击任意标签可筛选相关文件
- 标签已做智能聚类（如 "HTML优化" 和 "HTML页面开发" 会合并展示）
- 标签云只展示出现次数最多的 **Top 20**

### 5. 搜索查询
在搜索框输入自然语言问题，例如：
- `"张总负责的预算方案"`
- `"HTML 前端优化相关的文档"`
- `"MES 系统的部署计划"`

知匣会：
1. 用本地 BGE 模型将你的问题转成向量
2. 在 ChromaDB 中召回语义最相关的文件
3. 同时用 BM25 做关键词补充召回
4. 融合结果后交给 LLM 生成回答（包含文件路径 + 解释原因）

---

## 六、常见问题

### Q1: 启动时窗口闪退怎么办？
- 检查端口 8765 是否被其他程序占用
- 确认 `ZHIXIA_PYTHON_DIR` 指向了正确的 `src-tauri/python` 路径
- 查看日志：`C:\Users\bob\AppData\Local\app.zhixia.ai\data\logs\backend.log`

### Q2: 文件分析一直卡住或超时？
- 99% 是因为 LLM 配置错误，请检查设置里的 Model 是否填的是 **Endpoint ID**（`ep-` 开头）
- 检查 API Key 是否有效、是否还有余额

### Q3: 为什么有些标签很长，像一句话？
- 这是 LLM 偶尔用中文逗号 `，` 或顿号 `、` 分隔标签导致的。目前已通过前后端规范化处理修复：新分析的文件会自动转成英文逗号；前端也会兼容展示旧数据。

### Q4: PPT 文件能分析吗？
- `.pptx`：完全支持，无需安装 Office
- `.ppt`：需要电脑上安装 PowerPoint 才能读取，建议另存为 `.pptx`

### Q5: 搜索结果是空的？
- 确认文件已被索引（索引库中有显示）
- 确认 LLM 配置正确（否则 ingest 阶段无法生成标签和摘要）
- 尝试用更简单的关键词搜索，或降低问题具体程度

---

## 七、项目数据位置

所有本地数据（向量库、wiki、配置、日志）都保存在：
```
C:\Users\bob\AppData\Local\app.zhixia.ai\data\
```

子目录说明：
- `db/chroma/` — 向量数据库
- `wiki/files/` — AI 生成的文件认知页
- `wiki/index.md` — 全局文件索引
- `llm_settings.json` — 你的 LLM 配置（含 API Key）
- `logs/backend.log` — 后端运行日志

如需彻底重置，直接删除上述 `data` 文件夹，重启应用后会自动重建。
