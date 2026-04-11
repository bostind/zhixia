"""
知匣 Tauri App 集成测试
在 dev 环境运行（Python 后端已启动在 127.0.0.1:8765）
"""
import json
import sys
import time
from pathlib import Path

import requests

API_BASE = "http://127.0.0.1:8765"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

TEST_QUERIES = [
    # TC-01 预算
    ("Q01", "TC-01", "张总负责的预算文件在哪"),
    ("Q02", "TC-01", "4.5万的采购计划"),
    ("Q03", "TC-01", "市场部第三季度预算"),
    # TC-02 会议纪要
    ("Q04", "TC-02", "3月28日会议记录"),
    ("Q05", "TC-02", "客户对报价的反馈"),
    ("Q06", "TC-02", "张总参加的会议"),
    # TC-03 设计稿
    ("Q07", "TC-03", "首页改版的设计稿"),
    ("Q08", "TC-03", "Alice和Bob做的项目"),
    ("Q09", "TC-03", "深蓝色主色调的文档"),
    # TC-04 合同
    ("Q10", "TC-04", "Alpha项目的合同"),
    ("Q11", "TC-04", "4.5万的合作协议"),
    ("Q12", "TC-04", "客户A公司的合同草案"),
    # TC-05 旅行
    ("Q13", "TC-05", "五一日本旅行计划"),
    ("Q14", "TC-05", "大阪京都自由行"),
    # CROSS 跨文件
    ("Q15", "CROSS", "和张总相关的所有文件"),
    ("Q16", "CROSS", "4.5万元相关的文档有哪些"),
    ("Q17", "CROSS", "市场部的工作文档"),
    ("Q18", "CROSS", "和预算报价有关的合同或会议记录"),
    ("Q19", "CROSS", "找设计相关的文件"),
]

EXPECTED_KEYWORDS = {
    "TC-01": ["2024_Q3_Budget", "预算"],
    "TC-02": ["Meeting_0328_Client", "会议"],
    "TC-03": ["Homepage_Redesign_V3", "设计"],
    "TC-04": ["Contract_Draft_Alpha", "合同"],
    "TC-05": ["Personal_Travel_Plan", "旅行"],
    "CROSS": None,
}


def health_check():
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        return r.status_code == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        return False


def ingest_fixture(path: Path):
    """通过 /ingest endpoint 手动索引单个文件。"""
    r = requests.post(f"{API_BASE}/ingest", params={"path": str(path)}, timeout=60)
    data = r.json()
    if not data.get("success"):
        print(f"  [WARN] Ingest failed for {path.name}: {data.get('error')}")
    else:
        print(f"  [OK] Ingested {path.name}")
    return data.get("success", False)


def run_query(q: str):
    r = requests.post(
        f"{API_BASE}/query",
        json={"question": q, "n_results": 5},
        timeout=60,
    )
    return r.json().get("answer", "")


def check_hit(tc_id, answer):
    if tc_id == "CROSS":
        return "未找到" not in answer and "暂无" not in answer
    keywords = EXPECTED_KEYWORDS[tc_id]
    return any(kw in answer for kw in keywords)


def main():
    print("=" * 70)
    print("知匣 (Zhixia) Integration Test")
    print("=" * 70)

    if not health_check():
        print("Python backend is not ready. Please start the dev server first.")
        sys.exit(1)

    # 1. 先清理并重新索引测试文件（放到 fixtures 目录即可，/ingest 接受任意路径）
    print("\n[1/3] Ingesting test fixtures...")
    txt_files = sorted(FIXTURES_DIR.glob("*.txt"))
    if not txt_files:
        print("No test fixtures found!")
        sys.exit(1)
    for f in txt_files:
        ingest_fixture(f)
        time.sleep(1)

    # 重建 BM25 索引
    print("\n[2/3] Rebuilding BM25 index...")
    r = requests.post(f"{API_BASE}/bm25_rebuild", timeout=10)
    print(f"  {r.json()}")

    # 2. 运行 19 个查询
    print("\n[3/3] Running queries...")
    results = []
    for qid, tc_id, qtext in TEST_QUERIES:
        print(f"\n[{qid}] {qtext}")
        try:
            answer = run_query(qtext)
        except Exception as e:
            answer = f"ERROR: {e}"
        print(answer[:300] + ("..." if len(answer) > 300 else ""))
        hit = check_hit(tc_id, answer)
        results.append({"qid": qid, "tc": tc_id, "query": qtext, "hit": hit, "answer": answer})

    # 3. 输出报告
    print("\n" + "=" * 70)
    print("Test Report")
    print("=" * 70)

    total = len(results)
    hits = sum(1 for r in results if r["hit"])
    print(f"\nTotal queries: {total}")
    print(f"Hits: {hits}")
    print(f"Hit rate: {hits / total * 100:.1f}%")

    print("\nBy test case:")
    for tc in ["TC-01", "TC-02", "TC-03", "TC-04", "TC-05", "CROSS"]:
        tc_results = [r for r in results if r["tc"] == tc]
        tc_hits = sum(1 for r in tc_results if r["hit"])
        print(f"  {tc}: {tc_hits}/{len(tc_results)} hit")

    print("\nMissed queries:")
    for r in results:
        if not r["hit"]:
            print(f"  [{r['qid']}] {r['query']}")

    # 写入 JSON 报告
    report_path = Path(__file__).parent / "integration_report.json"
    report_path.write_text(json.dumps({"total": total, "hits": hits, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetailed report written to: {report_path}")

    if hits / total < 0.7:
        print("\n[FAIL] Hit rate below 70%")
        sys.exit(1)
    else:
        print("\n[PASS] Hit rate acceptable")


if __name__ == "__main__":
    main()
