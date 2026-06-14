"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { translateText } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { IconLanguages } from "@/components/icons";

type Lang = {
  code: string;
  label: string;
};

const SOURCE_LANGS: Lang[] = [
  { code: "auto", label: "自动检测" },
  { code: "en", label: "英语" },
  { code: "zh", label: "中文" },
  { code: "ja", label: "日语" },
  { code: "ko", label: "韩语" },
  { code: "fr", label: "法语" },
  { code: "de", label: "德语" },
  { code: "es", label: "西班牙语" },
  { code: "ru", label: "俄语" },
  { code: "it", label: "意大利语" },
  { code: "pt", label: "葡萄牙语" },
  { code: "nl", label: "荷兰语" },
];

const TARGET_LANGS: Lang[] = SOURCE_LANGS.filter((lang) => lang.code !== "auto");

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function TranslatePage() {
  const [sourceLang, setSourceLang] = useState("auto");
  const [targetLang, setTargetLang] = useState("zh");
  const [sourceText, setSourceText] = useState("");
  const [translatedText, setTranslatedText] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [copyState, setCopyState] = useState("");
  const [translating, setTranslating] = useState(false);
  const requestIdRef = useRef(0);

  const sourceCount = sourceText.length;
  const canTranslate = sourceText.trim().length > 0 && !translating;

  const statusText = useMemo(() => {
    if (translating) return "翻译中";
    if (error) return error;
    if (status === "done") return "已翻译";
    if (status === "failed") return "翻译失败";
    if (status === "skipped") return "已跳过";
    return "待翻译";
  }, [error, status, translating]);

  const runTranslate = useCallback(async () => {
    const text = sourceText.trim();
    if (!text) {
      setTranslatedText("");
      setStatus("");
      setError("");
      return;
    }

    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setTranslating(true);
    setError("");
    setCopyState("");

    try {
      const res = await translateText({
        text,
        source_lang: sourceLang,
        target_lang: targetLang,
      });
      if (requestIdRef.current !== requestId) return;
      setTranslatedText(res.translated_text || "");
      setStatus(res.status);
      setError(res.status === "failed" ? res.error_msg || "翻译失败" : "");
    } catch (err) {
      if (requestIdRef.current !== requestId) return;
      setTranslatedText("");
      setStatus("failed");
      setError(errMessage(err));
    } finally {
      if (requestIdRef.current === requestId) setTranslating(false);
    }
  }, [sourceLang, sourceText, targetLang]);

  useEffect(() => {
    if (!sourceText.trim()) {
      setTranslatedText("");
      setStatus("");
      setError("");
      return;
    }
    const timer = window.setTimeout(() => {
      runTranslate();
    }, 700);
    return () => window.clearTimeout(timer);
  }, [runTranslate, sourceText, sourceLang, targetLang]);

  const swapLanguages = useCallback(() => {
    if (sourceLang === "auto") return;
    setSourceLang(targetLang);
    setTargetLang(sourceLang);
    setSourceText(translatedText);
    setTranslatedText(sourceText);
    setError("");
    setCopyState("");
  }, [sourceLang, sourceText, targetLang, translatedText]);

  const clear = useCallback(() => {
    requestIdRef.current += 1;
    setSourceText("");
    setTranslatedText("");
    setStatus("");
    setError("");
    setCopyState("");
    setTranslating(false);
  }, []);

  const copyTranslated = useCallback(async () => {
    if (!translatedText) return;
    await navigator.clipboard.writeText(translatedText);
    setCopyState("已复制");
    window.setTimeout(() => setCopyState(""), 1200);
  }, [translatedText]);

  return (
    <div className="min-h-[calc(100vh-3.5rem)] px-4 py-6 sm:px-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <PageHeader
          icon={IconLanguages}
          title="在线翻译"
          subtitle="使用当前工作站配置的 DeepLX 服务翻译文本。"
          actions={
            <span className="chip">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  translating
                    ? "bg-primary pulse-dot"
                    : status === "failed"
                      ? "bg-destructive"
                      : status === "done"
                        ? "bg-success"
                        : "bg-muted-foreground"
                }`}
              />
              {statusText}
            </span>
          }
        />

        <section className="surface-card soft-shadow">
          <div className="grid gap-0 lg:grid-cols-[1fr_auto_1fr]">
            <div className="flex min-h-[620px] flex-col">
              <div className="flex h-14 items-center gap-3 border-b border-border px-4">
                <select
                  value={sourceLang}
                  onChange={(event) => setSourceLang(event.target.value)}
                  className="h-9 field"
                  aria-label="源语言"
                >
                  {SOURCE_LANGS.map((lang) => (
                    <option key={lang.code} value={lang.code}>
                      {lang.label}
                    </option>
                  ))}
                </select>
                <div className="flex-1" />
                <span className="text-xs text-muted-foreground">{sourceCount.toLocaleString()} 字符</span>
                <button
                  type="button"
                  onClick={clear}
                  className="btn btn-ghost btn-sm"
                >
                  清空
                </button>
              </div>
              <textarea
                value={sourceText}
                onChange={(event) => setSourceText(event.target.value)}
                placeholder="输入或粘贴要翻译的文本"
                className="min-h-0 flex-1 resize-none bg-transparent p-4 text-base leading-7 outline-none placeholder:text-muted-foreground/70"
                spellCheck={false}
              />
            </div>

            <div className="flex items-center justify-center border-y border-border px-3 py-2 lg:border-x lg:border-y-0">
              <button
                type="button"
                onClick={swapLanguages}
                disabled={sourceLang === "auto"}
                className="btn btn-outline btn-sm w-16"
                title={sourceLang === "auto" ? "自动检测源语言时不能交换" : "交换语言"}
              >
                交换
              </button>
            </div>

            <div className="flex min-h-[620px] flex-col">
              <div className="flex h-14 items-center gap-3 border-b border-border px-4">
                <select
                  value={targetLang}
                  onChange={(event) => setTargetLang(event.target.value)}
                  className="h-9 field"
                  aria-label="目标语言"
                >
                  {TARGET_LANGS.map((lang) => (
                    <option key={lang.code} value={lang.code}>
                      {lang.label}
                    </option>
                  ))}
                </select>
                <div className="flex-1" />
                <button
                  type="button"
                  onClick={runTranslate}
                  disabled={!canTranslate}
                  className="btn btn-primary btn-sm"
                >
                  {translating ? "翻译中" : "翻译"}
                </button>
                <button
                  type="button"
                  onClick={copyTranslated}
                  disabled={!translatedText}
                  className="btn btn-ghost btn-sm"
                >
                  {copyState || "复制"}
                </button>
              </div>
              <div className="min-h-0 flex-1 whitespace-pre-wrap p-4 text-base leading-7">
                {translatedText || (
                  <span className="text-muted-foreground/70">
                    译文会显示在这里
                  </span>
                )}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
