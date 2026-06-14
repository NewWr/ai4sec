"use client";

import { useState } from "react";

export type ExportItem = {
  id: string;
  label: string;
  description?: string;
  filename: string;
  mime: string;
  emptyMessage: string;
  load: () => Promise<string>;
};

type ExportResult = {
  item: ExportItem;
  content: string;
};

type ExportPanelProps = {
  title?: string;
  items: ExportItem[];
  onError?: (message: string) => void;
};

async function copyToClipboard(text: string): Promise<boolean> {
  if (!text.trim()) return false;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the textarea fallback.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(textarea);
  }
}

function downloadText(item: ExportItem, content: string) {
  const blob = new Blob([content], { type: item.mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = item.filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function sizeText(content: string): string {
  return `${content.length.toLocaleString()} 字符`;
}

export function ExportPanel({ title = "导出与复制", items, onError }: ExportPanelProps) {
  const [loadingId, setLoadingId] = useState("");
  const [result, setResult] = useState<ExportResult | null>(null);
  const [message, setMessage] = useState("");

  const runExport = async (item: ExportItem) => {
    setLoadingId(item.id);
    setMessage(`正在生成 ${item.label}...`);
    onError?.("");
    try {
      const content = await item.load();
      setResult({ item, content });
      if (!content.trim()) {
        setMessage(item.emptyMessage);
        return;
      }
      const copied = await copyToClipboard(content);
      setMessage(copied ? `已复制 ${item.label}，${sizeText(content)}。` : `已生成 ${item.label}，可在下方手动复制。`);
    } catch (err) {
      const text = err instanceof Error ? err.message : String(err);
      setResult(null);
      setMessage("导出失败。");
      onError?.(text);
    } finally {
      setLoadingId("");
    }
  };

  const copyCurrent = async () => {
    if (!result?.content.trim()) return;
    const copied = await copyToClipboard(result.content);
    setMessage(copied ? `已复制 ${result.item.label}，${sizeText(result.content)}。` : "浏览器未允许自动复制，请手动选择下方内容复制。");
  };

  const downloadCurrent = () => {
    if (!result?.content.trim()) return;
    downloadText(result.item, result.content);
    setMessage(`已下载 ${result.item.filename}。`);
  };

  return (
    <section className="mb-5 surface-card p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-sm font-semibold">{title}</h2>
        {message && <span className="text-xs text-muted-foreground" aria-live="polite">{message}</span>}
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => {
          const loading = loadingId === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => runExport(item)}
              disabled={Boolean(loadingId)}
              className="min-h-16 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-55"
            >
              <span className="block text-sm font-medium">{loading ? "生成中" : `复制 ${item.label}`}</span>
              {item.description && <span className="mt-1 block text-xs leading-5 text-muted-foreground">{item.description}</span>}
            </button>
          );
        })}
      </div>

      {result && (
        <div className="mt-4 rounded-lg border border-border bg-background p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="mr-auto text-xs text-muted-foreground">
              当前内容：{result.item.label}{result.content ? ` / ${sizeText(result.content)}` : ""}
            </span>
            <button
              type="button"
              onClick={copyCurrent}
              disabled={!result.content.trim()}
              className="btn btn-outline btn-sm"
            >
              复制当前内容
            </button>
            <button
              type="button"
              onClick={downloadCurrent}
              disabled={!result.content.trim()}
              className="btn btn-outline btn-sm"
            >
              下载文件
            </button>
            <button
              type="button"
              onClick={() => {
                setResult(null);
                setMessage("");
              }}
              className="btn btn-outline btn-sm"
            >
              清空
            </button>
          </div>
          {result.content.trim() ? (
            <textarea
              readOnly
              value={result.content}
              className="min-h-52 w-full resize-y rounded-lg border border-border bg-card px-3 py-2 font-mono text-xs leading-5 outline-none"
              spellCheck={false}
            />
          ) : (
            <p className="rounded-lg border border-border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
              {result.item.emptyMessage}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
