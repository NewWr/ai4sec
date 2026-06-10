"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import type { PluggableList } from "unified";
import { useTranslation } from "@/lib/i18n";
import type { EvidenceAnchor } from "@/lib/types";

// Extend the default GitHub sanitize schema:
// - Allow className on div/span (needed for math wrappers from remark-math)
// - Allow dataPage on span (keeps backwards compatibility with legacy citation badges)
// - Allow className on code (needed for syntax-highlighted code blocks)
const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    div: [...(defaultSchema.attributes?.div || []), "className"],
    span: [...(defaultSchema.attributes?.span || []), "className", "dataPage", "data-page"],
    code: [...(defaultSchema.attributes?.code || []), "className"],
    // Allow embedded figure images (e.g. the architecture diagram in Logic Lens).
    img: [...(defaultSchema.attributes?.img || []), "src", "alt", "title", "loading"],
  },
  // Only same-origin /api image URLs are emitted by the backend; permit relative paths.
  protocols: {
    ...defaultSchema.protocols,
    src: [...(defaultSchema.protocols?.src || []), "http", "https"],
  },
};

const LEGACY_CITATION_SPAN_RE =
  /<span\s+class=["']cite-badge["']\s+data-page=["'](\d+)["']>\[p\.\1\]<\/span>/gi;
const PLAIN_CITATION_RE = /\[p\.(\d+)\]/gi;
const CITATION_HREF_RE = /^#cite-page-(\d+)$/;
const CITATION_ANCHOR_HREF_RE = /^#cite-anchor-([^:]+):(\d+)$/;

// Library (knowledge-base) citations: corpus answers carry document-level
// `[L1]`, `[L2]`… markers (no page index) that link to a source document.
const PLAIN_LIB_CITATION_RE = /\[L(\d+)\]/g;
const LIB_CITATION_HREF_RE = /^#cite-lib-(\d+)$/;

// Dify and PDF extraction can leave malformed display math, especially an
// orphan closing `$$` after a formula line. A global `$$...$$` regex is unsafe:
// it can consume all prose/images until the next equation fence. Normalize
// display math line-by-line and only pair fences that look like real formulas.
const MATH_FENCE = "$$";
const MATH_HINT_RE =
  /\\(?:begin|end|mathcal|mathbb|mathrm|operatorname|text|frac|sqrt|sum|prod|int|tag|quad|cdot|odot|times|in|top|alpha|beta|delta|sigma|tau|hat|tilde|bar|cos|log|exp)|[\^_]\s*\{|\\[{}]/;

export function normalizeDisplayMath(content: string): string {
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const out: string[] = [];
  let inCode = false;
  let inMath = false;
  let openFenceIndex = -1;

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      inCode = !inCode;
      out.push(line);
      continue;
    }

    if (inCode || trimmed !== MATH_FENCE) {
      out.push(line);
      continue;
    }

    if (inMath) {
      out.push(MATH_FENCE);
      if (nextNonEmptyLine(lines, i + 1) >= 0) out.push("");
      inMath = false;
      openFenceIndex = -1;
      continue;
    }

    const previousMathStart = previousMathRunStart(out);
    if (previousMathStart >= 0) {
      insertOpeningFence(out, previousMathStart);
      out.push(MATH_FENCE);
      if (nextNonEmptyLine(lines, i + 1) >= 0) out.push("");
      continue;
    }

    const nextIndex = nextNonEmptyLine(lines, i + 1);
    if (nextIndex >= 0 && isLikelyMathLine(lines[nextIndex])) {
      if (out.length > 0 && out[out.length - 1].trim() !== "") out.push("");
      openFenceIndex = out.length;
      out.push(MATH_FENCE);
      inMath = true;
      continue;
    }

    out.push("\\$\\$");
  }

  if (inMath && openFenceIndex >= 0) {
    out[openFenceIndex] = "\\$\\$";
  }

  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}

function nextNonEmptyLine(lines: string[], start: number): number {
  for (let i = start; i < lines.length; i += 1) {
    if (lines[i].trim()) return i;
  }
  return -1;
}

function previousMathRunStart(lines: string[]): number {
  let end = lines.length - 1;
  if (end < 0 || lines[end].trim() === "" || !isLikelyMathLine(lines[end])) {
    return -1;
  }

  let start = end;
  while (start > 0 && lines[start - 1].trim() !== "" && isLikelyMathLine(lines[start - 1])) {
    start -= 1;
  }
  return start;
}

function insertOpeningFence(lines: string[], index: number) {
  const insert: string[] = [];
  if (index > 0 && lines[index - 1].trim() !== "") insert.push("");
  insert.push(MATH_FENCE);
  lines.splice(index, 0, ...insert);
}

function isLikelyMathLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return false;
  if (/^(#{1,6}\s|!\[|\[[^\]]+\]\(|<[a-zA-Z]|[-*+]\s|\d+\.\s)/.test(trimmed)) {
    return false;
  }
  return MATH_HINT_RE.test(trimmed);
}

export function prepareCitationMarkdown(content: string, evidenceAnchors: EvidenceAnchor[] = []): string {
  let citationIndex = 0;
  const canHighlight = (anchor: EvidenceAnchor) =>
    anchor.status === "resolved"
    && anchor.highlightable !== false
    && Boolean(anchor.source_quote?.trim());
  return content
    .replace(LEGACY_CITATION_SPAN_RE, "[p.$1]")
    .replace(PLAIN_CITATION_RE, (_match, page: string) => {
      const index = citationIndex;
      citationIndex += 1;
      const anchor = evidenceAnchors.find((item) => item.citation_index === index && item.source_page === Number(page) && canHighlight(item));
      if (anchor) return `[[p.${page}]](#cite-anchor-${anchor.anchor_id}:${page})`;
      return `[[p.${page}]](#cite-page-${page})`;
    })
    .replace(PLAIN_LIB_CITATION_RE, (_match, idx: string) => `[[L${idx}]](#cite-lib-${idx})`);
}

interface MarkdownRendererProps {
  content: string;
  evidenceAnchors?: EvidenceAnchor[];
  onCitationClick?: (page: number, anchorId?: string) => void;
  onLibraryCitationClick?: (idx: number) => void;
  softMathErrors?: boolean;
}

export default function MarkdownRenderer({
  content,
  evidenceAnchors = [],
  onCitationClick,
  onLibraryCitationClick,
  softMathErrors = false,
}: MarkdownRendererProps) {
  const { t } = useTranslation();

  // Normalize display equations to block form first, then keep citations as
  // Markdown links so raw HTML never leaks into rendered answers.
  const processed = prepareCitationMarkdown(normalizeDisplayMath(content), evidenceAnchors);
  const rehypePlugins: PluggableList = softMathErrors
    ? [
        rehypeRaw,
        [rehypeSanitize, sanitizeSchema],
        [rehypeKatex, { errorColor: "currentColor", strict: "ignore" }],
      ]
    : [rehypeRaw, [rehypeSanitize, sanitizeSchema], rehypeKatex];

  return (
    <div className={`markdown-body${softMathErrors ? " markdown-body-soft-math" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={rehypePlugins}
        components={{
          a: ({ node, children, ...props }) => {
            const href = typeof props.href === "string" ? props.href : "";
            const anchorMatch = CITATION_ANCHOR_HREF_RE.exec(href);
            const citationMatch = CITATION_HREF_RE.exec(href);

            if (anchorMatch) {
              const anchorId = anchorMatch[1];
              const page = parseInt(anchorMatch[2], 10);
              return (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    onCitationClick?.(page, anchorId);
                  }}
                  className="mx-0.5 inline-flex cursor-pointer items-center rounded-md border border-primary/40 bg-primary/10 px-1.5 py-0.5 align-baseline font-mono text-xs font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground"
                  title={t("pdf.jump_to_page", { page: String(page) })}
                >
                  p.{page}
                </button>
              );
            }

            if (citationMatch) {
              const page = parseInt(citationMatch[1], 10);
              return (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    onCitationClick?.(page);
                  }}
                  className="mx-0.5 inline-flex cursor-pointer items-center rounded-md border border-primary/30 bg-accent px-1.5 py-0.5 align-baseline font-mono text-xs font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground"
                  title={t("pdf.jump_to_page", { page: String(page) })}
                >
                  p.{page}
                </button>
              );
            }

            const libMatch = LIB_CITATION_HREF_RE.exec(href);
            if (libMatch) {
              const idx = parseInt(libMatch[1], 10);
              return (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    onLibraryCitationClick?.(idx);
                  }}
                  className="mx-0.5 inline-flex cursor-pointer items-center rounded-md border border-primary/30 bg-accent px-1.5 py-0.5 align-baseline font-mono text-xs font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground"
                  title={t("library.open_doc")}
                >
                  L{idx}
                </button>
              );
            }

            return <a {...props}>{children}</a>;
          },
          span: ({ node, children, ...props }) => {
            const className = (props as Record<string, unknown>).className as string | undefined;
            const dataPage = (
              (props as Record<string, unknown>)["data-page"] ||
              (props as Record<string, unknown>).dataPage
            ) as string | undefined;

            if (className === "cite-badge" && dataPage) {
              const page = parseInt(dataPage, 10);
              return (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    onCitationClick?.(page);
                  }}
                  className="mx-0.5 inline-flex cursor-pointer items-center rounded-md border border-primary/30 bg-accent px-1.5 py-0.5 align-baseline font-mono text-xs font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground"
                  title={t("pdf.jump_to_page", { page: String(page) })}
                >
                  p.{page}
                </button>
              );
            }

            return <span {...props}>{children}</span>;
          },
          img: ({ node, ...props }) => {
            const src = typeof props.src === "string" ? props.src : "";
            const alt = typeof props.alt === "string" ? props.alt : "";
            if (!src) return null;
            // Rendered inside a <p>, so use inline-level wrappers (no <figure>/<div>).
            return (
              <span className="my-4 flex flex-col items-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={src}
                  alt={alt}
                  loading="lazy"
                  className="max-h-[28rem] max-w-full rounded-lg border border-border bg-white object-contain shadow-sm"
                />
                {alt ? (
                  <span className="mt-1.5 px-4 text-center text-xs text-muted-foreground">
                    {alt}
                  </span>
                ) : null}
              </span>
            );
          },
        }}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}
