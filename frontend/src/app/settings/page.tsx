"use client";

import { useCallback, useEffect, useState } from "react";
import { getLLMSettings, testLLMSettings, updateLLMSettings } from "@/lib/api";
import type { LLMConnectionTestResponse, LLMSettingsResponse } from "@/lib/types";

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<LLMSettingsResponse | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [thinkingModel, setThinkingModel] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("medium");
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [adminToken, setAdminToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<LLMConnectionTestResponse | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const applySettings = useCallback((data: LLMSettingsResponse) => {
    setSettings(data);
    setBaseUrl(data.base_url || "");
    setThinkingModel(data.thinking_model || "");
    setReasoningEffort(data.reasoning_effort || "medium");
    setApiKey("");
    setClearApiKey(false);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      applySettings(await getLLMSettings());
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setLoading(false);
    }
  }, [applySettings]);

  useEffect(() => {
    load();
  }, [load]);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const data = await updateLLMSettings(
        {
          base_url: baseUrl,
          thinking_model: thinkingModel,
          reasoning_effort: reasoningEffort,
          api_key: apiKey,
          clear_api_key: clearApiKey,
        },
        adminToken,
      );
      applySettings(data);
      setMessage("LLM 配置已保存，后续解读任务会使用新配置。");
      setTestResult(null);
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setSaving(false);
    }
  }, [adminToken, apiKey, applySettings, baseUrl, clearApiKey, reasoningEffort, thinkingModel]);

  const testConnection = useCallback(async () => {
    setTesting(true);
    try {
      const data = await testLLMSettings(
        {
          base_url: baseUrl,
          thinking_model: thinkingModel,
          reasoning_effort: reasoningEffort,
          api_key: apiKey,
          clear_api_key: clearApiKey,
          use_saved_api_key: !apiKey,
        },
        adminToken,
      );
      setTestResult(data);
      setMessage(data.ok ? "LLM 连接测试通过。" : "LLM 连接测试失败。");
      setError("");
    } catch (err) {
      setTestResult(null);
      setError(errMessage(err));
    } finally {
      setTesting(false);
    }
  }, [adminToken, apiKey, baseUrl, clearApiKey, reasoningEffort, thinkingModel]);

  return (
    <div className="mx-auto max-w-4xl px-5 py-8">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">系统设置</h1>
          <p className="mt-1 text-sm text-muted-foreground">修改 LLM 接口、模型列表和密钥。</p>
        </div>
        <button onClick={load} className="rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-muted">
          刷新
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {message && <p className="mb-4 rounded-lg border border-primary/25 bg-primary/10 px-3 py-2 text-sm text-primary">{message}</p>}

      {loading ? (
        <div className="py-16 text-center text-sm text-muted-foreground">加载中...</div>
      ) : (
        <section className="rounded-xl border border-border bg-card p-5 soft-shadow">
          <div className="mb-5 flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span className="rounded-full border border-border bg-background px-2 py-1">来源：{settings?.source === "runtime" ? "网页配置" : ".env"}</span>
            <span className="rounded-full border border-border bg-background px-2 py-1">
              密钥：{settings?.api_key_configured ? `已配置，末尾 ${settings.api_key_suffix}` : "未配置"}
            </span>
            <span className="rounded-full border border-border bg-background px-2 py-1">
              默认模型：{settings?.default || "-"}
            </span>
            <span className="rounded-full border border-border bg-background px-2 py-1">
              思考等级：{settings?.reasoning_effort || "medium"}
            </span>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-1.5">
              <span className="text-sm font-medium">LLM Base URL</span>
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://example.com/v1"
                className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
              />
            </label>

            <label className="grid gap-1.5">
              <span className="text-sm font-medium">模型列表</span>
              <input
                value={thinkingModel}
                onChange={(event) => setThinkingModel(event.target.value)}
                placeholder="gpt-4.1,gpt-4.1-mini"
                className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
              />
              <span className="text-xs text-muted-foreground">多个模型用英文逗号分隔，第一个作为默认模型。</span>
            </label>

            <label className="grid gap-1.5">
              <span className="text-sm font-medium">思考等级</span>
              <select
                value={reasoningEffort}
                onChange={(event) => setReasoningEffort(event.target.value)}
                className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                {(settings?.reasoning_efforts?.length ? settings.reasoning_efforts : ["none", "minimal", "low", "medium", "high", "xhigh"]).map((effort) => (
                  <option key={effort} value={effort}>{effort}</option>
                ))}
              </select>
              <span className="text-xs text-muted-foreground">用于 Responses API 的 reasoning.effort，例如 gpt-5.5 可设为 xhigh。</span>
            </label>

            <label className="grid gap-1.5">
              <span className="text-sm font-medium">API Key</span>
              <input
                value={apiKey}
                onChange={(event) => {
                  setApiKey(event.target.value);
                  if (event.target.value) setClearApiKey(false);
                }}
                placeholder={settings?.api_key_configured ? "留空表示保留现有密钥" : "输入新的 API Key"}
                type="password"
                className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
              />
            </label>

            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={clearApiKey}
                onChange={(event) => {
                  setClearApiKey(event.target.checked);
                  if (event.target.checked) setApiKey("");
                }}
              />
              清空当前 API Key
            </label>

            <label className="grid gap-1.5">
              <span className="text-sm font-medium">管理员 Token</span>
              <input
                value={adminToken}
                onChange={(event) => setAdminToken(event.target.value)}
                type="password"
                placeholder="仅在 ADMIN_API_TOKEN 已配置时需要"
                className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
              />
            </label>
          </div>

          {testResult && (
            <div
              className={`mt-5 rounded-lg border px-3 py-2 text-sm ${
                testResult.ok
                  ? "border-success/25 bg-success/10 text-success"
                  : "border-destructive/25 bg-destructive/10 text-destructive"
              }`}
            >
              <div className="font-medium">{testResult.ok ? "连接正常" : "连接失败"}</div>
              <div className="mt-1 text-xs leading-5">
                <span>模型：{testResult.model || "-"}</span>
                <span className="mx-2">/</span>
                <span>路径：{testResult.endpoint || "-"}</span>
                <span className="mx-2">/</span>
                <span>状态：{testResult.status_code || "-"}</span>
                <span className="mx-2">/</span>
                <span>耗时：{testResult.elapsed_ms || 0} ms</span>
              </div>
              {(testResult.message || testResult.error) && (
                <p className="mt-1 whitespace-pre-wrap text-xs leading-5">{testResult.message || testResult.error}</p>
              )}
            </div>
          )}

          <div className="mt-5 flex justify-end gap-2">
            <button
              onClick={testConnection}
              disabled={testing || saving}
              className="rounded-lg border border-border px-4 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-50"
            >
              {testing ? "测试中" : "测试连接"}
            </button>
            <button
              onClick={save}
              disabled={saving || testing}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-50"
            >
              {saving ? "保存中" : "保存配置"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
