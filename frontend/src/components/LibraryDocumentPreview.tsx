"use client";

import { useMemo } from "react";
import MarkdownRenderer from "@/components/MarkdownRenderer";

type PreviewBlock =
  | { type: "text"; content: string }
  | { type: "table"; caption: string; rows: TableCell[][] };

interface TableCell {
  text: string;
  colSpan: number;
  rowSpan: number;
}

const TABLE_RE = /<table\b[\s\S]*?<\/table>/gi;
const ROW_RE = /<tr\b[^>]*>([\s\S]*?)<\/tr>/gi;
const CELL_RE = /<t([dh])\b([^>]*)>([\s\S]*?)<\/t\1>/gi;

export default function LibraryDocumentPreview({
  content,
  title,
  wide = false,
}: {
  content: string;
  title?: string;
  wide?: boolean;
}) {
  const analysis = useMemo(() => extractAnalysisMarkdown(content), [content]);
  const blocks = useMemo(() => buildPreviewBlocks(content), [content]);

  return (
    <div className="library-document-preview">
      {title ? (
        <p className="library-document-preview-title">{title}</p>
      ) : null}
      <div className={wide ? "mx-auto max-w-5xl" : "mx-auto max-w-3xl"}>
        {analysis ? (
          <MarkdownRenderer content={analysis} softMathErrors />
        ) : (
          blocks.map((block, idx) =>
            block.type === "text" ? (
              <MarkdownRenderer
                key={`text-${idx}`}
                content={block.content}
                softMathErrors
              />
            ) : (
              <LibraryTableBlock
                key={`table-${idx}`}
                caption={block.caption}
                rows={block.rows}
              />
            ),
          )
        )}
      </div>
    </div>
  );
}

function extractAnalysisMarkdown(content: string): string | null {
  if (!/(^|\n)source_type:\s*analysis(\n|$)/.test(content)) return null;

  const lines = normalizeLibraryText(content).split("\n");
  const bodyStart = lines.findIndex((line, idx) => idx > 0 && /^#{1,6}\s+/.test(line.trim()));
  if (bodyStart >= 0) return lines.slice(bodyStart).join("\n").trim();

  const runIdIndex = lines.findIndex((line) => /^run_id:\s*/.test(line.trim()));
  if (runIdIndex >= 0) return lines.slice(runIdIndex + 1).join("\n").trim();

  return content.trim();
}

function buildPreviewBlocks(content: string): PreviewBlock[] {
  const source = normalizeLibraryText(content);
  const blocks: PreviewBlock[] = [];
  let lastIndex = 0;

  for (const match of source.matchAll(TABLE_RE)) {
    const tableStart = match.index ?? 0;
    const before = source.slice(lastIndex, tableStart);
    const { text, caption } = detachTableCaption(before);
    pushTextBlock(blocks, text);
    blocks.push({
      type: "table",
      caption,
      rows: parseHtmlTable(match[0]),
    });
    lastIndex = tableStart + match[0].length;
  }

  pushTextBlock(blocks, source.slice(lastIndex));
  return blocks.length > 0 ? blocks : [{ type: "text", content: "" }];
}

function pushTextBlock(blocks: PreviewBlock[], raw: string) {
  const content = preparePreviewMarkdown(raw);
  if (content) blocks.push({ type: "text", content });
}

function normalizeLibraryText(raw: string): string {
  return raw
    .replace(/\r\n?/g, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/&nbsp;/gi, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function preparePreviewMarkdown(raw: string): string {
  let text = normalizeMathText(stripResidualHtml(raw));
  text = splitEmbeddedSectionHeadings(text);
  text = splitLongParagraphs(text);
  return text.trim();
}

function normalizeMathText(raw: string): string {
  return decodeHtmlEntities(raw)
    .replace(/\?\?2\b/g, "R²")
    .replace(/\$?\(\s*R\s*\^\s*\{\s*2\s*\}\s*\\colon\s*([^)]+?)\s*\)\$?/gi, (_m, value: string) => {
      return `(R²: ${compactSpacedDecimal(value.trim())})`;
    })
    .replace(/\$?\s*R\s*\^\s*\{\s*2\s*\}\s*\\colon\s*\$?/gi, "R²:")
    .replace(/\$?\s*R\s*\^\s*\{\s*2\s*\}\s*\$?/gi, "R²")
    .replace(/\$?\s*R\^2\s*\$?/gi, "R²")
    .replace(/\\colon/g, ":")
    .replace(/(\d)\s+\.\s+(\d)/g, "$1.$2");
}

function splitEmbeddedSectionHeadings(raw: string): string {
  return raw
    .replace(
      /(?<=[.!?)\]])\s+((?:\d+\.)+\s+[A-Z][A-Za-z][^.!?\n]{5,120}?)(?=\s+[A-Z][a-z])/g,
      "\n\n### $1\n\n",
    )
    .replace(
      /(^|\n)((?:\d+\.)+\s+[A-Z][A-Za-z][^.!?\n]{5,120}?)(?=\s+[A-Z][a-z])/g,
      "$1### $2\n\n",
    );
}

function splitLongParagraphs(raw: string): string {
  return raw
    .split(/\n{2,}/)
    .map((paragraph) => {
      const trimmed = paragraph.trim();
      if (trimmed.length < 900 || trimmed.startsWith("#")) return trimmed;

      const sentences = trimmed.split(/(?<=[.!?])\s+(?=[A-Z])/g);
      const groups: string[] = [];
      let group = "";
      for (const sentence of sentences) {
        const next = group ? `${group} ${sentence}` : sentence;
        if (next.length > 620 && group) {
          groups.push(group);
          group = sentence;
        } else {
          group = next;
        }
      }
      if (group) groups.push(group);
      return groups.join("\n\n");
    })
    .filter(Boolean)
    .join("\n\n");
}

function detachTableCaption(raw: string): { text: string; caption: string } {
  const marker = raw.lastIndexOf("[Table]");
  if (marker >= 0) {
    const caption = raw.slice(marker).trim();
    if (/^\[Table\]\s*Table\s+\d+/i.test(caption) && caption.length <= 700) {
      return {
        text: raw.slice(0, marker),
        caption: normalizeCaption(caption),
      };
    }
  }

  const match = raw.match(/(Table\s+\d+[^\n]{0,360})\s*$/i);
  if (match?.index !== undefined) {
    return {
      text: raw.slice(0, match.index),
      caption: normalizeCaption(match[1]),
    };
  }

  return { text: raw, caption: "" };
}

function normalizeCaption(raw: string): string {
  return normalizeMathText(stripResidualHtml(raw))
    .replace(/^\[Table\]\s*/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

function parseHtmlTable(html: string): TableCell[][] {
  const rows: TableCell[][] = [];

  for (const rowMatch of html.matchAll(ROW_RE)) {
    const rowHtml = rowMatch[1];
    const cells: TableCell[] = [];

    for (const cellMatch of rowHtml.matchAll(CELL_RE)) {
      const attrs = cellMatch[2] || "";
      const text = normalizeMathText(stripResidualHtml(cellMatch[3]))
        .replace(/\s+/g, " ")
        .trim();
      cells.push({
        text,
        colSpan: readSpan(attrs, "colspan"),
        rowSpan: readSpan(attrs, "rowspan"),
      });
    }

    if (cells.length > 0) rows.push(cells);
  }

  return rows;
}

function readSpan(attrs: string, name: "colspan" | "rowspan"): number {
  const match = attrs.match(new RegExp(`${name}\\s*=\\s*["']?(\\d+)`, "i"));
  const value = match ? Number(match[1]) : 1;
  return Number.isFinite(value) ? Math.min(Math.max(value, 1), 12) : 1;
}

function stripResidualHtml(raw: string): string {
  return raw.replace(/<[^>]+>/g, " ");
}

function compactSpacedDecimal(value: string): string {
  return value.replace(/(\d)\s+\.\s+(\d)/g, "$1.$2").replace(/\s+/g, " ");
}

function decodeHtmlEntities(raw: string): string {
  return raw
    .replace(/&#x([0-9a-f]+);/gi, (_m, hex: string) =>
      String.fromCodePoint(Number.parseInt(hex, 16)),
    )
    .replace(/&#(\d+);/g, (_m, dec: string) =>
      String.fromCodePoint(Number.parseInt(dec, 10)),
    )
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/g, "'");
}

function LibraryTableBlock({
  caption,
  rows,
}: {
  caption: string;
  rows: TableCell[][];
}) {
  if (rows.length === 0) return null;

  return (
    <section className="library-preview-table-block">
      {caption ? <p className="library-preview-table-caption">{caption}</p> : null}
      <div className="library-preview-table-scroll">
        <table className="library-preview-table">
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => {
                  const Cell = rowIndex === 0 ? "th" : "td";
                  return (
                    <Cell
                      key={`${rowIndex}-${cellIndex}`}
                      colSpan={cell.colSpan}
                      rowSpan={cell.rowSpan}
                    >
                      {cell.text}
                    </Cell>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
