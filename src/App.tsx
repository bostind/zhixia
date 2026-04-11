import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import SettingsPanel from "./SettingsPanel";
import "./App.css";

interface FileItem {
  id: string;
  filename: string;
  path: string;
  summary?: string;
  tags?: string;
  ext?: string;
}

type ViewMode = "search" | "library" | "settings";

interface StatusInfo {
  watch_dirs: string[];
  total_files: number;
  indexed_files: number;
}

const API_BASE = "http://127.0.0.1:8765";

function extractPaths(text: string): string[] {
  // 1. 提取 PATH: 标记的路径
  const pathMatches = text.match(/PATH:\s*((?:[A-Z]:|\\\\)[^\n]+)/gi) || [];
  // 2. 通用 Windows 绝对路径提取（兼容引号、括号、中文标点）
  const generalMatches = text.match(/(?:[A-Z]:|\\\\)[^\s"<>|\n\u4e00-\u9fa5]+/gi) || [];
  const all = [
    ...pathMatches.map((m) => m.replace(/^PATH:\s*/i, "").trim()),
    ...generalMatches,
  ];
  // 清理尾部中文标点和引号/括号
  const cleaned = all.map((p) =>
    p
      .replace(/[，。、；：""''（）()\[\]{}]+$/g, "")
      .replace(/\\+$/, "")
      .trim()
  );
  return Array.from(
    new Set(cleaned.filter((p) => p.includes("\\") && p.length > 3))
  );
}

function getFileNameFromPath(path: string): string {
  const idx = path.lastIndexOf("\\");
  return idx >= 0 ? path.slice(idx + 1) : path;
}

function getExt(path: string): string {
  const name = getFileNameFromPath(path);
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

function fileTypeIcon(ext: string): string {
  return `/icons/${ext || "default"}.png`;
}

function fileTypeColor(ext: string): string {
  const map: Record<string, string> = {
    txt: "#22c55e",
    md: "#f59e0b",
    pdf: "#ef4444",
    xlsx: "#10b981",
    docx: "#3b82f6",
    pptx: "#f97316",
  };
  return map[ext] || "#8b8ba7";
}

interface Relation {
  from: string;
  to: string;
  reason: string;
}

function extractRelations(text: string): Relation[] {
  const matches = text.match(/RELATION:\s*([^\n]+)/gi) || [];
  return matches.map((m) => {
    const line = m.replace(/^RELATION:\s*/i, "").trim();
    const parts = line.split("|");
    const filesPart = parts[0] || "";
    const reason = parts.slice(1).join("|").trim();
    const fileNames = filesPart.split("->").map((s) => s.trim());
    return {
      from: fileNames[0] || "",
      to: fileNames[1] || "",
      reason,
    };
  }).filter((r) => r.from && r.to);
}

function extractFileExplanations(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  const pathMatches = Array.from(text.matchAll(/PATH:\s*((?:[A-Z]:|\\\\)[^\n]+)/gi));
  for (let i = 0; i < pathMatches.length; i++) {
    const path = pathMatches[i][1].trim();
    const start = (pathMatches[i].index || 0) + pathMatches[i][0].length;
    const end = i + 1 < pathMatches.length ? (pathMatches[i + 1].index || text.length) : text.length;
    const chunk = text.slice(start, end).trim();
    const fname = getFileNameFromPath(path);
    // 取第一行非空解释
    const explanation = chunk
      .split("\n")
      .map((l) => l.trim())
      .find((l) => l.length > 3 && !l.startsWith("RELATION:")) || "";
    out[fname] = explanation;
    out[path.toLowerCase()] = explanation;
  }
  return out;
}

export default function App() {
  const [pythonStatus, setPythonStatus] = useState<string>("connecting...");
  const [files, setFiles] = useState<FileItem[]>([]);
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasResult, setHasResult] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [view, setView] = useState<ViewMode>("search");
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [newDir, setNewDir] = useState("");
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [llmSettings, setLlmSettings] = useState({
    api_key: "",
    base_url: "",
    model: "",
    ingest_model: "",
    query_model: "",
  });
  const [llmSettingsLoading, setLlmSettingsLoading] = useState(false);
  const [ingestProgress, setIngestProgress] = useState<{ path: string; status: string; detail?: string }[]>([]);
  const orbitRef = useRef<HTMLDivElement>(null);
  const [feedbackMap, setFeedbackMap] = useState<Record<string, string>>({});
  const [resultView, setResultView] = useState<"list" | "graph">("list");
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
  const [editingTagId, setEditingTagId] = useState<string | null>(null);
  const [editingTagValue, setEditingTagValue] = useState("");
  interface QueryRecord {
    query: string;
    answer: string;
    files: string[];
    timestamp: number;
  }
  const [queryRecords, setQueryRecords] = useState<QueryRecord[]>([]);
  const [queryHistoryOpen, setQueryHistoryOpen] = useState(false);
  const [showFileList, setShowFileList] = useState(false);
  const [libraryTagFilter, setLibraryTagFilter] = useState<string | null>(null);

  interface Toast {
    id: number;
    message: string;
    type?: "success" | "error" | "info";
  }
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastIdRef = useRef(0);

  function showToast(message: string, type: "success" | "error" | "info" = "info") {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  }

  useEffect(() => {
    checkHealth();
    loadFiles();
    loadStatus();
    loadLlmSettings();
    const interval = setInterval(() => {
      checkHealth();
      loadFiles();
      loadStatus();
      loadIngestProgress();
    }, 8000);
    return () => clearInterval(interval);
  }, []);

  async function checkHealth() {
    try {
      const res = await fetch(`${API_BASE}/health`);
      const data = await res.json();
      setPythonStatus(data.status === "ok" ? "connected" : "error");
    } catch (e) {
      setPythonStatus("disconnected");
    }
  }

  async function loadFiles() {
    try {
      const res = await fetch(`${API_BASE}/files`);
      const data = await res.json();
      setFiles(data.files || []);
    } catch (e) {
      console.error("Failed to load files:", e);
    }
  }

  async function loadStatus() {
    try {
      const res = await fetch(`${API_BASE}/status`);
      const data = await res.json();
      setStatus(data);
    } catch (e) {
      console.error("Failed to load status:", e);
    }
  }

  async function loadIngestProgress() {
    try {
      const res = await fetch(`${API_BASE}/ingest_progress`);
      const data = await res.json();
      setIngestProgress(data.progress || []);
    } catch (e) {
      console.error("Failed to load ingest progress:", e);
    }
  }

  async function loadLlmSettings() {
    try {
      const res = await fetch(`${API_BASE}/settings`);
      const data = await res.json();
      setLlmSettings({
        api_key: data.api_key || "",
        base_url: data.base_url || "",
        model: data.model || "",
        ingest_model: data.ingest_model || "",
        query_model: data.query_model || "",
      });
    } catch (e) {
      console.error("Failed to load LLM settings:", e);
    }
  }

  async function saveLlmSettings() {
    setLlmSettingsLoading(true);
    try {
      const payload = { ...llmSettings };
      // 如果 api_key 是脱敏值，不传给后端，避免覆盖真实 key
      if (payload.api_key.startsWith("****")) {
        payload.api_key = "";
      }
      const res = await fetch(`${API_BASE}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.success) {
        showToast("配置已保存", "success");
      } else {
        showToast("保存失败", "error");
      }
    } catch (e) {
      showToast("保存配置出错: " + String(e), "error");
    } finally {
      setLlmSettingsLoading(false);
    }
  }

  async function sendFeedback(filePath: string, feedback: "helpful" | "irrelevant" | "wrong") {
    try {
      await fetch(`${API_BASE}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, file_path: filePath, feedback }),
      });
      setFeedbackMap((prev) => ({ ...prev, [filePath + query]: feedback }));
    } catch (e) {
      console.error("Failed to send feedback:", e);
    }
  }

  async function updateWatchDirs(dirs: string[]) {
    setSettingsBusy(true);
    try {
      const res = await fetch(`${API_BASE}/watch_dirs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dirs }),
      });
      const data = await res.json();
      if (Array.isArray(data.dirs)) {
        setStatus((s) => (s ? { ...s, watch_dirs: data.dirs } : s));
        setNewDir("");
      } else {
        showToast(data.error || "更新失败", "error");
      }
    } catch (e) {
      showToast("更新目录时出错: " + String(e), "error");
    } finally {
      setSettingsBusy(false);
    }
  }

  async function handleReindex() {
    setReindexing(true);
    try {
      const res = await fetch(`${API_BASE}/reindex`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        showToast(`已加入分析队列: ${data.queued} 个文件`, "success");
      } else {
        showToast("手动分析失败", "error");
      }
    } catch (e) {
      showToast("手动分析请求出错: " + String(e), "error");
    } finally {
      setReindexing(false);
    }
  }

  function handleRemoveDir(idx: number) {
    if (!status) return;
    const next = status.watch_dirs.filter((_, i) => i !== idx);
    updateWatchDirs(next);
  }

  function handleAddDir() {
    const trimmed = newDir.trim();
    if (!trimmed) return;
    if (!status) return;
    if (status.watch_dirs.includes(trimmed)) {
      setNewDir("");
      return;
    }
    updateWatchDirs([...status.watch_dirs, trimmed]);
  }

  async function runQuery(q: string) {
    if (!q.trim()) return;
    const trimmed = q.trim();
    setQuery(trimmed);
    setLoading(true);
    setAnswer("");
    setView("search");

    // 前端缓存：完全相同的问题直接复用历史结果
    const cached = queryRecords.find((r) => r.query === trimmed);
    if (cached) {
      setAnswer(cached.answer);
      setHasResult(true);
      setHistory((prev) => {
        const next = [trimmed, ...prev.filter((x) => x !== trimmed)];
        return next.slice(0, 8);
      });
      setLoading(false);
      return;
    }

    try {
      // 向后端发送时仍转换为旧格式上下文
      const context = queryRecords.flatMap((r) => [
        { role: "user", content: r.query },
        { role: "assistant", content: r.answer },
      ]);
      const res = await fetch(`${API_BASE}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, n_results: 5, context }),
      });
      const data = await res.json();
      const ans = data.answer || "No answer";
      setAnswer(ans);
      setHasResult(true);
      setHistory((prev) => {
        const next = [trimmed, ...prev.filter((x) => x !== trimmed)];
        return next.slice(0, 8);
      });
      const mentionedFiles = extractPaths(ans);
      setQueryRecords((prev) => {
        const next = [
          ...prev,
          { query: trimmed, answer: ans, files: mentionedFiles, timestamp: Date.now() },
        ];
        return next.slice(-10);
      });
    } catch (e) {
      setAnswer("Error: " + String(e));
      setHasResult(true);
    }
    setLoading(false);
  }

  function clearQueryRecords() {
    setQueryRecords([]);
    setHasResult(false);
    setAnswer("");
    setQuery("");
    setFeedbackMap({});
    setResultView("list");
  }

  async function openFile(path: string) {
    try {
      await invoke("open_file", { path });
    } catch (e) {
      console.error("Failed to open file:", e);
    }
  }

  async function openFolder(path: string) {
    try {
      await invoke("open_folder", { path });
    } catch (e) {
      console.error("Failed to open folder:", e);
    }
  }

  async function updateFileTags(docId: string, tags: string) {
    try {
      const res = await fetch(`${API_BASE}/files/${docId}/tags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags }),
      });
      const data = await res.json();
      if (data.success) {
        showToast("标签已更新", "success");
        loadFiles();
      } else {
        showToast(data.error || "更新失败", "error");
      }
    } catch (e) {
      showToast("更新标签出错: " + String(e), "error");
    }
  }

  async function runBatchAction(action: "delete" | "reindex", ids: string[]) {
    try {
      const res = await fetch(`${API_BASE}/files/batch_action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ids }),
      });
      const data = await res.json();
      if (data.success) {
        showToast(`${action === "delete" ? "删除" : "重新分析"}完成: ${data.processed} 个文件`, "success");
        setSelectedFileIds(new Set());
        loadFiles();
        loadStatus();
      } else {
        showToast(data.error || "操作失败", "error");
      }
    } catch (e) {
      showToast("批量操作出错: " + String(e), "error");
    }
  }

  const extractedCards = useMemo(() => {
    const paths = extractPaths(answer);
    return paths.map((p, i) => {
      const matched = files.find((f) => f.path.toLowerCase() === p.toLowerCase());
      return {
        id: matched?.id || `extracted-${i}`,
        path: p,
        filename: getFileNameFromPath(p),
        ext: getExt(p),
        tags: matched?.tags,
      };
    });
  }, [answer, files]);

  const relatedFiles = useMemo(() => {
    // 把 answer 中提到路径的已索引文件置顶
    const mentioned = new Set(extractedCards.map((c) => c.path.toLowerCase()));
    const top = files.filter((f) => mentioned.has(f.path.toLowerCase()));
    const rest = files.filter((f) => !mentioned.has(f.path.toLowerCase()));
    return { top, rest };
  }, [files, extractedCards]);

  const relations = useMemo(() => extractRelations(answer), [answer]);
  const explanations = useMemo(() => extractFileExplanations(answer), [answer]);

  const allResultCards = useMemo(
    () => [...extractedCards, ...relatedFiles.top.map((f) => ({ ...f, id: f.id }))],
    [extractedCards, relatedFiles.top]
  );

  const cardAngles = useMemo(() => {
    const count = allResultCards.length || 1;
    return allResultCards.map((_, i) => (i / count) * Math.PI * 2);
  }, [allResultCards.length]);

  const cardPositions = useMemo(() => {
    return cardAngles.map((angle) => {
      const r = 300;
      return {
        x: 480 + Math.cos(angle) * r,
        y: 180 + Math.sin(angle) * (r * 0.45),
      };
    });
  }, [cardAngles]);

  const webLines = useMemo(() => {
    const lines: { d: string; type: "base" | "relation"; reason?: string; midX?: number; midY?: number }[] = [];
    // 基础连线：中心到每个卡片
    allResultCards.forEach((_, i) => {
      const pos = cardPositions[i];
      if (pos) {
        lines.push({ d: `M 480 160 Q 480 220 ${pos.x} ${pos.y}`, type: "base" });
      }
    });
    // 关系连线：有关联的卡片之间
    relations.forEach((rel) => {
      const fromIdx = allResultCards.findIndex((c) => c.filename === rel.from || c.path.endsWith("\\" + rel.from));
      const toIdx = allResultCards.findIndex((c) => c.filename === rel.to || c.path.endsWith("\\" + rel.to));
      if (fromIdx >= 0 && toIdx >= 0) {
        const p1 = cardPositions[fromIdx];
        const p2 = cardPositions[toIdx];
        const midX = (p1.x + p2.x) / 2;
        const midY = (p1.y + p2.y) / 2 - 40;
        lines.push({
          d: `M ${p1.x} ${p1.y} Q ${midX} ${midY} ${p2.x} ${p2.y}`,
          type: "relation",
          reason: rel.reason,
          midX,
          midY,
        });
      }
    });
    return lines;
  }, [allResultCards, cardPositions, relations]);

  const tagStats = useMemo(() => {
    const counts: Record<string, number> = {};
    files.forEach((f) => {
      if (f.tags) {
        f.tags.split(",").forEach((t) => {
          const tag = t.trim();
          if (tag) counts[tag] = (counts[tag] || 0) + 1;
        });
      }
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [files]);

  const typeDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    files.forEach((f) => {
      const ext = f.ext || "未知";
      counts[ext] = (counts[ext] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 4);
  }, [files]);

  const filteredLibraryFiles = useMemo(() => {
    if (!libraryTagFilter) return files;
    return files.filter((f) => f.tags && f.tags.split(",").some((t) => t.trim() === libraryTagFilter));
  }, [files, libraryTagFilter]);

  const statusLabel = pythonStatus === "connected" ? "在线" : "离线";

  return (
    <>
      <div className="nebula-bg" />
      <div className="stars" />
      <div className="app-shell">
        <div className="toast-container">
          {toasts.map((t) => (
            <div key={t.id} className={`toast ${t.type || "info"}`}>
              <div className="toast-bar" />
              <div className="toast-message">{t.message}</div>
            </div>
          ))}
        </div>

        {editingTagId && (
          <div className="tag-edit-overlay" onClick={() => setEditingTagId(null)}>
            <div className="tag-edit-modal" onClick={(e) => e.stopPropagation()}>
              <h4>编辑标签</h4>
              <input
                value={editingTagValue}
                onChange={(e) => setEditingTagValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    updateFileTags(editingTagId, editingTagValue);
                    setEditingTagId(null);
                  }
                  if (e.key === "Escape") {
                    setEditingTagId(null);
                  }
                }}
                autoFocus
              />
              <div className="tag-edit-actions">
                <button className="tag-edit-btn ghost" onClick={() => setEditingTagId(null)}>取消</button>
                <button className="tag-edit-btn" onClick={() => { updateFileTags(editingTagId, editingTagValue); setEditingTagId(null); }}>保存</button>
              </div>
            </div>
          </div>
        )}

        <aside className="sidebar">
          <div className="sidebar-brand">
            <div className="logo-mark">知</div>
            <div className="brand-name">知匣</div>
          </div>
          <div className="sidebar-divider" />
          <div className="sidebar-nav">
            <div
              className={`nav-item ${view === "search" ? "active" : ""}`}
              onClick={() => setView("search")}
              title="搜索"
            >
              🔭
            </div>
            <div
              className={`nav-item ${view === "library" ? "active" : ""}`}
              onClick={() => {
                setView("library");
                loadFiles();
              }}
              title="索引库"
            >
              🗂️
            </div>
            <div
              className={`nav-item ${view === "settings" ? "active" : ""}`}
              onClick={() => setView("settings")}
              title="设置"
            >
              ⚙️
            </div>
          </div>

          <div className="sidebar-footer">
            {ingestProgress.filter((p) => p.status === "processing" || p.status === "queued").length > 0 && (
              <div className="sidebar-progress" title="正在分析文件...">
                <div className="sidebar-progress-bar" />
              </div>
            )}
            <div className={`status-dot ${pythonStatus === "connected" ? "connected" : ""}`} title={`Python ${statusLabel}`} />
            <div className="status-label">{statusLabel}</div>
          </div>
        </aside>

        <main className="main-stage">
          {(() => {
            const active = ingestProgress.filter((p) => p.status === "processing" || p.status === "queued");
            if (active.length === 0) return null;
            const total = ingestProgress.length || 1;
            const pct = Math.max(5, Math.min(95, ((ingestProgress.filter((p) => p.status === "done").length / total) * 100)));
            return (
              <div className="global-progress">
                <div className="global-progress-bar" style={{ width: `${pct}%` }} />
                <span className="global-progress-text">
                  {active.filter((p) => p.status === "processing").length} 分析中 · {active.filter((p) => p.status === "queued").length} 排队中
                </span>
              </div>
            );
          })()}
          {view === "settings" && (
            <div className="settings-page">
              <div className="settings-page-header">
                <h2>设置</h2>
                <p className="settings-page-subtitle">管理监控目录、LLM 配置与系统状态</p>
              </div>
              <SettingsPanel
                status={status}
                settingsBusy={settingsBusy}
                newDir={newDir}
                setNewDir={setNewDir}
                handleAddDir={handleAddDir}
                handleRemoveDir={handleRemoveDir}
                llmSettings={llmSettings}
                setLlmSettings={setLlmSettings}
                saveLlmSettings={saveLlmSettings}
                llmSettingsLoading={llmSettingsLoading}
                ingestProgress={ingestProgress}
                reindexing={reindexing}
                handleReindex={handleReindex}
                openFolder={openFolder}
                showToast={showToast}
              />
            </div>
          )}

          {view === "search" && (
            <>
              <div className={`search-stage ${hasResult ? "has-results" : ""}`}>
                <div className="search-hint">Knowledge Nebula</div>
                {status && status.watch_dirs.length > 0 && (
                  <div className="status-bar">
                    <span className="status-item" title={status.watch_dirs.join("\n")}>
                      📁 {status.watch_dirs.map((d) => d.replace(/\\/g, "/").split("/").pop()).join(", ")}
                    </span>
                    <span className="status-divider" />
                    <span className="status-item">
                      🧠 索引 {status.indexed_files} / {status.total_files}
                      {status.indexed_files < status.total_files && (
                        <span className="indexing-pulse" title="正在构建认知层..." />
                      )}
                    </span>
                  </div>
                )}
                {ingestProgress.filter((p) => p.status === "processing" || p.status === "queued").length > 0 && (
                  <div className="ingest-progress">
                    {ingestProgress
                      .filter((p) => p.status === "processing" || p.status === "queued")
                      .slice(0, 2)
                      .map((p) => (
                        <span key={p.path} className="ingest-progress-item">
                          {p.status === "processing" ? "🔄 正在分析" : "⏳ 排队中"}: {getFileNameFromPath(p.path)}
                        </span>
                      ))}
                  </div>
                )}
                <button
                  className="reindex-btn"
                  onClick={handleReindex}
                  disabled={reindexing}
                  title="强制重新分析所有监控目录中的文件"
                >
                  {reindexing ? "分析中..." : "🔄 手动分析"}
                </button>
                <div className="search-glow">
                  {queryRecords.length > 0 && (
                    <>
                      <button
                        className="query-badge"
                        onClick={() => setQueryHistoryOpen((v) => !v)}
                        type="button"
                        title="点击查看查询记录"
                      >
                        🕐 查询记录 · {queryRecords.length} 条
                      </button>
                      {queryHistoryOpen && (
                        <div className="query-history-panel">
                          <div className="query-history-hint">相同问题将直接复用历史结果，点击记录可快速重新查询</div>
                          <div className="query-history-list">
                            {queryRecords.map((rec, idx) => (
                              <div key={idx} className="query-record-card">
                                <div className="query-record-header">
                                  <span className="query-record-q">{rec.query}</span>
                                  <span className="query-record-meta">
                                    {rec.files.length > 0 && `· ${rec.files.length} 个文件 `}
                                    · {new Date(rec.timestamp).toLocaleTimeString()}
                                  </span>
                                </div>
                                <div className="query-record-summary">
                                  {rec.answer.slice(0, 90)}{rec.answer.length > 90 ? "…" : ""}
                                </div>
                                <div className="query-record-actions">
                                  <button className="query-record-btn" onClick={() => { setQuery(rec.query); runQuery(rec.query); }}>重新查询</button>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      runQuery(query);
                    }}
                    className="search-form"
                  >
                    <input
                      type="text"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="描述你想找的文件，例如：张总负责的预算..."
                      className="search-input"
                    />
                    <button type="submit" disabled={loading} className="search-btn">
                      查询
                    </button>
                  </form>
                </div>

                {loading && (
                  <div className="search-loading">
                    <div className="search-pulse-ring" />
                    <div className="search-scan-line" />
                    <div className="search-loading-text">正在扫描认知层…</div>
                  </div>
                )}

                {!hasResult && !loading && history.length > 0 && (
                  <div className="history-chips">
                    {history.map((h) => (
                      <span key={h} className="chip" onClick={() => runQuery(h)}>
                        {h}
                      </span>
                    ))}
                  </div>
                )}

                {!hasResult && !loading && files.length === 0 && (
                  <div className="empty-constellation" style={{ marginTop: "4rem" }}>
                    <div className="empty-orbit">
                      <div className="empty-core" />
                    </div>
                    <div className="empty-title">认知层为空</div>
                    <div className="empty-desc">将 .txt / .md / .pdf / .xlsx / .docx / .pptx / .csv 文件放入监控目录，AI 会自动构建索引</div>
                  </div>
                )}
              </div>

              <div className={`constellation ${hasResult ? "visible" : ""}`}>
                <div className="constellation-inner" ref={orbitRef}>
                  <div className="result-actions">
                    <div className="result-actions-left">
                      <button
                        className="back-btn"
                        onClick={() => {
                          setHasResult(false);
                          setAnswer("");
                          setQuery("");
                          setFeedbackMap({});
                          setResultView("list");
                          setQueryHistoryOpen(false);
                        }}
                      >
                        ← 返回
                      </button>
                      {queryRecords.length > 0 && (
                        <button className="back-btn" onClick={() => { clearQueryRecords(); setQueryHistoryOpen(false); }}>
                          🔄 清空记录
                        </button>
                      )}
                    </div>
                    {allResultCards.length > 0 && (
                      <div className="result-actions-right">
                        <div className="view-toggle">
                          <button
                            className={resultView === "list" ? "active" : ""}
                            onClick={() => setResultView("list")}
                          >
                            列表
                          </button>
                          <button
                            className={resultView === "graph" ? "active" : ""}
                            onClick={() => setResultView("graph")}
                          >
                            图谱
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  {resultView === "graph" && (
                    <svg className="web-svg" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">
                      <defs>
                        <linearGradient id="lineGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                          <stop offset="0%" stopColor="rgba(0,212,255,0.4)" />
                          <stop offset="100%" stopColor="rgba(123,58,237,0.2)" />
                        </linearGradient>
                      </defs>
                      {webLines.map((line, i) => (
                        <g key={i}>
                          <path
                            d={line.d}
                            className={`web-line ${line.type === "relation" ? "relation-line" : ""}`}
                            style={{ animationDelay: `${i * 80}ms` }}
                            fill="none"
                          />
                          {line.type === "relation" && line.reason && line.midX != null && line.midY != null && (
                            <g>
                              <rect
                                x={(line.midX || 0) - 60}
                                y={(line.midY || 0) - 14}
                                width="120"
                                height="20"
                                rx="4"
                                fill="rgba(10,10,20,0.8)"
                                stroke="rgba(255,0,170,0.25)"
                              />
                              <text className="relation-tooltip" x={line.midX} y={(line.midY || 0) + 1} textAnchor="middle">
                                {line.reason.length > 18 ? line.reason.slice(0, 18) + "…" : line.reason}
                              </text>
                            </g>
                          )}
                        </g>
                      ))}
                    </svg>
                  )}

                  {resultView === "graph" && <div className="graph-center-glow" />}
                  <div className={resultView === "graph" ? "query-node graph-mode" : "query-node list-mode"}>{query}</div>


                  <div className={resultView === "graph" ? "orbit graph-orbit" : "orbit list-orbit"}>
                    {resultView === "list" ? (
                      <div className="list-results">
                        {allResultCards.map((c, idx) => {
                          const explanation =
                            explanations[c.filename] || explanations[c.path.toLowerCase()] || "";
                          const fbKey = c.path + query;
                          const fb = feedbackMap[fbKey];
                          return (
                            <div
                              key={c.id}
                              className="list-result-item"
                              style={{ animationDelay: `${idx * 60}ms` }}
                            >
                              <div
                                className="list-result-icon"
                                onClick={() => openFile(c.path)}
                              >
                                <img src={fileTypeIcon(("ext" in c ? c.ext : "") || "")} alt="" onError={(e) => { e.currentTarget.src = "/icons/default.png"; }} />
                              </div>
                              <div className="list-result-body" onClick={() => openFile(c.path)}>
                                <div className="list-result-title">{c.filename}</div>
                                {explanation && <div className="list-result-reason">{explanation}</div>}
                                <div className="list-result-path">{c.path}</div>
                              </div>
                              <div className="list-result-meta">
                                <div className="list-result-actions">
                                  <button
                                    className="list-result-action-btn"
                                    onClick={(e) => { e.stopPropagation(); openFolder(c.path); }}
                                    title="在文件夹中显示"
                                  >
                                    📂
                                  </button>
                                  {!String(c.id).startsWith("extracted-") && (
                                    <button
                                      className="list-result-action-btn"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setEditingTagId(c.id);
                                        setEditingTagValue((c as any).tags || "");
                                      }}
                                      title="编辑标签"
                                    >
                                      🏷️
                                    </button>
                                  )}
                                  <span className="list-result-action" onClick={() => openFile(c.path)}>打开 →</span>
                                </div>
                                <div className="list-result-feedback">
                                  <button
                                    className={fb === "helpful" ? "active" : ""}
                                    onClick={(e) => { e.stopPropagation(); sendFeedback(c.path, "helpful"); }}
                                    title="有用"
                                  >
                                    👍
                                  </button>
                                  <button
                                    className={fb === "irrelevant" || fb === "wrong" ? "active" : ""}
                                    onClick={(e) => { e.stopPropagation(); sendFeedback(c.path, "irrelevant"); }}
                                    title="不相关"
                                  >
                                    👎
                                  </button>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                        {allResultCards.length === 0 && answer && (
                          <div className="empty-constellation mini">
                            <div className="empty-orbit small">
                              <div className="empty-core" />
                            </div>
                            <div className="empty-title">未识别到可定位的文件路径</div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <>
                        {allResultCards.map((c, idx) => {
                          const pos = cardPositions[idx];
                          const relReason = relations.find(
                            (r) =>
                              c.filename === r.from ||
                              c.path.endsWith("\\" + r.from) ||
                              c.filename === r.to ||
                              c.path.endsWith("\\" + r.to)
                          )?.reason;
                          const color = fileTypeColor(("ext" in c ? c.ext : "") || "");
                          const fbKey = c.path + query;
                          const fb = feedbackMap[fbKey];
                          return (
                            <div
                              key={c.id}
                              className="graph-node"
                              style={{
                                animationDelay: `${idx * 80}ms`,
                                left: pos?.x ?? 0,
                                top: pos?.y ?? 0,
                                boxShadow: `0 0 24px ${color}40, inset 0 0 0 1px ${color}60`,
                              }}
                              title="点击打开文件"
                            >
                              <div className="graph-node-icon" style={{ color }} onClick={() => openFile(c.path)}>
                                <img src={fileTypeIcon(("ext" in c ? c.ext : "") || "")} alt="" onError={(e) => { e.currentTarget.src = "/icons/default.png"; }} />
                              </div>
                              <div className="graph-node-name" onClick={() => openFile(c.path)}>{c.filename}</div>
                              {relReason && (
                                <div className="graph-node-relation" title={relReason} onClick={() => openFile(c.path)}>
                                  {relReason.length > 20 ? relReason.slice(0, 20) + "…" : relReason}
                                </div>
                              )}
                              <div className="graph-node-actions">
                                <button
                                  onClick={(e) => { e.stopPropagation(); openFolder(c.path); }}
                                  title="在文件夹中显示"
                                >
                                  📂
                                </button>
                                {!String(c.id).startsWith("extracted-") && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setEditingTagId(c.id);
                                      setEditingTagValue((c as any).tags || "");
                                    }}
                                    title="编辑标签"
                                  >
                                    🏷️
                                  </button>
                                )}
                              </div>
                              <div className="graph-node-feedback">
                                <button
                                  className={fb === "helpful" ? "active" : ""}
                                  onClick={(e) => { e.stopPropagation(); sendFeedback(c.path, "helpful"); }}
                                  title="有用"
                                >
                                  👍
                                </button>
                                <button
                                  className={fb === "irrelevant" || fb === "wrong" ? "active" : ""}
                                  onClick={(e) => { e.stopPropagation(); sendFeedback(c.path, "irrelevant"); }}
                                  title="不相关"
                                >
                                  👎
                                </button>
                              </div>
                              <div className="graph-node-ring" style={{ borderColor: color }} />
                            </div>
                          );
                        })}

                        {allResultCards.length === 0 && answer && (
                          <div className="empty-constellation mini">
                            <div className="empty-orbit small">
                              <div className="empty-core" />
                            </div>
                            <div className="empty-title">未识别到可定位的文件路径</div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

          {view === "library" && (
            <div className="constellation visible library-constellation" style={{ position: "relative", top: 0 }}>
              <div className="constellation-inner">
                <div className="library-dashboard">
                  <div className="library-stat-grid">
                    <div className="library-stat-card">
                      <div className="library-stat-value">{files.length}</div>
                      <div className="library-stat-label">已索引文件</div>
                    </div>
                    <div className="library-stat-card">
                      <div className="library-stat-value">{status?.indexed_files || 0}</div>
                      <div className="library-stat-label">有效索引</div>
                    </div>
                    <div className="library-stat-card">
                      <div className="library-stat-value">{status?.watch_dirs?.length || 0}</div>
                      <div className="library-stat-label">监控目录</div>
                    </div>
                    <div className="library-stat-card">
                      <div className="library-stat-value">{tagStats.length}</div>
                      <div className="library-stat-label">标签总数</div>
                    </div>
                    <div className="library-stat-card wide">
                      <div className="library-type-bar">
                        {typeDistribution.map(([ext, count]) => (
                          <div key={ext} className="library-type-chip" style={{ color: fileTypeColor(ext) }}>
                            <img src={fileTypeIcon(ext)} alt="" onError={(e) => { e.currentTarget.src = "/icons/default.png"; }} />
                            <span>{ext === "未知" ? "未知" : ext.toUpperCase()} {count}</span>
                          </div>
                        ))}
                        {typeDistribution.length === 0 && <span className="library-type-empty">暂无类型统计</span>}
                      </div>
                      <div className="library-stat-label" style={{ marginTop: "0.3rem" }}>类型分布 TOP4</div>
                    </div>
                  </div>

                  <div className="tag-cloud">
                    {tagStats.map(([tag, count], idx) => {
                      const scale = 0.8 + Math.min(count * 0.12, 1.0);
                      const hue = (idx * 47 + 180) % 360;
                      return (
                        <button
                          key={tag}
                          className="tag-cloud-item"
                          onClick={() => setLibraryTagFilter(tag)}
                          title={`出现 ${count} 次`}
                          style={{
                            fontSize: `${scale}rem`,
                            color: `hsl(${hue}, 85%, 65%)`,
                            borderColor: `hsla(${hue}, 85%, 65%, 0.3)`,
                            background: `hsla(${hue}, 85%, 65%, 0.08)`,
                          }}
                        >
                          {tag}
                        </button>
                      );
                    })}
                    {tagStats.length === 0 && (
                      <div className="tag-cloud-empty">暂无标签数据，分析文件后会自动生成标签</div>
                    )}
                  </div>

                  {libraryTagFilter && (
                    <div className="tag-filter-bar">
                      <span>已选标签：<b style={{ color: "var(--cyan)" }}>{libraryTagFilter}</b></span>
                      <button className="back-btn" onClick={() => setLibraryTagFilter(null)}>清除筛选</button>
                    </div>
                  )}

                  <button className="toggle-filelist-btn" onClick={() => setShowFileList((v) => !v)}>
                    {showFileList ? "▲ 收起文件列表" : "📂 查看全部文件列表"}
                  </button>

                  {showFileList && (
                    <>
                      {selectedFileIds.size > 0 && (
                        <div className="batch-bar">
                          <label className="batch-check">
                            <input
                              type="checkbox"
                              checked={selectedFileIds.size === filteredLibraryFiles.length && filteredLibraryFiles.length > 0}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedFileIds(new Set(filteredLibraryFiles.map((f) => f.id)));
                                } else {
                                  setSelectedFileIds(new Set());
                                }
                              }}
                            />
                            <span>全选</span>
                          </label>
                          <span className="batch-count">已选 {selectedFileIds.size} 项</span>
                          <button className="batch-btn" onClick={() => runBatchAction("reindex", Array.from(selectedFileIds))} title="重新分析">🔄 重新分析</button>
                          <button className="batch-btn danger" onClick={() => { if (confirm("确定要删除所选文件的索引吗？此操作不可恢复。")) { runBatchAction("delete", Array.from(selectedFileIds)); } }} title="删除索引">🗑️ 删除索引</button>
                          <button className="batch-btn ghost" onClick={() => setSelectedFileIds(new Set())}>取消</button>
                        </div>
                      )}

                      <div className="library-list">
                        {filteredLibraryFiles.map((f, idx) => {
                          const color = fileTypeColor(f.ext || "");
                          const isSelected = selectedFileIds.has(f.id);
                          return (
                            <div key={f.id} className={`library-item ${isSelected ? "selected" : ""}`} style={{ animationDelay: `${idx * 40}ms` }}>
                              <input type="checkbox" className="library-checkbox" checked={isSelected} onChange={(e) => { const next = new Set(selectedFileIds); if (e.target.checked) next.add(f.id); else next.delete(f.id); setSelectedFileIds(next); }} onClick={(e) => e.stopPropagation()} />
                              <div className="library-icon" style={{ color }} onClick={() => openFile(f.path)}>
                                <img src={fileTypeIcon(f.ext || "")} alt="" onError={(e) => { e.currentTarget.src = "/icons/default.png"; }} />
                              </div>
                              <div className="library-body" onClick={() => openFile(f.path)}>
                                <div className="library-title">{f.filename}</div>
                                {f.summary && <div className="library-summary">{f.summary}</div>}
                                <div className="library-path">{f.path}</div>
                              </div>
                              <div className="library-meta">
                                {editingTagId === f.id ? (
                                  <div className="tag-edit-inline">
                                    <input value={editingTagValue} onChange={(e) => setEditingTagValue(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { updateFileTags(f.id, editingTagValue); setEditingTagId(null); } if (e.key === "Escape") { setEditingTagId(null); } }} onBlur={() => { updateFileTags(f.id, editingTagValue); setEditingTagId(null); }} autoFocus />
                                  </div>
                                ) : (
                                  <>
                                    {f.tags && (
                                      <div className="library-tags" onClick={() => openFile(f.path)}>
                                        {f.tags.split(",").slice(0, 2).map((t) => (<span key={t} className="library-tag">{t.trim()}</span>))}
                                        {f.tags.split(",").length > 2 && (<span className="library-tag-more">+{f.tags.split(",").length - 2}</span>)}
                                      </div>
                                    )}
                                    <div className="library-actions">
                                      <button className="library-action-btn" onClick={(e) => { e.stopPropagation(); openFolder(f.path); }} title="在文件夹中显示">📂</button>
                                      <button className="library-action-btn" onClick={(e) => { e.stopPropagation(); setEditingTagId(f.id); setEditingTagValue(f.tags || ""); }} title="编辑标签">🏷️</button>
                                      <span className="library-action" onClick={() => openFile(f.path)}>打开 →</span>
                                    </div>
                                  </>
                                )}
                              </div>
                            </div>
                          );
                        })}
                        {filteredLibraryFiles.length === 0 && (
                          <div className="empty-constellation mini">
                            <div className="empty-orbit small"><div className="empty-core" /></div>
                            <div className="empty-title">没有符合条件的文件</div>
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </>
  );
}
