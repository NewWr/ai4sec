"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  buildComparisonTable,
  composeRelatedWork,
  exportObsidianMarkdown,
  exportPapersBibtex,
  exportPapersRis,
  exportPapersZoteroCslJson,
  exportWritingMarkdown,
  listKnowledgeCards,
  listPapers,
  listWritingSnippets,
} from "@/lib/api";
import type { ComparisonTableResponse, KnowledgeCard, PaperLibraryItem, SectionHint, WritingSnippet } from "@/lib/types";

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function paperTitle(paper: PaperLibraryItem): string {
  return paper.display?.title_zh || paper.title || paper.paper_id;
}

function paperMeta(paper: PaperLibraryItem): string {
  return [
    paper.venue,
    paper.year || "",
    paper.citation_key ? `@${paper.citation_key}` : "",
    paper.reading_status,
    paper.parse_status,
  ].filter(Boolean).join(" / ");
}

export default function WritingPage() {
  const [cards, setCards] = useState<KnowledgeCard[]>([]);
  const [snippets, setSnippets] = useState<WritingSnippet[]>([]);
  const [papers, setPapers] = useState<PaperLibraryItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectedPaperIds, setSelectedPaperIds] = useState<Set<string>>(new Set());
  const [paperQuery, setPaperQuery] = useState("");
  const [advancedPaperIds, setAdvancedPaperIds] = useState("");
  const [showAdvancedPaperInput, setShowAdvancedPaperInput] = useState(false);
  const [sectionHint, setSectionHint] = useState<SectionHint>("related_work");
  const [table, setTable] = useState<ComparisonTableResponse | null>(null);
  const [exportText, setExportText] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cardRows, snippetRows, paperRows] = await Promise.all([
        listKnowledgeCards({ status: "verified", limit: 200 }),
        listWritingSnippets(),
        listPapers({ limit: 500 }),
      ]);
      setCards(cardRows);
      setSnippets(snippetRows);
      setPapers(paperRows);
      setError("");
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedCards = useMemo(
    () => cards.filter((card) => selected.has(card.card_id)),
    [cards, selected],
  );

  const paperById = useMemo(
    () => new Map(papers.map((paper) => [paper.paper_id, paper])),
    [papers],
  );

  const selectedPapers = useMemo(
    () => Array.from(selectedPaperIds).map((paperId) => paperById.get(paperId)).filter(Boolean) as PaperLibraryItem[],
    [paperById, selectedPaperIds],
  );

  const filteredPapers = useMemo(() => {
    const query = paperQuery.trim().toLowerCase();
    const rows = query
      ? papers.filter((paper) => {
          const haystack = [
            paper.title,
            paper.display?.title_zh || "",
            paper.venue,
            paper.year ? String(paper.year) : "",
            paper.citation_key,
            paper.reading_status,
            paper.paper_id,
          ].join(" ").toLowerCase();
          return haystack.includes(query);
        })
      : papers;
    return rows.slice(0, 80);
  }, [paperQuery, papers]);

  const togglePaper = (paperId: string) => {
    setSelectedPaperIds((prev) => {
      const next = new Set(prev);
      if (next.has(paperId)) next.delete(paperId);
      else next.add(paperId);
      return next;
    });
  };

  const addPapersFromSelectedCards = () => {
    const ids = selectedCards.map((card) => card.paper_id).filter(Boolean);
    if (!ids.length) {
      setError("当前已选卡片没有关联论文。");
      return;
    }
    setSelectedPaperIds((prev) => {
      const next = new Set(prev);
      ids.forEach((paperId) => next.add(paperId));
      return next;
    });
    setError("");
  };

  const compose = async () => {
    if (!selectedCards.length) {
      setError("请选择至少一张已确认卡片。");
      return;
    }
    try {
      await composeRelatedWork({ card_ids: selectedCards.map((card) => card.card_id), section_hint: sectionHint });
      setSelected(new Set());
      await load();
    } catch (err) {
      setError(errMessage(err));
    }
  };

  const makeTable = async () => {
    const advancedIds = advancedPaperIds.split(/[\s,]+/).map((id) => id.trim()).filter(Boolean);
    const ids = Array.from(new Set([...selectedPaperIds, ...advancedIds]));
    if (!ids.length) {
      setError("请选择至少一篇论文。");
      return;
    }
    try {
      setTable(await buildComparisonTable({ paper_ids: ids }));
    } catch (err) {
      setError(errMessage(err));
    }
  };

  const exportKind = async (kind: "traceable" | "clean" | "bibtex" | "ris" | "zotero" | "obsidian") => {
    try {
      const res =
        kind === "traceable" ? await exportWritingMarkdown("", "traceable")
        : kind === "clean" ? await exportWritingMarkdown("", "clean")
        : kind === "bibtex" ? await exportPapersBibtex()
        : kind === "ris" ? await exportPapersRis()
        : kind === "zotero" ? await exportPapersZoteroCslJson()
        : await exportObsidianMarkdown();
      setExportText(res.content);
    } catch (err) {
      setError(errMessage(err));
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-5 py-8">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">写作与导出</h1>
          <p className="mt-1 text-sm text-muted-foreground">从已确认 Claim / Synthesis 生成草稿、对比表和外部导出。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => exportKind("traceable")} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">Traceable Markdown</button>
          <button onClick={() => exportKind("clean")} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">Clean Markdown</button>
          <button onClick={() => exportKind("bibtex")} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">BibTeX</button>
          <button onClick={() => exportKind("ris")} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">RIS</button>
          <button onClick={() => exportKind("zotero")} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">Zotero CSL</button>
          <button onClick={() => exportKind("obsidian")} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">Obsidian</button>
        </div>
      </div>
      {error && <p className="mb-4 rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}

      <div className="grid gap-5 xl:grid-cols-[1fr_.9fr]">
        <section className="rounded-xl border border-border bg-card p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">草稿合成器</h2>
            <div className="flex gap-2">
              <select value={sectionHint} onChange={(e) => setSectionHint(e.target.value as SectionHint)} className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
                <option value="related_work">related_work</option>
                <option value="method">method</option>
                <option value="experiment">experiment</option>
                <option value="limitation">limitation</option>
              </select>
              <button onClick={compose} className="rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground hover:bg-primary-hover">生成片段</button>
            </div>
          </div>
          {loading ? (
            <p className="py-10 text-center text-sm text-muted-foreground">加载中...</p>
          ) : (
            <div className="max-h-[34rem] space-y-2 overflow-auto pr-1">
              {cards.map((card) => (
                <label key={card.card_id} className="flex gap-3 rounded-lg border border-border bg-background p-3">
                  <input
                    type="checkbox"
                    checked={selected.has(card.card_id)}
                    onChange={() => setSelected((prev) => {
                      const next = new Set(prev);
                      if (next.has(card.card_id)) next.delete(card.card_id);
                      else next.add(card.card_id);
                      return next;
                    })}
                    className="mt-1 h-4 w-4"
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{card.title}</span>
                    <span className="mt-1 line-clamp-2 block text-xs leading-5 text-muted-foreground">{card.content}</span>
                    <span className="mt-1 block text-xs text-muted-foreground">{card.asset_level} / {card.card_type} / p.{card.source_page || "-"}</span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">写作素材</h2>
          <div className="max-h-[34rem] space-y-2 overflow-auto pr-1">
            {snippets.map((snippet) => (
              <article key={snippet.snippet_id} className="rounded-lg border border-border bg-background p-3">
                <div className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                  <span>{snippet.section_hint}</span>
                  <span>{snippet.trace_mode}</span>
                  {snippet.citation_key && <span>@{snippet.citation_key}</span>}
                  {snippet.source_page > 0 && <span>p.{snippet.source_page}</span>}
                  <span>{snippet.source_card_ids.length || (snippet.source_card_id ? 1 : 0)} cards</span>
                  <span>{snippet.evidence_ids.length} evidence</span>
                </div>
                <p className="mt-2 text-sm leading-6">{snippet.content}</p>
                {Array.isArray(snippet.paragraph_plan_json.order) && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    plan: {(snippet.paragraph_plan_json.order as string[]).join(" / ")}
                  </p>
                )}
              </article>
            ))}
            {!snippets.length && <p className="py-10 text-center text-sm text-muted-foreground">暂无素材。</p>}
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-4 xl:col-span-2">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="mr-auto text-sm font-semibold">跨论文对比表</h2>
            <button onClick={addPapersFromSelectedCards} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">从已选卡片加入论文</button>
            <button onClick={makeTable} className="rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground hover:bg-primary-hover">生成表格</button>
          </div>
          <div className="grid gap-4 lg:grid-cols-[.9fr_1.1fr]">
            <div className="rounded-lg border border-border bg-background p-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-xs font-semibold text-muted-foreground">已选论文</h3>
                {selectedPaperIds.size > 0 && (
                  <button onClick={() => setSelectedPaperIds(new Set())} className="text-xs text-muted-foreground hover:text-foreground">清空</button>
                )}
              </div>
              <div className="mt-2 min-h-20 space-y-2">
                {selectedPapers.map((paper) => (
                  <div key={paper.paper_id} className="flex items-start justify-between gap-2 rounded-lg border border-border px-3 py-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{paperTitle(paper)}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{paperMeta(paper)}</p>
                    </div>
                    <button onClick={() => togglePaper(paper.paper_id)} className="shrink-0 rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted">移除</button>
                  </div>
                ))}
                {!selectedPapers.length && <p className="py-6 text-center text-sm text-muted-foreground">尚未选择论文。</p>}
              </div>
              <button
                onClick={() => setShowAdvancedPaperInput((value) => !value)}
                className="mt-3 rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-muted"
              >
                {showAdvancedPaperInput ? "隐藏高级输入" : "高级输入"}
              </button>
              {showAdvancedPaperInput && (
                <textarea
                  value={advancedPaperIds}
                  onChange={(e) => setAdvancedPaperIds(e.target.value)}
                  placeholder="可选：粘贴 paper_id，以空格、换行或逗号分隔"
                  className="mt-2 min-h-20 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
                />
              )}
            </div>

            <div className="rounded-lg border border-border bg-background p-3">
              <input
                value={paperQuery}
                onChange={(e) => setPaperQuery(e.target.value)}
                placeholder="搜索标题、中文标题、venue、年份、citation key 或状态"
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
              />
              <div className="mt-3 max-h-80 space-y-2 overflow-auto pr-1">
                {filteredPapers.map((paper) => {
                  const checked = selectedPaperIds.has(paper.paper_id);
                  return (
                    <label key={paper.paper_id} className="flex cursor-pointer gap-3 rounded-lg border border-border p-3 hover:bg-muted/40">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => togglePaper(paper.paper_id)}
                        className="mt-1 h-4 w-4"
                      />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">{paperTitle(paper)}</span>
                        {paper.title && paper.display?.title_zh && paper.title !== paper.display.title_zh && (
                          <span className="mt-1 line-clamp-1 block text-xs text-muted-foreground">{paper.title}</span>
                        )}
                        <span className="mt-1 block text-xs text-muted-foreground">{paperMeta(paper)}</span>
                      </span>
                    </label>
                  );
                })}
                {!filteredPapers.length && <p className="py-10 text-center text-sm text-muted-foreground">暂无可选论文。</p>}
              </div>
            </div>
          </div>
          {table && (
            <div className="mt-4 overflow-auto">
              <table className="min-w-full border-separate border-spacing-0 text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    {table.columns.map((column) => <th key={column} className="border-b border-border px-3 py-2">{column}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row) => (
                    <tr key={row.paper_id} className="align-top">
                      {table.columns.map((column) => {
                        const key = column === "paper" ? "title" : column;
                        return (
                          <td key={column} className="whitespace-pre-line border-b border-border px-3 py-3">
                            {String(row[key as keyof typeof row] || "缺失")}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {exportText && (
        <section className="mt-5 rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">导出内容</h2>
          <pre className="max-h-96 overflow-auto rounded-lg border border-border bg-background p-3 text-xs leading-5 whitespace-pre-wrap">{exportText}</pre>
        </section>
      )}
    </div>
  );
}
