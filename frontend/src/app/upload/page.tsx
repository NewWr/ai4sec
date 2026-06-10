"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  confirmPaperCollection,
  createRun,
  listModels,
  suggestPaperCollection,
  uploadPaper,
} from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import type {
  PaperCollection,
  PaperCollectionSuggestResponse,
  ReadingMode,
} from "@/lib/types";
import {
  IconArrowRight,
  IconCheck,
  IconLens,
  IconSparkles,
  IconSphere,
  IconSnap,
  IconUpload,
} from "@/components/icons";
import RecentRuns from "@/components/RecentRuns";
import type { ComponentType } from "react";

const MODE_KEYS: {
  value: ReadingMode;
  labelKey: string;
  descKey: string;
  Icon: ComponentType<{ className?: string }>;
}[] = [
  { value: "snap", labelKey: "upload.mode.snap.label", descKey: "upload.mode.snap.desc", Icon: IconSnap },
  { value: "lens", labelKey: "upload.mode.lens.label", descKey: "upload.mode.lens.desc", Icon: IconLens },
  { value: "sphere", labelKey: "upload.mode.sphere.label", descKey: "upload.mode.sphere.desc", Icon: IconSphere },
  { value: "auto", labelKey: "upload.mode.auto.label", descKey: "upload.mode.auto.desc", Icon: IconSparkles },
];

type OutputLanguage = "en" | "zh";
type UploadStep = "select" | "classify" | "analyze";
type CollectionChoice = "existing" | "new";

export default function UploadPage() {
  const router = useRouter();
  const { t, locale } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [paperId, setPaperId] = useState("");
  const [step, setStep] = useState<UploadStep>("select");
  const [suggestion, setSuggestion] = useState<PaperCollectionSuggestResponse | null>(null);
  const [choice, setChoice] = useState<CollectionChoice>("existing");
  const [selectedCollectionId, setSelectedCollectionId] = useState("");
  const [newName, setNewName] = useState("");
  const [newNameZh, setNewNameZh] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newDescriptionZh, setNewDescriptionZh] = useState("");
  const [mode, setMode] = useState<ReadingMode>("snap");
  const [question, setQuestion] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [outputLanguage, setOutputLanguage] = useState<OutputLanguage>(locale);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listModels()
      .then((res) => {
        if (cancelled) return;
        setModels(res.models);
        setLlmModel(res.default || res.models[0] || "");
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      })
      .finally(() => {
        if (!cancelled) setModelsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const collections = suggestion?.collections || [];
  const visibleCollections = useMemo(
    () => collections.filter((item) => item.collection_id !== "unclassified"),
    [collections],
  );

  const applySuggestion = useCallback((data: PaperCollectionSuggestResponse) => {
    setSuggestion(data);
    const suggested = data.suggestion;
    if (suggested.mode === "existing" && suggested.collection_id) {
      setChoice("existing");
      setSelectedCollectionId(suggested.collection_id);
    } else {
      setChoice("new");
      setSelectedCollectionId("");
    }
    setNewName(suggested.new_name || "");
    setNewNameZh(suggested.new_name_zh || suggested.new_name || "");
    setNewDescription(suggested.new_description || "");
    setNewDescriptionZh(suggested.new_description_zh || suggested.new_description || "");
  }, []);

  const selectFile = useCallback((nextFile: File) => {
    setFile(nextFile);
    setPaperId("");
    setStep("select");
    setSuggestion(null);
    setChoice("existing");
    setSelectedCollectionId("");
    setNewName("");
    setNewNameZh("");
    setNewDescription("");
    setNewDescriptionZh("");
    setError(null);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped?.type === "application/pdf") {
      selectFile(dropped);
    } else {
      setError(t("upload.drop_error"));
    }
  }, [selectFile, t]);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      selectFile(selected);
      e.target.value = "";
    }
  }, [selectFile]);

  const handleUploadAndClassify = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setStep("classify");
    try {
      const uploadRes = await uploadPaper(file);
      setPaperId(uploadRes.paper_id);
      const data = await suggestPaperCollection(uploadRes.paper_id, llmModel);
      applySuggestion(data);
      setStep("analyze");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("upload.fail"));
      setStep("select");
    } finally {
      setBusy(false);
    }
  }, [applySuggestion, file, llmModel, t]);

  const handleConfirmAndRun = useCallback(async () => {
    if (!paperId) return;
    if (mode === "auto" && !question.trim()) {
      setError(t("upload.question_required"));
      return;
    }
    if (choice === "existing" && !selectedCollectionId) {
      setError("请选择一个收纳结构。");
      return;
    }
    if (choice === "new" && !newName.trim() && !newNameZh.trim()) {
      setError("请输入新结构名称。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await confirmPaperCollection(paperId, choice === "existing"
        ? { collection_id: selectedCollectionId }
        : {
            new_name: newName.trim() || newNameZh.trim(),
            new_name_zh: newNameZh.trim() || newName.trim(),
            new_description: newDescription.trim(),
            new_description_zh: newDescriptionZh.trim(),
          });
      const runRes = await createRun({
        paper_id: paperId,
        mode,
        llm_model: llmModel,
        language: outputLanguage,
        question: mode === "auto" ? question.trim() : "",
      });
      router.push(`/paper/${paperId}/run/${runRes.run_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("upload.fail"));
      setBusy(false);
    }
  }, [
    choice,
    llmModel,
    mode,
    newDescription,
    newDescriptionZh,
    newName,
    newNameZh,
    outputLanguage,
    paperId,
    question,
    router,
    selectedCollectionId,
    t,
  ]);

  const handleConfirmAndOpenWorkspace = useCallback(async () => {
    if (!paperId) return;
    if (choice === "existing" && !selectedCollectionId) {
      setError("请选择一个收纳结构。");
      return;
    }
    if (choice === "new" && !newName.trim() && !newNameZh.trim()) {
      setError("请输入新结构名称。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await confirmPaperCollection(paperId, choice === "existing"
        ? { collection_id: selectedCollectionId }
        : {
            new_name: newName.trim() || newNameZh.trim(),
            new_name_zh: newNameZh.trim() || newName.trim(),
            new_description: newDescription.trim(),
            new_description_zh: newDescriptionZh.trim(),
          });
      router.push(`/papers#paper-${paperId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("upload.fail"));
      setBusy(false);
    }
  }, [
    choice,
    newDescription,
    newDescriptionZh,
    newName,
    newNameZh,
    paperId,
    router,
    selectedCollectionId,
    t,
  ]);

  const langBtn = (value: OutputLanguage, label: string) => (
    <button
      onClick={() => setOutputLanguage(value)}
      className={`rounded-lg border p-3 text-center text-sm font-medium transition-colors ${
        outputLanguage === value
          ? "border-primary bg-accent text-accent-foreground"
          : "border-border hover:border-foreground/20"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <header className="mb-6">
        <h1 className="font-display text-3xl font-semibold tracking-tight">{t("upload.title")}</h1>
      </header>

      <RecentRuns />

      <StepBar step={step} />

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`mb-6 cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragOver
            ? "border-primary bg-accent"
            : file
              ? "border-primary/40 bg-card"
              : "border-border bg-card hover:border-foreground/20"
        }`}
        onClick={() => document.getElementById("file-input")?.click()}
      >
        <input
          id="file-input"
          type="file"
          accept=".pdf"
          onChange={handleFileChange}
          className="hidden"
          disabled={busy}
        />
        <span
          className={`mx-auto flex h-12 w-12 items-center justify-center rounded-xl text-2xl ${
            file ? "bg-accent text-primary" : "bg-muted text-muted-foreground"
          }`}
        >
          {file ? <IconCheck /> : <IconUpload />}
        </span>
        {file ? (
          <div className="mt-4">
            <p className="break-words font-medium">{file.name}</p>
            <p className="text-sm text-muted-foreground">
              {(file.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
        ) : (
          <div className="mt-4">
            <p className="font-medium">{t("upload.drop")}</p>
            <p className="mt-1 text-sm text-muted-foreground">{t("upload.supports")}</p>
          </div>
        )}
      </div>

      {step === "select" && (
        <button
          onClick={handleUploadAndClassify}
          disabled={!file || busy}
          className="mb-8 flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-primary"
        >
          {busy && <Spinner />}
          {busy ? "正在解析并推荐结构..." : "上传并推荐收纳结构"}
        </button>
      )}

      {step === "classify" && (
        <div className="mb-8 rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
          <div className="mb-3 flex items-center gap-2 text-foreground">
            <Spinner />
            <span className="font-medium">正在解析论文并生成结构推荐</span>
          </div>
          <p>这一步会读取论文标题、摘要和早期正文，完成后需要确认纳入哪个收纳结构。</p>
        </div>
      )}

      {step === "analyze" && suggestion && (
        <>
          <CollectionConfirmPanel
            data={suggestion}
            collections={visibleCollections.length ? visibleCollections : collections}
            choice={choice}
            selectedCollectionId={selectedCollectionId}
            newName={newName}
            newNameZh={newNameZh}
            newDescription={newDescription}
            newDescriptionZh={newDescriptionZh}
            onChoiceChange={setChoice}
            onSelectedCollectionChange={setSelectedCollectionId}
            onNewNameChange={setNewName}
            onNewNameZhChange={setNewNameZh}
            onNewDescriptionChange={setNewDescription}
            onNewDescriptionZhChange={setNewDescriptionZh}
          />

          <AnalysisOptions
            mode={mode}
            question={question}
            outputLanguage={outputLanguage}
            models={models}
            modelsLoaded={modelsLoaded}
            llmModel={llmModel}
            setMode={setMode}
            setQuestion={setQuestion}
            setLlmModel={setLlmModel}
            langBtn={langBtn}
            t={t}
          />

          {error && <ErrorBox message={error} />}

          <div className="grid gap-2 sm:grid-cols-2">
            <button
              onClick={handleConfirmAndOpenWorkspace}
              disabled={busy}
              className="flex items-center justify-center gap-2 rounded-xl border border-border py-3.5 font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy && <Spinner />}
              确认并进入论文工作台
            </button>
            <button
              onClick={handleConfirmAndRun}
              disabled={busy}
              className="flex items-center justify-center gap-2 rounded-xl bg-primary py-3.5 font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-primary"
            >
              {busy && <Spinner />}
              {busy ? t("upload.submitting") : t("upload.submit")}
              {!busy && <IconArrowRight />}
            </button>
          </div>
        </>
      )}

      {step !== "analyze" && error && <ErrorBox message={error} />}
    </div>
  );
}

function StepBar({ step }: { step: UploadStep }) {
  const steps = [
    ["select", "选择 PDF"],
    ["classify", "结构归纳"],
    ["analyze", "确认并分析"],
  ] as const;
  const activeIdx = steps.findIndex(([key]) => key === step);
  return (
    <div className="mb-6 grid grid-cols-3 gap-2 text-xs">
      {steps.map(([key, label], idx) => (
        <div
          key={key}
          className={`rounded-lg border px-3 py-2 text-center ${
            idx <= activeIdx
              ? "border-primary/30 bg-accent text-accent-foreground"
              : "border-border bg-card text-muted-foreground"
          }`}
        >
          {idx + 1}. {label}
        </div>
      ))}
    </div>
  );
}

function CollectionConfirmPanel({
  data,
  collections,
  choice,
  selectedCollectionId,
  newName,
  newNameZh,
  newDescription,
  newDescriptionZh,
  onChoiceChange,
  onSelectedCollectionChange,
  onNewNameChange,
  onNewNameZhChange,
  onNewDescriptionChange,
  onNewDescriptionZhChange,
}: {
  data: PaperCollectionSuggestResponse;
  collections: PaperCollection[];
  choice: CollectionChoice;
  selectedCollectionId: string;
  newName: string;
  newNameZh: string;
  newDescription: string;
  newDescriptionZh: string;
  onChoiceChange: (choice: CollectionChoice) => void;
  onSelectedCollectionChange: (id: string) => void;
  onNewNameChange: (value: string) => void;
  onNewNameZhChange: (value: string) => void;
  onNewDescriptionChange: (value: string) => void;
  onNewDescriptionZhChange: (value: string) => void;
}) {
  const confidence = Math.round((data.suggestion.confidence || 0) * 100);
  return (
    <section className="mb-8 rounded-xl border border-border bg-card p-5">
      <div className="mb-4">
        <h2 className="text-base font-semibold">确认论文收纳结构</h2>
        <p className="mt-1 break-words text-sm text-muted-foreground">
          {data.paper_title_zh || data.paper_title}
        </p>
        {data.summary_zh && (
          <p className="mt-3 text-sm leading-6 text-muted-foreground">{data.summary_zh}</p>
        )}
      </div>

      <div className="mb-4 rounded-lg border border-border bg-muted/35 px-3 py-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">系统推荐</span>
          <span className="rounded-full bg-background px-2 py-0.5 text-xs text-muted-foreground">
            {confidence}%
          </span>
        </div>
        {data.suggestion.reason && (
          <p className="mt-1 text-muted-foreground">{data.suggestion.reason}</p>
        )}
      </div>

      <div className="mb-4 grid gap-2 sm:grid-cols-2">
        <button
          onClick={() => onChoiceChange("existing")}
          className={`rounded-lg border p-3 text-left text-sm ${
            choice === "existing" ? "border-primary bg-accent" : "border-border hover:bg-muted"
          }`}
        >
          纳入已有结构
        </button>
        <button
          onClick={() => onChoiceChange("new")}
          className={`rounded-lg border p-3 text-left text-sm ${
            choice === "new" ? "border-primary bg-accent" : "border-border hover:bg-muted"
          }`}
        >
          新建结构
        </button>
      </div>

      {choice === "existing" ? (
        <select
          value={selectedCollectionId}
          onChange={(e) => onSelectedCollectionChange(e.target.value)}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
        >
          <option value="">选择收纳结构</option>
          {collections.map((item) => (
            <option key={item.collection_id} value={item.collection_id}>
              {item.name_zh || item.name} · {item.paper_count}
            </option>
          ))}
        </select>
      ) : (
        <div className="grid gap-3">
          <input
            value={newNameZh}
            onChange={(e) => onNewNameZhChange(e.target.value)}
            placeholder="中文结构名称"
            className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
          />
          <input
            value={newName}
            onChange={(e) => onNewNameChange(e.target.value)}
            placeholder="English name"
            className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
          />
          <textarea
            value={newDescriptionZh}
            onChange={(e) => onNewDescriptionZhChange(e.target.value)}
            placeholder="中文结构说明"
            rows={2}
            className="resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm"
          />
          <textarea
            value={newDescription}
            onChange={(e) => onNewDescriptionChange(e.target.value)}
            placeholder="English description"
            rows={2}
            className="resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm"
          />
        </div>
      )}
    </section>
  );
}

function AnalysisOptions({
  mode,
  question,
  outputLanguage,
  models,
  modelsLoaded,
  llmModel,
  setMode,
  setQuestion,
  setLlmModel,
  langBtn,
  t,
}: {
  mode: ReadingMode;
  question: string;
  outputLanguage: OutputLanguage;
  models: string[];
  modelsLoaded: boolean;
  llmModel: string;
  setMode: (mode: ReadingMode) => void;
  setQuestion: (value: string) => void;
  setLlmModel: (value: string) => void;
  langBtn: (value: OutputLanguage, label: string) => React.ReactNode;
  t: (key: string) => string;
}) {
  return (
    <section className="mb-8 rounded-xl border border-border bg-card p-5">
      <div className="mb-5">
        <label className="mb-3 block text-sm font-semibold">{t("upload.mode_label")}</label>
        <div className="grid gap-3 sm:grid-cols-2">
          {MODE_KEYS.map((m) => {
            const selected = mode === m.value;
            return (
              <button
                key={m.value}
                onClick={() => setMode(m.value)}
                className={`relative rounded-lg border p-4 text-left transition-colors ${
                  selected ? "border-primary bg-accent" : "border-border hover:border-foreground/20"
                }`}
              >
                {selected && (
                  <span className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground">
                    <IconCheck />
                  </span>
                )}
                <span className={`flex h-9 w-9 items-center justify-center rounded-lg text-lg ${
                  selected ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
                }`}>
                  <m.Icon />
                </span>
                <p className="mt-3 text-sm font-medium">{t(m.labelKey)}</p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t(m.descKey)}</p>
              </button>
            );
          })}
        </div>
      </div>

      {mode === "auto" && (
        <div className="mb-5">
          <label className="mb-2 block text-sm font-semibold">{t("upload.question_label")}</label>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t("upload.question_placeholder")}
            rows={3}
            maxLength={2000}
            className="min-h-[88px] w-full resize-y rounded-lg border border-border bg-background px-4 py-3 text-sm transition-colors placeholder:text-muted-foreground/70 focus:border-primary focus:outline-none"
          />
        </div>
      )}

      <div className="mb-5">
        <label className="mb-3 block text-sm font-semibold">{t("upload.language_label")}</label>
        <div className="grid gap-3 sm:grid-cols-2">
          {langBtn("en", "English")}
          {langBtn("zh", "中文")}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{t("upload.language_note")}</p>
      </div>

      <div>
        <label className="mb-2 block text-sm font-semibold">{t("upload.model_label")}</label>
        {modelsLoaded && models.length === 0 ? (
          <p className="rounded-lg border border-border bg-background px-4 py-3 text-sm text-muted-foreground">
            {t("upload.model_empty")}
          </p>
        ) : (
          <select
            value={llmModel}
            onChange={(e) => setLlmModel(e.target.value)}
            disabled={!modelsLoaded || models.length === 0}
            className="w-full rounded-lg border border-border bg-background px-4 py-3 text-sm transition-colors focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
          >
            {!modelsLoaded ? (
              <option value="">{t("upload.model_loading")}</option>
            ) : (
              models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))
            )}
          </select>
        )}
      </div>
    </section>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="mb-5 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
      {message}
    </div>
  );
}

function Spinner() {
  return <span className="h-4 w-4 animate-spin rounded-full border-2 border-current/30 border-t-current" />;
}
