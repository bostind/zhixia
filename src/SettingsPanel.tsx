import { useState, useMemo } from "react";
import { open } from "@tauri-apps/plugin-dialog";

interface StatusInfo {
  watch_dirs: string[];
  total_files: number;
  indexed_files: number;
}

interface SettingsPanelProps {
  status: StatusInfo | null;
  settingsBusy: boolean;
  newDir: string;
  setNewDir: (v: string) => void;
  handleAddDir: () => void;
  handleRemoveDir: (idx: number) => void;
  llmSettings: {
    api_key: string;
    base_url: string;
    model: string;
    ingest_model: string;
    query_model: string;
  };
  setLlmSettings: (s: any) => void;
  saveLlmSettings: () => void;
  llmSettingsLoading: boolean;
  ingestProgress: { path: string; status: string; detail?: string }[];
  reindexing: boolean;
  handleReindex: () => void;
  openFolder: (path: string) => void;
  showToast?: (msg: string, type?: "success" | "error" | "info") => void;
  testLlm?: () => Promise<{ ok: boolean; message: string }>;
}

const PRESETS = [
  { key: "custom", name: "自定义", base_url: "", model: "" },
  { key: "moonshot", name: "Moonshot", base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k" },
  { key: "openai", name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  { key: "silicon", name: "硅基流动", base_url: "https://api.siliconflow.cn/v1", model: "deepseek-ai/DeepSeek-V3" },
];

export default function SettingsPanel(props: SettingsPanelProps) {
  const {
    status,
    settingsBusy,
    newDir,
    setNewDir,
    handleAddDir,
    handleRemoveDir,
    llmSettings,
    setLlmSettings,
    saveLlmSettings,
    llmSettingsLoading,
    ingestProgress,
    reindexing,
    handleReindex,
    openFolder,
    showToast,
    testLlm,
  } = props;

  const [activeTab, setActiveTab] = useState<"dirs" | "llm" | "system">("dirs");
  const [showApiKey, setShowApiKey] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [llmTestLoading, setLlmTestLoading] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState<{ ok?: boolean; message?: string } | null>(null);

  const stats = useMemo(() => {
    const all = ingestProgress || [];
    return {
      queued: all.filter((p) => p.status === "queued").length,
      processing: all.filter((p) => p.status === "processing").length,
      done: all.filter((p) => p.status === "done").length,
      error: all.filter((p) => p.status === "error").length,
      recent: all.slice(-8).reverse(),
    };
  }, [ingestProgress]);

  function applyPreset(key: string) {
    const preset = PRESETS.find((p) => p.key === key);
    if (!preset) return;
    setLlmSettings((s: any) => ({
      ...s,
      base_url: preset.base_url,
      model: preset.model,
    }));
  }

  const currentPreset = useMemo(() => {
    return (
      PRESETS.find(
        (p) => p.base_url === llmSettings.base_url && p.model === llmSettings.model
      )?.key || "custom"
    );
  }, [llmSettings.base_url, llmSettings.model]);

  return (
    <div className="settings-body">
      <div className="settings-tabs">
        <button className={activeTab === "dirs" ? "active" : ""} onClick={() => setActiveTab("dirs")}>
          监控目录
        </button>
        <button className={activeTab === "llm" ? "active" : ""} onClick={() => setActiveTab("llm")}>
          LLM 配置
        </button>
        <button className={activeTab === "system" ? "active" : ""} onClick={() => setActiveTab("system")}>
          系统状态
        </button>
      </div>

      {activeTab === "dirs" && (
        <div className="settings-section">
          <h4>监控目录</h4>
          <div className="settings-chips">
            {(status?.watch_dirs || []).map((d, idx) => (
              <div className="settings-chip" key={d + idx} title={d}>
                <span className="settings-chip-dir">{d}</span>
                <button
                  className="settings-chip-open"
                  onClick={() => openFolder(d)}
                  disabled={settingsBusy}
                  title="在文件夹中打开"
                >
                  📂
                </button>
                <button
                  className="settings-chip-remove"
                  onClick={() => handleRemoveDir(idx)}
                  disabled={settingsBusy}
                  title="移除"
                >
                  ✕
                </button>
              </div>
            ))}
            {(status?.watch_dirs || []).length === 0 && (
              <div className="settings-empty">暂无监控目录</div>
            )}
          </div>
          <div className="settings-add">
            <div className="settings-field floating" style={{ flex: 1 }}>
              <input
                id="new-dir"
                type="text"
                placeholder=" "
                value={newDir}
                onChange={(e) => setNewDir(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleAddDir();
                }}
                disabled={settingsBusy}
              />
              <label htmlFor="new-dir">输入文件夹路径，例如 D:\工作文档</label>
            </div>
            <button
              className="settings-browse-btn"
              onClick={async () => {
                try {
                  const selected = await open({ directory: true });
                  if (selected && typeof selected === "string") {
                    setNewDir(selected);
                  }
                } catch (e) {
                  showToast && showToast("无法打开文件夹选择器: " + String(e), "error");
                }
              }}
              disabled={settingsBusy}
              title="浏览目录"
            >
              浏览…
            </button>
            <button
              className="settings-add-btn"
              onClick={handleAddDir}
              disabled={settingsBusy || !newDir.trim()}
            >
              添加
            </button>
          </div>
          {settingsBusy && (
            <div className="settings-busy">
              <span className="settings-spinner" /> 保存中…
            </div>
          )}
        </div>
      )}

      {activeTab === "llm" && (
        <div className="settings-section">
          <h4>LLM 配置</h4>
          <div className="settings-form">
            <div className="settings-field">
              <label>服务商预设</label>
              <select
                value={currentPreset}
                onChange={(e) => applyPreset(e.target.value)}
                className="settings-select"
              >
                {PRESETS.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="settings-field floating">
              <input
                id="llm-base-url"
                type="text"
                placeholder=" "
                value={llmSettings.base_url}
                onChange={(e) => setLlmSettings((s: any) => ({ ...s, base_url: e.target.value }))}
              />
              <label htmlFor="llm-base-url">Base URL</label>
            </div>

            <div className="settings-row-apikey">
              <div className="settings-field floating" style={{ flex: 1 }}>
                <input
                  id="llm-api-key"
                  type={showApiKey ? "text" : "password"}
                  placeholder=" "
                  value={llmSettings.api_key}
                  onChange={(e) => setLlmSettings((s: any) => ({ ...s, api_key: e.target.value }))}
                />
                <label htmlFor="llm-api-key">API Key</label>
              </div>
              <button
                className="settings-eye-btn"
                onClick={() => setShowApiKey((v) => !v)}
                title={showApiKey ? "隐藏" : "显示"}
              >
                {showApiKey ? "🙈" : "👁️"}
              </button>
            </div>

            <div className="settings-field floating">
              <input
                id="llm-model"
                type="text"
                placeholder=" "
                value={llmSettings.model}
                onChange={(e) => setLlmSettings((s: any) => ({ ...s, model: e.target.value }))}
              />
              <label htmlFor="llm-model">基础模型</label>
            </div>

            <div className="settings-advanced-toggle">
              <button onClick={() => setShowAdvanced((v) => !v)}>
                {showAdvanced ? "▼ 收起高级选项" : "▶ 高级选项"}
              </button>
            </div>

            {showAdvanced && (
              <>
                <div className="settings-field floating">
                  <input
                    id="llm-ingest-model"
                    type="text"
                    placeholder=" "
                    value={llmSettings.ingest_model}
                    onChange={(e) => setLlmSettings((s: any) => ({ ...s, ingest_model: e.target.value }))}
                  />
                  <label htmlFor="llm-ingest-model">Ingest Model（为空则使用基础模型）</label>
                </div>
                <div className="settings-field floating">
                  <input
                    id="llm-query-model"
                    type="text"
                    placeholder=" "
                    value={llmSettings.query_model}
                    onChange={(e) => setLlmSettings((s: any) => ({ ...s, query_model: e.target.value }))}
                  />
                  <label htmlFor="llm-query-model">Query Model（为空则使用基础模型）</label>
                </div>
              </>
            )}

            <div className="settings-row" style={{ display: "flex", gap: "0.6rem", marginTop: "0.4rem" }}>
              <button
                className="settings-save-btn"
                onClick={saveLlmSettings}
                disabled={llmSettingsLoading}
                style={{ flex: 1 }}
              >
                {llmSettingsLoading && <span className="settings-spinner" />}
                {llmSettingsLoading ? "保存中..." : "保存配置"}
              </button>
              <button
                className="settings-save-btn secondary"
                onClick={async () => {
                  setLlmTestLoading(true);
                  setLlmTestResult(null);
                  try {
                    const res = await (testLlm ? testLlm() : Promise.resolve({ ok: false, message: "未提供测试方法" }));
                    setLlmTestResult(res);
                    if (showToast) {
                      showToast(res.ok ? `连接成功: ${res.message}` : `连接失败: ${res.message}`, res.ok ? "success" : "error");
                    }
                  } finally {
                    setLlmTestLoading(false);
                  }
                }}
                disabled={llmTestLoading}
              >
                {llmTestLoading && <span className="settings-spinner" />}
                {llmTestLoading ? "测试中..." : "测试连接"}
              </button>
            </div>
            {llmTestResult && (
              <div
                className="llm-test-result"
                style={{
                  marginTop: "0.6rem",
                  padding: "0.5rem 0.75rem",
                  borderRadius: "10px",
                  fontSize: "0.85rem",
                  background: llmTestResult.ok ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)",
                  color: llmTestResult.ok ? "#86efac" : "#fca5a5",
                  border: `1px solid ${llmTestResult.ok ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)"}`,
                }}
              >
                {llmTestResult.ok ? "✅ 连接成功" : "❌ 连接失败"}: {llmTestResult.message}
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === "system" && (
        <div className="settings-section">
          <h4>系统状态</h4>
          <div className="stats-grid">
            <div className="stat-card">
              <div className="stat-value">{stats.queued}</div>
              <div className="stat-label">排队中</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{stats.processing}</div>
              <div className="stat-label">分析中</div>
            </div>
            <div className="stat-card success">
              <div className="stat-value">{stats.done}</div>
              <div className="stat-label">已完成</div>
            </div>
            <div className="stat-card error">
              <div className="stat-value">{stats.error}</div>
              <div className="stat-label">失败</div>
            </div>
          </div>

          <div className="recent-progress">
            <h5>最近处理</h5>
            {stats.recent.length === 0 && (
              <div className="settings-empty">暂无处理记录</div>
            )}
            <ul>
              {stats.recent.map((p, i) => (
                <li key={i} className={`progress-row ${p.status}`}>
                  <span className="progress-icon">
                    {p.status === "done" ? "✅" : p.status === "error" ? "❌" : p.status === "processing" ? "🔄" : "⏳"}
                  </span>
                  <span className="progress-name" title={p.path}>
                    {p.path.split("\\").pop() || p.path}
                  </span>
                  {p.detail && <span className="progress-detail">{p.detail}</span>}
                </li>
              ))}
            </ul>
          </div>

          <button
            className="settings-save-btn"
            onClick={handleReindex}
            disabled={reindexing}
            style={{ marginTop: "1rem" }}
          >
            {reindexing && <span className="settings-spinner" />}
            {reindexing ? "分析中..." : "🔄 手动分析全部文件"}
          </button>
        </div>
      )}
    </div>
  );
}
