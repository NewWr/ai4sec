"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ExportPanel, type ExportItem } from "@/components/ExportPanel";
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
import { assetLevelLabel, cardTypeLabel, sectionHintLabel, traceModeLabel } from "@/lib/labels";
import type { ComparisonTableResponse, KnowledgeCard, PaperLibraryItem, SectionHint, WritingSnippet } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { PageContainer } from "@/components/PageContainer";
import { IconPencil } from "@/components/icons";

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
  ].filter(Boolean).join(" / ");
}

const TABLE_COLUMN_LABELS: Record<string, string> = {
  paper: "论文",
  method: "方法",
  dataset: "数据集",
  metric: "指标",
  result: "结果",
  limitation: "局限",
  conflicts: "冲突",
};

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

  const exportItems = useMemo<ExportItem[]>(() => [
    {
      id: "writing-traceable",
      label: "带证据 Markdown",
      description: "复制素材正文、来源、原文摘录和段落计划。",
      filename: "ai4sec-writing-traceable.md",
      mime: "text/markdown;charset=utf-8",
      emptyMessage: "暂无可复制的写作素材，请先生成片段或加入写作素材。",
      load: async () => (await exportWritingMarkdown("", "traceable")).content,
    },
    {
      id: "writing-clean",
      label: "纯净 Markdown",
      description: "只复制正文和引用标记，适合粘贴进草稿。",
      filename: "ai4sec-writing-clean.md",
      mime: "text/markdown;charset=utf-8",
      emptyMessage: "暂无可复制的写作素材，请先生成片段或加入写作素材。",
      load: async () => (await exportWritingMarkdown("", "clean")).content,
    },
    {
      id: "papers-bibtex",
      label: "BibTeX",
      description: "复制论文引用，适合 LaTeX。",
      filename: "ai4sec-papers.bib",
      mime: "application/x-bibtex;charset=utf-8",
      emptyMessage: "暂无可复制的 BibTeX，请先导入或解析论文引用。",
      load: async () => (await exportPapersBibtex()).content,
    },
    {
      id: "papers-ris",
      label: "RIS",
      description: "复制引用记录，适合文献管理器。",
      filename: "ai4sec-papers.ris",
      mime: "application/x-research-info-systems;charset=utf-8",
      emptyMessage: "暂无可复制的 RIS，请先导入或解析论文引用。",
      load: async () => (await exportPapersRis()).content,
    },
    {
      id: "papers-zotero",
      label: "Zotero CSL",
      description: "复制 CSL JSON，适合 Zotero 或引用工具。",
      filename: "ai4sec-papers-csl.json",
      mime: "application/json;charset=utf-8",
      emptyMessage: "暂无可复制的 CSL JSON，请先导入或解析论文引用。",
      load: async () => (await exportPapersZoteroCslJson()).content,
    },
    {
      id: "obsidian",
      label: "Obsidian Markdown",
      description: "复制已确认知识卡片，适合放入笔记库。",
      filename: "ai4sec-obsidian.md",
      mime: "text/markdown;charset=utf-8",
      emptyMessage: "暂无可复制的 Obsidian 内容，请先确认知识卡片。",
      load: async () => (await exportObsidianMarkdown()).content,
    },
  ], []);

  const setPanelError = useCallback((message: string) => {
    setError(message);
  }, []);

  return (
    <PageContainer size="wide">
      <PageHeader
        icon={IconPencil}
        title="写作与导出"
        subtitle="从已确认论点卡、综合卡生成草稿、对比表和外部导出。"
      />
      {error && <p className="alert alert-error mb-4">{error}</p>}

      <ExportPanel items={exportItems} onError={setPanelError} />

      <div className="grid gap-5 xl:grid-cols-[1fr_.9fr]">
        <section className="surface-card p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">草稿合成器</h2>
            <div className="flex gap-2">
              <select value={sectionHint} onChange={(e) => setSectionHint(e.target.value as SectionHint)} className="field field-sm">
                <option value="related_work">{sectionHintLabel("related_work")}</option>
                <option value="method">{sectionHintLabel("method")}</option>
                <option value="experiment">{sectionHintLabel("experiment")}</option>
                <option value="limitation">{sectionHintLabel("limitation")}</option>
              </select>
              <button onClick={compose} className="btn btn-primary btn-sm">生成片段</button>
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
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {assetLevelLabel(card.asset_level)} / {cardTypeLabel(card.card_type)} / 第 {card.source_page || "-"} 页
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </section>

        <section className="surface-card p-4">
          <h2 className="mb-3 text-sm font-semibold">写作素材</h2>
          <div className="max-h-[34rem] space-y-2 overflow-auto pr-1">
            {snippets.map((snippet) => (
              <article key={snippet.snippet_id} className="rounded-lg border border-border bg-background p-3">
                <div className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                  <span>{sectionHintLabel(snippet.section_hint)}</span>
                  <span>{traceModeLabel(snippet.trace_mode)}</span>
                  {snippet.citation_key && <span>@{snippet.citation_key}</span>}
                  {snippet.source_page > 0 && <span>第 {snippet.source_page} 页</span>}
                  <span>{snippet.source_card_ids.length || (snippet.source_card_id ? 1 : 0)} 张卡片</span>
                  <span>{snippet.evidence_ids.length} 条证据</span>
                </div>
                <p className="mt-2 text-sm leading-6">{snippet.content}</p>
                {Array.isArray(snippet.paragraph_plan_json.order) && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    段落计划：{(snippet.paragraph_plan_json.order as string[]).join(" / ")}
                  </p>
                )}
              </article>
            ))}
            {!snippets.length && <p className="py-10 text-center text-sm text-muted-foreground">暂无素材。</p>}
          </div>
        </section>

        <section className="surface-card p-4 xl:col-span-2">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="mr-auto text-sm font-semibold">跨论文对比表</h2>
            <button onClick={addPapersFromSelectedCards} className="btn btn-outline btn-sm">从已选卡片加入论文</button>
            <button onClick={makeTable} className="btn btn-primary btn-sm">生成表格</button>
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
                    <button onClick={() => togglePaper(paper.paper_id)} className="shrink-0 btn btn-outline btn-sm">移除</button>
                  </div>
                ))}
                {!selectedPapers.length && <p className="py-6 text-center text-sm text-muted-foreground">尚未选择论文。</p>}
              </div>
              <button
                onClick={() => setShowAdvancedPaperInput((value) => !value)}
                className="mt-3 btn btn-outline btn-sm"
              >
                {showAdvancedPaperInput ? "隐藏高级输入" : "高级输入"}
              </button>
              {showAdvancedPaperInput && (
                <textarea
                  value={advancedPaperIds}
                  onChange={(e) => setAdvancedPaperIds(e.target.value)}
                  placeholder="可选：粘贴 paper_id，以空格、换行或逗号分隔"
                  className="mt-2 min-h-20 w-full field"
                />
              )}
            </div>

            <div className="rounded-lg border border-border bg-background p-3">
              <input
                value={paperQuery}
                onChange={(e) => setPaperQuery(e.target.value)}
                placeholder="搜索标题、中文标题、会议/期刊、年份、引用键或状态"
                className="w-full field"
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
                    {table.columns.map((column) => <th key={column} className="border-b border-border px-3 py-2">{TABLE_COLUMN_LABELS[column] || column}</th>)}
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

    </PageContainer>
  );
}
