"""Tests for zhixia text extractor with new document formats."""

import sys
import os
import tempfile
from pathlib import Path

# Make python backend importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src-tauri" / "python"))

# Use a temporary data dir so we don't pollute the real workspace
os.environ["ZHIXIA_DATA_DIR"] = tempfile.mkdtemp(prefix="zhixia_test_")

import extractor
import config

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_docx_extraction():
    path = FIXTURES_DIR / "Test_DOCX.docx"
    assert path.exists()
    text = extractor.extract_text(path)
    assert "知匣测试文档" in text
    assert "知匣、文档管理、AI 认知层" in text
    assert "张总" in text
    assert "4.5万元" in text


def test_pptx_extraction():
    path = FIXTURES_DIR / "Test_PPTX.pptx"
    assert path.exists()
    text = extractor.extract_text(path)
    assert "知匣测试 PPT" in text
    assert "语义搜索、本地 AI" in text
    assert "市场部第三季度预算为 4.5 万元" in text


def test_csv_extraction():
    path = FIXTURES_DIR / "Test_CSV.csv"
    assert path.exists()
    text = extractor.extract_text(path)
    assert "项目" in text
    assert "负责人" in text
    assert "知匣认知层" in text
    assert "45000" in text
    assert "Alice" in text


def test_supported_exts_includes_new_formats():
    expected = {".txt", ".md", ".pdf", ".xlsx", ".docx", ".doc", ".pptx", ".ppt", ".csv"}
    assert config.SUPPORTED_EXTS == expected


def test_doc_fallback_on_non_windows():
    """.doc / .ppt fallback should return friendly message if COM not available."""
    # Create a dummy .doc file (content doesn't matter, COM will fail on non-Windows)
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as f:
        f.write(b"not a real doc")
        dummy_path = Path(f.name)
    try:
        text = extractor.extract_text(dummy_path)
        print("DEBUG doc fallback text:", repr(text))
        assert "DOC extraction failed" in text or "张总" in text
    finally:
        dummy_path.unlink(missing_ok=True)


if __name__ == "__main__":
    test_docx_extraction()
    print("PASS: test_docx_extraction")

    test_pptx_extraction()
    print("PASS: test_pptx_extraction")

    test_csv_extraction()
    print("PASS: test_csv_extraction")

    test_supported_exts_includes_new_formats()
    print("PASS: test_supported_exts_includes_new_formats")

    test_doc_fallback_on_non_windows()
    print("PASS: test_doc_fallback_on_non_windows")

    print("\nAll extractor tests passed!")
