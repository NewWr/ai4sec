"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/esm/Page/AnnotationLayer.css";
import "react-pdf/dist/esm/Page/TextLayer.css";
import { useTranslation } from "@/lib/i18n";
import {
  IconChevronLeft,
  IconChevronRight,
  IconMinus,
  IconPlus,
} from "@/components/icons";
import type {
  EvidenceAnchor,
  PdfHighlight,
  PdfSelectionAction,
  PdfSelectionRange,
  PdfSelectionRect,
  PdfTextSelection,
} from "@/lib/types";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

interface PdfViewerProps {
  url: string;
  targetPage?: number;
  highlights?: PdfHighlight[];
  activeHighlightId?: string;
  evidenceAnchors?: EvidenceAnchor[];
  activeEvidenceAnchorId?: string;
  pendingSelection?: PdfTextSelection | null;
  onTextSelection?: (selection: PdfTextSelection) => void;
  onSelectionAction?: (action: PdfSelectionAction) => void;
}

const TOOLBAR_BTN =
  "inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent";
const PDF_OVERSCAN_PAGES = 2;
const DEFAULT_PAGE_WIDTH = 794;
const DEFAULT_PAGE_HEIGHT = 1123;

function selectionId() {
  return `sel_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function mergeRects(rects: DOMRect[], pageRect: DOMRect) {
  return rects
    .filter((rect) => rect.width > 1 && rect.height > 1)
    .map((rect) => ({
      x: Math.max(0, Math.min(1, (rect.left - pageRect.left) / pageRect.width)),
      y: Math.max(0, Math.min(1, (rect.top - pageRect.top) / pageRect.height)),
      width: Math.max(0, Math.min(1, rect.width / pageRect.width)),
      height: Math.max(0, Math.min(1, rect.height / pageRect.height)),
    }));
}

function normalizeText(value: string) {
  return value
    .replace(/-\s+/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function normalizeLoose(value: string) {
  return normalizeText(value).replace(/[^\p{L}\p{N}]+/gu, "");
}

function textTokens(value: string) {
  return Array.from(new Set((normalizeText(value).match(/[\p{L}\p{N}]+/gu) || []).filter((token) => token.length > 1)));
}

function tokenCoverage(source: string, target: string) {
  const sourceTokens = textTokens(source);
  if (!sourceTokens.length) return 0;
  const normalizedTarget = normalizeText(target);
  const matched = sourceTokens.filter((token) => normalizedTarget.includes(token)).length;
  return matched / sourceTokens.length;
}

function rectKey(rect: PdfSelectionRect) {
  return `${rect.x.toFixed(4)}:${rect.y.toFixed(4)}:${rect.width.toFixed(4)}:${rect.height.toFixed(4)}`;
}

function textLayerSpans(pageEl: HTMLElement): HTMLSpanElement[] {
  return Array.from(pageEl.querySelectorAll<HTMLSpanElement>(".react-pdf__Page__textContent span"));
}

function rangesFromQuote(page: number, quote: string): PdfSelectionRange[] {
  const pageEl = document.getElementById(`pdf-page-${page}`);
  if (!pageEl || !quote.trim()) return [];
  const spans = textLayerSpans(pageEl);
  if (!spans.length) return [];

  const pageRect = pageEl.getBoundingClientRect();
  const spanText = spans.map((span) => span.textContent || "");
  const normalizedQuote = normalizeText(quote);
  const looseQuote = normalizeLoose(quote);
  const minCoverage = looseQuote.length > 80 ? 0.82 : 0.92;
  const matched: HTMLSpanElement[] = [];

  for (let start = 0; start < spans.length; start += 1) {
    let combined = "";
    for (let end = start; end < Math.min(spans.length, start + 80); end += 1) {
      combined += `${spanText[end]} `;
      const normalizedCombined = normalizeText(combined);
      const looseCombined = normalizeLoose(combined);
      const exactMatch = normalizedCombined.includes(normalizedQuote);
      const looseMatch = looseQuote.length > 24 && looseCombined.includes(looseQuote);
      const coverageMatch =
        looseQuote.length > 48
        && looseCombined.length >= looseQuote.length * 0.75
        && tokenCoverage(quote, combined) >= minCoverage;
      if (
        exactMatch
        || looseMatch
        || coverageMatch
      ) {
        matched.push(...spans.slice(start, end + 1));
        start = end;
        break;
      }
      if (normalizedCombined.length > normalizedQuote.length + 240) break;
    }
    if (matched.length) break;
  }

  if (!matched.length) return [];
  const rects = matched
    .flatMap((span) => Array.from(span.getClientRects()))
    .filter((rect) => rect.width > 1 && rect.height > 1)
    .flatMap((rect) => mergeRects([rect], pageRect));
  const seen = new Set<string>();
  const uniqueRects = rects.filter((rect) => {
    const key = rectKey(rect);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return uniqueRects.length ? [{ page, quote, rects: uniqueRects }] : [];
}

function rangeFromSourceBbox(page: number, quote: string, bbox: number[] | undefined): PdfSelectionRange[] {
  if (!bbox || bbox.length !== 4) return [];
  const [x0, y0, x1, y1] = bbox;
  if (![x0, y0, x1, y1].every(Number.isFinite) || x1 <= x0 || y1 <= y0) return [];
  const width = 972;
  const height = 1260;
  return [{
    page,
    quote,
    rects: [{
      x: Math.max(0, Math.min(1, x0 / width)),
      y: Math.max(0, Math.min(1, y0 / height)),
      width: Math.max(0, Math.min(1, (x1 - x0) / width)),
      height: Math.max(0, Math.min(1, (y1 - y0) / height)),
    }],
  }];
}

function rangesForAnchor(anchor: EvidenceAnchor): PdfSelectionRange[] {
  const textRanges = rangesFromQuote(anchor.source_page, anchor.source_quote);
  if (textRanges.length) return textRanges;
  return rangeFromSourceBbox(anchor.source_page, anchor.source_quote, anchor.source_bbox);
}

function parseSelection(): PdfTextSelection | null {
  const selection = window.getSelection();
  const quote = selection?.toString().trim() || "";
  if (!selection || selection.rangeCount === 0 || !quote) return null;

  const rangesByPage = new Map<number, PdfSelectionRange>();
  const allRects: DOMRect[] = [];

  for (let i = 0; i < selection.rangeCount; i += 1) {
    const range = selection.getRangeAt(i);
    const clientRects = Array.from(range.getClientRects()).filter((rect) => rect.width > 1 && rect.height > 1);
    allRects.push(...clientRects);
    for (const rect of clientRects) {
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const element = document.elementFromPoint(centerX, centerY);
      const pageEl = element?.closest<HTMLElement>("[data-pdf-page-number]");
      const page = Number(pageEl?.dataset.pdfPageNumber || 0);
      if (!page || !pageEl) continue;
      const pageRect = pageEl.getBoundingClientRect();
      const normalized = mergeRects([rect], pageRect);
      if (!normalized.length) continue;
      const existing = rangesByPage.get(page);
      if (existing) {
        existing.rects.push(...normalized);
      } else {
        rangesByPage.set(page, { page, quote: "", rects: normalized });
      }
    }
  }

  if (!rangesByPage.size || !allRects.length) return null;
  const pages = Array.from(rangesByPage.keys()).sort((a, b) => a - b);
  const ranges = pages.map((page) => rangesByPage.get(page)!);
  if (ranges.length === 1) ranges[0].quote = quote;
  const firstRect = allRects.reduce((best, rect) => (
    rect.top < best.top || (rect.top === best.top && rect.left < best.left) ? rect : best
  ), allRects[0]);

  return {
    selection_id: selectionId(),
    source: "pdf",
    page: pages[0],
    quote,
    ranges,
    anchor_rect: {
      left: firstRect.left,
      top: firstRect.top,
      width: firstRect.width,
      height: firstRect.height,
    },
    created_at: Date.now(),
  };
}

export default function PdfViewer({
  url,
  targetPage,
  highlights = [],
  activeHighlightId = "",
  evidenceAnchors = [],
  activeEvidenceAnchorId = "",
  pendingSelection,
  onTextSelection,
  onSelectionAction,
}: PdfViewerProps) {
  const { t } = useTranslation();
  const [numPages, setNumPages] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.0);
  const [error, setError] = useState("");
  const [resolvedEvidenceRanges, setResolvedEvidenceRanges] = useState<Record<string, PdfSelectionRange[]>>({});
  const [pageSizes, setPageSizes] = useState<Record<number, { width: number; height: number }>>({});
  const containerRef = useRef<HTMLDivElement>(null);
  const selectionTimer = useRef<number | null>(null);
  const pendingScrollPageRef = useRef<number | null>(null);

  const scrollToPage = useCallback((page: number) => {
    const nextPage = Math.max(1, Math.min(numPages || 1, page));
    setCurrentPage(nextPage);
    pendingScrollPageRef.current = nextPage;
    const container = containerRef.current;
    const pageEl = document.getElementById(`pdf-page-${nextPage}`);
    if (!container || !pageEl) return;
    const containerRect = container.getBoundingClientRect();
    const pageRect = pageEl.getBoundingClientRect();
    const nextTop = container.scrollTop + pageRect.top - containerRect.top - 16;
    container.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
  }, [numPages]);

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setError("");
    setNumPages(numPages);
  }, []);

  useEffect(() => {
    if (targetPage && targetPage >= 1 && targetPage <= numPages) {
      scrollToPage(targetPage);
    }
  }, [targetPage, numPages, scrollToPage]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !numPages) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        const page = Number(visible[0]?.target.getAttribute("data-pdf-page-number") || 0);
        if (page) setCurrentPage(page);
      },
      { root: container, threshold: [0.15, 0.35, 0.55, 0.75] },
    );
    for (let page = 1; page <= numPages; page += 1) {
      const pageEl = document.getElementById(`pdf-page-${page}`);
      if (pageEl) observer.observe(pageEl);
    }
    return () => observer.disconnect();
  }, [numPages]);

  const handleSelection = useCallback(() => {
    if (!onTextSelection) return;
    if (selectionTimer.current) window.clearTimeout(selectionTimer.current);
    selectionTimer.current = window.setTimeout(() => {
      const selection = parseSelection();
      if (selection) onTextSelection(selection);
    }, 100);
  }, [onTextSelection]);

  const resolveVisibleEvidence = useCallback(() => {
    if (!activeEvidenceAnchorId) return;
    const anchor = evidenceAnchors.find((item) => item.anchor_id === activeEvidenceAnchorId);
    if (!anchor?.source_quote || !anchor.source_page || anchor.status !== "resolved" || anchor.highlightable === false) return;
    setResolvedEvidenceRanges((current) => {
      if (current[anchor.anchor_id]?.length) return current;
      const ranges = rangesForAnchor(anchor);
      return ranges.length ? { ...current, [anchor.anchor_id]: ranges } : current;
    });
  }, [activeEvidenceAnchorId, evidenceAnchors]);

  useEffect(() => {
    const timer = window.setTimeout(resolveVisibleEvidence, 250);
    return () => window.clearTimeout(timer);
  }, [resolveVisibleEvidence, scale, numPages, targetPage]);

  const evidenceHighlights = useMemo<PdfHighlight[]>(() => {
    if (!activeEvidenceAnchorId) return [];
    const ranges = resolvedEvidenceRanges[activeEvidenceAnchorId] || [];
    return ranges.length ? [{ id: activeEvidenceAnchorId, ranges, color: "evidence-active", active: true }] : [];
  }, [activeEvidenceAnchorId, evidenceAnchors, resolvedEvidenceRanges]);

  const pageHighlights = useMemo(() => {
    const map = new Map<number, PdfHighlight[]>();
    const combined = pendingSelection
      ? [
          ...evidenceHighlights,
          ...highlights,
          { id: pendingSelection.selection_id, ranges: pendingSelection.ranges, color: "draft", active: true },
        ]
      : [...evidenceHighlights, ...highlights];
    for (const highlight of combined) {
      for (const range of highlight.ranges || []) {
        const pageItems = map.get(range.page) || [];
        pageItems.push({
          ...highlight,
          active: highlight.active || highlight.id === activeHighlightId,
          ranges: [range],
        });
        map.set(range.page, pageItems);
      }
    }
    return map;
  }, [activeHighlightId, evidenceHighlights, highlights, pendingSelection]);

  const pages = Array.from({ length: numPages || 0 }, (_, i) => i + 1);
  const visiblePageSet = useMemo(() => {
    const activePages = new Set<number>();
    for (
      let page = Math.max(1, currentPage - PDF_OVERSCAN_PAGES);
      page <= Math.min(numPages, currentPage + PDF_OVERSCAN_PAGES);
      page += 1
    ) {
      activePages.add(page);
    }
    if (targetPage && targetPage >= 1 && targetPage <= numPages) activePages.add(targetPage);
    const activeAnchor = evidenceAnchors.find((anchor) => anchor.anchor_id === activeEvidenceAnchorId);
    if (activeAnchor?.source_page) activePages.add(activeAnchor.source_page);
    for (const page of pageHighlights.keys()) activePages.add(page);
    return activePages;
  }, [activeEvidenceAnchorId, currentPage, evidenceAnchors, numPages, pageHighlights, targetPage]);
  const floatingLeft = pendingSelection ? Math.max(12, pendingSelection.anchor_rect.left) : 0;
  const floatingTop = pendingSelection ? Math.max(78, pendingSelection.anchor_rect.top - 48) : 0;

  useEffect(() => {
    const pendingPage = pendingScrollPageRef.current;
    if (!pendingPage || !visiblePageSet.has(pendingPage)) return;
    const timer = window.setTimeout(() => {
      const container = containerRef.current;
      const pageEl = document.getElementById(`pdf-page-${pendingPage}`);
      if (!container || !pageEl) return;
      const containerRect = container.getBoundingClientRect();
      const pageRect = pageEl.getBoundingClientRect();
      const nextTop = container.scrollTop + pageRect.top - containerRect.top - 16;
      container.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
      pendingScrollPageRef.current = null;
    }, 80);
    return () => window.clearTimeout(timer);
  }, [visiblePageSet]);

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-2 border-b border-border bg-card/60 px-3 py-2 text-sm">
        <button
          onClick={() => scrollToPage(currentPage - 1)}
          disabled={currentPage <= 1}
          className={TOOLBAR_BTN}
          title={t("pdf.prev")}
        >
          <IconChevronLeft />
        </button>
        <span className="tabular-nums text-muted-foreground">
          <span className="font-medium text-foreground">{currentPage}</span> / {numPages || "-"}
        </span>
        <button
          onClick={() => scrollToPage(currentPage + 1)}
          disabled={currentPage >= numPages}
          className={TOOLBAR_BTN}
          title={t("pdf.next")}
        >
          <IconChevronRight />
        </button>
        <div className="flex-1" />
        <button onClick={() => setScale(Math.max(0.5, scale - 0.1))} className={TOOLBAR_BTN}>
          <IconMinus />
        </button>
        <span className="w-11 text-center tabular-nums text-muted-foreground">
          {Math.round(scale * 100)}%
        </span>
        <button onClick={() => setScale(Math.min(3.0, scale + 0.1))} className={TOOLBAR_BTN}>
          <IconPlus />
        </button>
      </div>

      {pendingSelection && onSelectionAction && (
        <div
          className="fixed z-50 flex items-center gap-1 rounded-lg border border-border bg-card p-1 text-xs shadow-lg"
          style={{ left: floatingLeft, top: floatingTop }}
        >
          <button onClick={() => onSelectionAction("replace")} className="rounded-md px-2 py-1.5 hover:bg-muted">替换</button>
          <button onClick={() => onSelectionAction("save")} className="rounded-md px-2 py-1.5 hover:bg-muted">保存摘录</button>
          <button onClick={() => onSelectionAction("append")} className="rounded-md px-2 py-1.5 hover:bg-muted">追加</button>
          <button onClick={() => onSelectionAction("question")} className="rounded-md px-2 py-1.5 hover:bg-muted">问题</button>
          <button onClick={() => onSelectionAction("card")} className="rounded-md px-2 py-1.5 hover:bg-muted">建卡片</button>
          <button onClick={() => onSelectionAction("cancel")} className="rounded-md px-2 py-1.5 text-muted-foreground hover:bg-muted">取消</button>
        </div>
      )}

      <div
        ref={containerRef}
        data-pdf-scroll
        onMouseUp={handleSelection}
        className="min-h-0 flex-1 overflow-auto bg-muted p-5 [contain:layout_paint]"
      >
        <Document
          file={url}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={(err) => setError(err.message)}
          loading={<div className="flex h-48 items-center justify-center text-muted-foreground">{t("pdf.loading")}</div>}
          error={
            <div className="mx-auto max-w-md rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
              Failed to load PDF file{error ? `: ${error}` : "."}
            </div>
          }
        >
          <div className="space-y-5">
            {pages.map((pageNumber) => (
              <div
                key={pageNumber}
                id={`pdf-page-${pageNumber}`}
                data-pdf-page-number={pageNumber}
                className="relative mx-auto w-fit"
                style={{
                  minWidth: `${(pageSizes[pageNumber]?.width || DEFAULT_PAGE_WIDTH) * scale}px`,
                  minHeight: `${(pageSizes[pageNumber]?.height || DEFAULT_PAGE_HEIGHT) * scale}px`,
                }}
              >
                {visiblePageSet.has(pageNumber) ? (
                  <>
                    <Page
                      pageNumber={pageNumber}
                      scale={scale}
                      className="overflow-hidden rounded-lg shadow-[0_4px_24px_-8px_rgba(20,20,19,0.25)]"
                      renderTextLayer={true}
                      renderAnnotationLayer={true}
                      onLoadSuccess={(page) => {
                        const viewport = page.getViewport({ scale: 1 });
                        setPageSizes((current) => (
                          current[pageNumber]
                            ? current
                            : { ...current, [pageNumber]: { width: viewport.width, height: viewport.height } }
                        ));
                      }}
                      onRenderSuccess={() => {
                        window.setTimeout(resolveVisibleEvidence, 0);
                      }}
                    />
                    <PageHighlightOverlay highlights={pageHighlights.get(pageNumber) || []} />
                  </>
                ) : (
                  <div className="h-full w-full rounded-lg bg-card/35 shadow-[0_4px_24px_-8px_rgba(20,20,19,0.12)]" />
                )}
              </div>
            ))}
          </div>
        </Document>
      </div>
    </div>
  );
}

function PageHighlightOverlay({ highlights }: { highlights: PdfHighlight[] }) {
  if (!highlights.length) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-10">
      {highlights.flatMap((highlight) =>
        highlight.ranges.flatMap((range) =>
          range.rects.map((rect, index) => (
            <div
              key={`${highlight.id}-${range.page}-${index}`}
              className={`absolute rounded-[2px] ${
                highlight.color === "draft"
                  ? "bg-primary/25 ring-1 ring-primary/35"
                  : highlight.color === "evidence-active"
                    ? "bg-primary/28 ring-1 ring-primary/55"
                    : highlight.color === "evidence"
                      ? "bg-amber-300/25 ring-1 ring-amber-400/30"
                  : highlight.active
                    ? "bg-primary/24 ring-1 ring-primary/45"
                    : "bg-yellow-300/35"
              }`}
              style={{
                left: `${rect.x * 100}%`,
                top: `${rect.y * 100}%`,
                width: `${rect.width * 100}%`,
                height: `${rect.height * 100}%`,
              }}
            />
          ))
        )
      )}
    </div>
  );
}
