import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Dict

import config
from config import get_logger
import extractor
import vector_store
import llm_client

logger = get_logger(__name__)


def _file_hash(file_path: Path) -> str:
    """基于文件绝对路径生成稳定 ID。"""
    return hashlib.md5(str(file_path.resolve()).encode("utf-8")).hexdigest()[:16]


def _get_similar_files(text: str, n: int = 3) -> List[Dict]:
    """查询向量库，获取最相似的已有文件。"""
    if not text.strip():
        return []
    try:
        results = vector_store.query_documents(text, n_results=n)
        return results
    except Exception:
        return []


def _build_ingest_prompt(filename: str, text: str, similar_files: List[Dict]) -> str:
    similar_section = ""
    if similar_files:
        similar_section = "\n## 已有相似文件\n"
        for i, sf in enumerate(similar_files, 1):
            similar_section += f"\n### {i}. {sf['metadata']['filename']}\n"
            similar_section += f"摘要片段：{sf['document'][:200]}...\n"

    prompt = f"""你是一个个人文件管理 AI。请阅读下面的新文件，并生成一个结构化的 markdown 页面。

## 新文件信息
- 文件名：{filename}
- 内容：
{text[:1500]}
{similar_section}

请严格按照以下格式输出（只输出 markdown，不要任何额外解释）：

```markdown
# 文件：{{文件名}}

- **路径**: {{绝对路径}}
- **修改时间**: {{YYYY-MM-DD HH:MM}}
- **标签**: {{3-5个标签，逗号分隔}}
- **摘要**: {{一句话概括核心内容}}

## 关键实体
- {{实体1}}
- {{实体2}}

## 关联文件
- [[{{相似文件A的filename}}|{{相似文件A的filename}}]]: {{关联理由}}
- [[{{相似文件B的filename}}|{{相似文件B的filename}}]]: {{关联理由}}
```

关联规则：
1. 只有内容确实相关时才建立关联；不相关则写"暂无"
2. 关联理由要具体，说明两个文件在内容上的联系
3. 如果已有相似文件列表为空，则关联文件写"暂无"
"""
    return prompt


def _parse_wiki_content(raw_md: str) -> str:
    """清理 LLM 输出的 markdown 代码块。"""
    raw = raw_md.strip()
    if raw.startswith("```markdown"):
        raw = raw[len("```markdown"):]
    elif raw.startswith("```"):
        raw = raw[len("```"):]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


def _update_index(file_path: Path, summary: str, tags: str):
    """更新 wiki/index.md。"""
    config.WIKI_FILES_DIR.mkdir(parents=True, exist_ok=True)
    config.WIKI_INDEX.parent.mkdir(parents=True, exist_ok=True)

    file_hash = _file_hash(file_path)
    wiki_filename = f"{file_hash}.md"
    relative_link = f"files/{wiki_filename}"

    line = f"- [[{relative_link}|{file_path.name}]] — {summary} `#{tags.replace(',', ' #').strip()}`\n"

    if not config.WIKI_INDEX.exists():
        config.WIKI_INDEX.write_text("# 知匣 认知层索引\n\n", encoding="utf-8")

    existing = config.WIKI_INDEX.read_text(encoding="utf-8").splitlines()
    new_lines = []
    found = False
    for l in existing:
        if l.strip().startswith(f"- [[{relative_link}"):
            new_lines.append(line.rstrip())
            found = True
        else:
            new_lines.append(l)
    if not found:
        new_lines.append(line.rstrip())

    config.WIKI_INDEX.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _append_log(action: str, file_path: Path, detail: str = ""):
    """追加到 wiki/log.md。"""
    config.WIKI_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"## [{ts}] {action} | {file_path.name}"
    if detail:
        entry += f" — {detail}"
    entry += "\n\n"

    if not config.WIKI_LOG.exists():
        config.WIKI_LOG.write_text("# 知匣 变更日志\n\n", encoding="utf-8")

    with config.WIKI_LOG.open("a", encoding="utf-8") as f:
        f.write(entry)


def process_file(file_path: Path) -> str:
    """处理单个文件：提取 → 向量化 → LLM 生成 wiki → 更新索引和日志。"""
    logger.info("Processing: %s", file_path)

    # 1. 提取文本
    text = extractor.extract_text(file_path)
    if not text.strip():
        logger.info("Skipped (empty content): %s", file_path)
        return ""

    # 2. 查找相似文件
    similar_files = _get_similar_files(text)

    # 3. 调用 LLM 生成 wiki 内容
    prompt = _build_ingest_prompt(file_path.name, text, similar_files)
    raw_md = llm_client.chat_completion(
        system_prompt="你是一个严谨的个人知识管理助手，擅长从文件中提取关键信息并建立关联。",
        user_prompt=prompt,
        temperature=0.3,
        model=config.LLM_INGEST_MODEL,
    )
    wiki_content = _parse_wiki_content(raw_md)

    # 修正路径和文件名占位符（LLM 可能不会完全按要求填）
    file_hash = _file_hash(file_path)
    wiki_path = config.WIKI_FILES_DIR / f"{file_hash}.md"

    # 确保路径和修改时间正确
    mtime_str = datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    lines = wiki_content.splitlines()
    new_lines = []
    for line in lines:
        if line.strip().startswith("- **路径**:"):
            line = f"- **路径**: {file_path.resolve()}"
        elif line.strip().startswith("- **修改时间**:"):
            line = f"- **修改时间**: {mtime_str}"
        new_lines.append(line)
    wiki_content = "\n".join(new_lines)

    # 4. 写入 wiki 页
    wiki_path.write_text(wiki_content, encoding="utf-8")
    logger.info("Wiki saved: %s", wiki_path)

    # 5. 提取摘要和标签用于索引（从生成的内容里简单解析）
    summary = "暂无摘要"
    tags = "未分类"
    for line in wiki_content.splitlines():
        if line.startswith("- **摘要**:"):
            summary = line.split(":", 1)[1].strip()
        if line.startswith("- **标签**:"):
            tags = line.split(":", 1)[1].strip()

    # 6. 更新向量库（先删后加，避免重复）
    doc_id = file_hash
    try:
        vector_store.delete_document(doc_id)
    except Exception:
        pass
    vector_store.add_document(
        doc_id=doc_id,
        text=text,
        metadata={
            "filename": file_path.name,
            "path": str(file_path.resolve()),
            "wiki_path": str(wiki_path),
            "summary": summary,
            "tags": tags,
        },
    )
    logger.info("Vector added: %s", doc_id)

    # 7. 更新索引和日志
    _update_index(file_path, summary, tags)
    _append_log("INGEST", file_path, f"summary={summary[:40]}...")

    return str(wiki_path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ingest.py <file_path>")
        sys.exit(1)
    target = Path(sys.argv[1])
    if not target.exists():
        print(f"File not found: {target}")
        sys.exit(1)
    process_file(target)
