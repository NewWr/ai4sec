"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createKnowledgeCard,
  createWritingSnippet,
  getLibraryStatus,
  listLibraryDatasets,
  listLibraryDocuments,
  getLibraryMarkdown,
  localLibrarySearch,
  searchLibrary,
  askLibrary,
} from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import MarkdownRenderer from "@/components/MarkdownRenderer";
import LibraryDocumentPreview from "@/components/LibraryDocumentPreview";
import SplitPane from "@/components/SplitPane";
import type {
  LibraryDocument,
  LibrarySearchRecord,
  LibraryAskResponse,
  LocalSearchMode,
  LocalSearchResult,
  SearchMethod,
} from "@/lib/types";

const METHODS: SearchMethod[] = ["keyword_search", "full_text_search", "semantic_search", "hybrid_search"];

function fmtScore(score: number | null | undefined): string | null {
  return typeof score === "number" && score > 0 ? score.toFixed(3) : null;
}

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function LibraryPage() {
  const { t, locale } = useTranslation();

  const [tab, setTab] = useState<"search" | "ask">("search");
  const [searchScope, setSearchScope] = useState<"dify" | LocalSearchMode>("dify");
  const [method, setMethod] = useState<SearchMethod>("keyword_search");
  const [libraryEnabled, setLibraryEnabled] = useState<boolean | null>(null);
  const [error, setError] = useState<string>("");
  const [actionMessage, setActionMessage] = useState("");
  const [datasets, setDatasets] = useState<Array<{ id: string; name: string }>>([]);
  const [datasetId, setDatasetId] = useState("");

  // Search
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LibrarySearchRecord[]>([]);
  const [localResults, setLocalResults] = useState<LocalSearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);

  // Ask
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<LibraryAskResponse | null>(null);
  const [asking, setAsking] = useState(false);

  // Browse documents
  const [docs, setDocs] = useState<LibraryDocument[]>([]);
  const [docsPage, setDocsPage] = useState(0);
  const [docsHasMore, setDocsHasMore] = useState(false);
  const [docsLoading, setDocsLoading] = useState(false);

  // Right-pane document preview
  const [selectedName, setSelectedName] = useState("");
  const [docContent, setDocContent] = useState("");
  const [docLoading, setDocLoading] = useState(false);

  const loadDocs = useCallback(
    async (page: number) => {
      setDocsLoading(true);
      try {
        const res = await listLibraryDocuments({ datasetId: datasetId || undefined, page, limit: 20 });
        setDocs((prev) => (page === 1 ? res.data : [...prev, ...res.data]));
        setDocsHasMore(Boolean(res.has_more));
        setDocsPage(page);
        setError("");
      } catch (err) {
        setError(errMessage(err));
      } finally {
        setDocsLoading(false);
      }
    },
    [datasetId],
  );

  useEffect(() => {
    let cancelled = false;
    getLibraryStatus()
      .then((res) => {
        if (cancelled) return;
        setLibraryEnabled(res.enabled);
        if (METHODS.includes(res.search_method as SearchMethod)) {
          setMethod(res.search_method as SearchMethod);
        }
        if (!res.enabled) {
          setDocs([]);
          setDocsHasMore(false);
          setError("");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setLibraryEnabled(null);
        setError(errMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!libraryEnabled) return;
    listLibraryDatasets(1, 100)
      .then((res) => {
        const data = (res.data || []).map((d) => ({ id: d.id, name: d.name }));
        setDatasets(data);
        if (!datasetId && data.length > 0) setDatasetId(data[0].id);
      })
      .catch((err) => setError(errMessage(err)));
  }, [libraryEnabled, datasetId]);

  useEffect(() => {
    if (libraryEnabled) {
      setDocs([]);
      setDocContent("");
      setSelectedName("");
      loadDocs(1);
    }
  }, [libraryEnabled, datasetId, loadDocs]);

  const openDoc = useCallback(async (documentId: string, name: string) => {
    if (!documentId) return;
    if (libraryEnabled !== true) {
      if (libraryEnabled === false) setError(t("library.disabled"));
      return;
    }
    setDocLoading(true);
    setSelectedName(name);
    try {
      const res = await getLibraryMarkdown(documentId, datasetId || undefined);
      setDocContent(res.content || "");
      if (!name && res.document_name) setSelectedName(res.document_name);
      setError("");
    } catch (err) {
      setDocContent("");
      setError(errMessage(err));
    } finally {
      setDocLoading(false);
    }
  }, [datasetId, libraryEnabled, t]);

  // Deep link: /library?doc=<document_id> (e.g. from a Research Sphere report)
  // opens that document in the preview pane. Read from the URL on the client to
  // avoid the Suspense boundary that useSearchParams would require at build.
  useEffect(() => {
    if (!libraryEnabled) return;
    const doc = new URLSearchParams(window.location.search).get("doc");
    if (doc) openDoc(doc, "");
  }, [libraryEnabled, openDoc]);

  const runSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) {
      setError(t("library.empty_query"));
      return;
    }
    if (searchScope !== "dify") {
      setSearching(true);
      setError("");
      try {
        const res = await localLibrarySearch(searchScope, q, 30);
        setLocalResults(res.results || []);
        setResults([]);
        setSearched(true);
      } catch (err) {
        setError(errMessage(err));
      } finally {
        setSearching(false);
      }
      return;
    }
    if (libraryEnabled !== true) {
      if (libraryEnabled === false) setError(t("library.disabled"));
      return;
    }
    setSearching(true);
    setError("");
    try {
      const res = await searchLibrary({ query: q, search_method: method, top_k: 20, dataset_id: datasetId });
      setResults(res.records || []);
      setLocalResults([]);
      setSearched(true);
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setSearching(false);
    }
  }, [query, method, datasetId, libraryEnabled, searchScope, t]);

  const runAsk = useCallback(async () => {
    const q = question.trim();
    if (libraryEnabled !== true) {
      if (libraryEnabled === false) setError(t("library.disabled"));
      return;
    }
    if (!q) {
      setError(t("library.empty_question"));
      return;
    }
    setAsking(true);
    setError("");
    try {
      const res = await askLibrary({
        question: q,
        search_method: method,
        language: locale,
        top_k: 10,
        dataset_id: datasetId,
      });
      setAnswer(res);
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setAsking(false);
    }
  }, [question, method, datasetId, locale, libraryEnabled, t]);

  const onLibraryCitationClick = useCallback(
    (idx: number) => {
      const src = answer?.sources.find((s) => s.idx === idx);
      if (src) openDoc(src.document_id, src.document_name);
    },
    [answer, openDoc],
  );

  const slowHint = method === "semantic_search" || method === "hybrid_search";
  const needsDify = tab === "ask" || searchScope === "dify";

  const saveLocalCard = useCallback(async (result: LocalSearchResult) => {
    if (result.result_type !== "fragment") {
      setActionMessage("该结果类型不适合直接保存为知识卡片。");
      return;
    }
    try {
      await createKnowledgeCard({
        card_type: result.result_type === "fragment" ? "claim" : "method",
        title: result.title || result.paper_title || "检索结果",
        content: result.snippet || result.title,
        paper_id: result.paper_id,
        source_page: result.page,
        source_quote: result.snippet,
        status: "draft",
        created_by: "user",
        tags: `local-search,${result.result_type}`,
      });
      setActionMessage("已保存为知识卡片。");
      setError("");
    } catch (err) {
      setError(errMessage(err));
    }
  }, []);

  const saveLocalSnippet = useCallback(async (result: LocalSearchResult) => {
    if (result.result_type === "paper" || result.result_type === "relation" || result.result_type === "writing") {
      setActionMessage("该结果类型不适合重复加入写作素材。");
      return;
    }
    try {
      await createWritingSnippet({
        content: result.snippet || result.title,
        source_card_id: typeof result.metadata.source_card_id === "string" ? result.metadata.source_card_id : "",
        paper_id: result.paper_id,
        citation_key: typeof result.metadata.citation_key === "string" ? result.metadata.citation_key : "",
        source_page: result.page,
        source_quote: result.snippet,
        section_hint: "related_work",
      });
      setActionMessage("已加入写作素材。");
      setError("");
    } catch (err) {
      setError(errMessage(err));
    }
  }, []);

  const methodSelect = (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{t("library.method_label")}</span>
      <select
        value={method}
        disabled={libraryEnabled !== true}
        onChange={(e) => setMethod(e.target.value as SearchMethod)}
        className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
      >
        {METHODS.map((m) => (
          <option key={m} value={m}>
            {t(`library.method.${m}`)}
          </option>
        ))}
      </select>
    </div>
  );

  const datasetSelect = (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{t("library.dataset_label")}</span>
      <select
        value={datasetId}
        disabled={libraryEnabled !== true || datasets.length === 0}
        onChange={(e) => setDatasetId(e.target.value)}
        className="max-w-[15rem] rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
      >
        {datasets.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <div data-library-root className="fixed inset-x-0 bottom-0 top-14 flex overflow-hidden flex-col">
      {/* Header */}
      <div className="shrink-0 border-b border-border bg-card/60 px-5 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h1 className="font-display text-lg font-semibold tracking-tight">
              {t("library.title")}
            </h1>
            <p className="truncate text-xs text-muted-foreground">{t("library.subtitle")}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1 rounded-xl border border-border bg-background p-1">
            {(["search", "ask"] as const).map((key) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  tab === key
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t(`library.tab.${key}`)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        <SplitPane
          defaultLeftWidth={48}
          left={
            <div className="flex h-full flex-col">
              {/* Controls */}
              <div className="shrink-0 space-y-2 border-b border-border px-5 py-3">
                {tab === "search" ? (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      runSearch();
                    }}
                    className="flex items-center gap-2"
                  >
                    <input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      disabled={searchScope === "dify" && libraryEnabled !== true}
                      placeholder={t("library.search_placeholder")}
                      className="min-w-0 flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/50"
                    />
                    <button
                      type="submit"
                      disabled={searching || (searchScope === "dify" && libraryEnabled !== true)}
                      className="shrink-0 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-50"
                    >
                      {searching ? t("library.searching") : t("library.run_search")}
                    </button>
                  </form>
                ) : (
                  <div className="space-y-2">
                    <textarea
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      disabled={libraryEnabled !== true}
                      onKeyDown={(e) => {
                        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                          e.preventDefault();
                          runAsk();
                        }
                      }}
                      placeholder={t("library.ask_placeholder")}
                      rows={3}
                      className="w-full resize-y rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/50"
                    />
                    <div className="flex justify-end">
                      <button
                        onClick={runAsk}
                        disabled={asking || libraryEnabled !== true}
                        className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-50"
                      >
                        {asking ? t("library.thinking") : t("library.run_ask")}
                      </button>
                    </div>
                  </div>
                )}

                <div className="flex items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-3">
                    {tab === "search" && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">模式</span>
                        <select
                          value={searchScope}
                          onChange={(e) => setSearchScope(e.target.value as "dify" | LocalSearchMode)}
                          className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
                        >
                          <option value="dify">Dify 原文</option>
                          <option value="papers">论文</option>
                          <option value="fragments">原文片段</option>
                          <option value="cards">知识卡片</option>
                          <option value="relations">关系</option>
                          <option value="writing">写作素材</option>
                        </select>
                      </div>
                    )}
                    {searchScope === "dify" && datasetSelect}
                    {searchScope === "dify" && methodSelect}
                  </div>
                  {slowHint && (
                    <span className="text-right text-xs text-muted-foreground">
                      {t("library.method_slow_hint")}
                    </span>
                  )}
                </div>

                {error && <p className="text-xs text-destructive">{error}</p>}
                {actionMessage && <p className="text-xs text-primary">{actionMessage}</p>}
              </div>

              {/* Results / answer / browse */}
              <div className="flex-1 overflow-auto px-5 py-3">
                {libraryEnabled === null && needsDify && !error ? (
                  <CenterSpinner label={t("library.searching")} />
                ) : libraryEnabled === false && needsDify ? (
                  <p className="py-10 text-center text-sm text-muted-foreground">
                    {t("library.disabled")}
                  </p>
                ) : tab === "search" ? (
                  searching ? (
                    <CenterSpinner label={t("library.searching")} />
                  ) : searched ? (
                    searchScope !== "dify" ? (
                      localResults.length === 0 ? (
                        <p className="py-10 text-center text-sm text-muted-foreground">
                          {t("library.no_results")}
                        </p>
                      ) : (
                        <div className="space-y-2">
                          <p className="px-1 text-xs text-muted-foreground">
                            {t("library.results_count", { count: localResults.length })}
                          </p>
                          {localResults.map((r) => (
                            <LocalResultCard
                              key={`${r.result_type}-${r.id}`}
                              result={r}
                              onSaveCard={saveLocalCard}
                              onSaveSnippet={saveLocalSnippet}
                            />
                          ))}
                        </div>
                      )
                    ) : results.length === 0 ? (
                      <p className="py-10 text-center text-sm text-muted-foreground">
                        {t("library.no_results")}
                      </p>
                    ) : (
                      <div className="space-y-2">
                        <p className="px-1 text-xs text-muted-foreground">
                          {t("library.results_count", { count: results.length })}
                        </p>
                        {results.map((r, i) => (
                          <ResultCard
                            key={`${r.segment_id}-${i}`}
                            name={r.document_name}
                            score={fmtScore(r.score)}
                            snippet={r.content}
                            onClick={() => openDoc(r.document_id, r.document_name)}
                          />
                        ))}
                      </div>
                    )
                  ) : (
                    <div className="space-y-2">
                      <p className="px-1 text-xs font-medium text-muted-foreground">
                        {t("library.documents")}
                      </p>
                      {docs.map((d) => (
                        <ResultCard
                          key={d.id}
                          name={d.name}
                          score={d.word_count ? `${d.word_count.toLocaleString()} w` : null}
                          onClick={() => openDoc(d.id, d.name)}
                        />
                      ))}
                      {docsHasMore && (
                        <button
                          onClick={() => loadDocs(docsPage + 1)}
                          disabled={docsLoading}
                          className="w-full rounded-lg border border-border py-2 text-sm text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
                        >
                          {docsLoading ? t("library.searching") : t("library.load_more")}
                        </button>
                      )}
                    </div>
                  )
                ) : asking ? (
                  <CenterSpinner label={t("library.thinking")} />
                ) : answer ? (
                  <div className="space-y-5">
                    <MarkdownRenderer
                      content={answer.markdown}
                      onLibraryCitationClick={onLibraryCitationClick}
                    />
                    {answer.sources.length > 0 && (
                      <div className="border-t border-border pt-3">
                        <p className="mb-2 text-xs font-medium text-muted-foreground">
                          {t("library.sources")}
                        </p>
                        <div className="space-y-1.5">
                          {answer.sources.map((s) => (
                            <button
                              key={s.idx}
                              onClick={() => openDoc(s.document_id, s.document_name)}
                              className="flex w-full items-start gap-2 rounded-lg border border-border bg-card px-3 py-2 text-left text-sm transition-colors hover:border-primary/40"
                            >
                              <span className="mt-0.5 shrink-0 font-mono text-xs text-primary">
                                L{s.idx}
                              </span>
                              <span className="min-w-0 flex-1 truncate">{s.document_name}</span>
                              {fmtScore(s.score) && (
                                <span className="shrink-0 text-xs text-muted-foreground">
                                  {fmtScore(s.score)}
                                </span>
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="py-10 text-center text-sm text-muted-foreground">
                    {t("library.select_hint")}
                  </p>
                )}
              </div>
            </div>
          }
          right={
            <div className="h-full">
              {docLoading ? (
                <CenterSpinner label={t("library.doc_loading")} />
              ) : docContent ? (
                <LibraryDocumentPreview content={docContent} title={selectedName} />
              ) : (
                <p className="flex h-full items-center justify-center px-6 text-center text-sm text-muted-foreground">
                  {t("library.select_hint")}
                </p>
              )}
            </div>
          }
        />
      </div>
    </div>
  );
}

function CenterSpinner({ label }: { label: string }) {
  return (
    <div className="flex h-full items-start justify-center py-12">
      <div className="text-center">
        <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-[3px] border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

function ResultCard({
  name,
  score,
  snippet,
  onClick,
}: {
  name: string;
  score: string | null;
  snippet?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="block w-full rounded-xl border border-border bg-card px-3.5 py-2.5 text-left transition-colors hover:border-primary/40"
    >
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1 break-words text-sm font-medium">{name}</span>
        {score && (
          <span className="shrink-0 rounded-md bg-accent px-1.5 py-0.5 font-mono text-xs text-primary">
            {score}
          </span>
        )}
      </div>
      {snippet && (
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          {snippet.trim().slice(0, 240)}
        </p>
      )}
    </button>
  );
}

function LocalResultCard({
  result,
  onSaveCard,
  onSaveSnippet,
}: {
  result: LocalSearchResult;
  onSaveCard: (result: LocalSearchResult) => void;
  onSaveSnippet: (result: LocalSearchResult) => void;
}) {
  const href = result.paper_id
    ? result.page
      ? `/paper/${result.paper_id}/run/${result.metadata.run_id || ""}`
      : `/papers#paper-${result.paper_id}`
    : "";
  const content = (
    <>
      <div className="flex items-start gap-2">
        <span className="rounded-md bg-accent px-1.5 py-0.5 text-xs text-primary">
          {result.result_type}
        </span>
        <span className="min-w-0 flex-1 break-words text-sm font-medium">{result.title}</span>
        {result.score > 0 && <span className="shrink-0 text-xs text-muted-foreground">{result.score.toFixed(2)}</span>}
      </div>
      {result.paper_title && <p className="mt-1 truncate text-xs text-muted-foreground">{result.paper_title}</p>}
      {result.snippet && <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-muted-foreground">{result.snippet}</p>}
      {result.page > 0 && <p className="mt-1 text-xs text-muted-foreground">p.{result.page}</p>}
    </>
  );
  return (
    <div className="rounded-xl border border-border bg-card px-3.5 py-2.5 transition-colors hover:border-primary/40">
      {href && !href.endsWith("/run/") ? (
        <a href={href} className="block text-left">
          {content}
        </a>
      ) : (
        <div className="text-left">{content}</div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {result.result_type === "fragment" && (
          <button
            onClick={() => onSaveCard(result)}
            className="rounded-lg border border-border px-2.5 py-1.5 text-xs transition-colors hover:bg-muted"
          >
            保存为卡片
          </button>
        )}
        {(result.result_type === "fragment" || result.result_type === "card") && (
          <button
            onClick={() => onSaveSnippet(result)}
            className="rounded-lg border border-border px-2.5 py-1.5 text-xs transition-colors hover:bg-muted"
          >
            加入素材
          </button>
        )}
      </div>
    </div>
  );
}
