"use client";

import Link from "next/link";
import { useTranslation } from "@/lib/i18n";
import {
  IconArrowRight,
  IconBookOpen,
  IconCards,
  IconCheck,
  IconCog,
  IconDatabase,
  IconDownload,
  IconLayers,
  IconLens,
  IconPencil,
  IconSearch,
  IconSnap,
  IconSparkles,
  IconSphere,
  IconUpload,
  IconWrench,
} from "@/components/icons";
import type { ComponentType } from "react";

type IconType = ComponentType<{ className?: string }>;

const MODES: {
  key: string;
  titleKey: string;
  descKey: string;
  Icon: IconType;
  status: "done" | "active" | "queued";
}[] = [
  { key: "snap", titleKey: "home.mode.snap.title", descKey: "home.mode.snap.desc", Icon: IconSnap, status: "done" },
  { key: "lens", titleKey: "home.mode.lens.title", descKey: "home.mode.lens.desc", Icon: IconLens, status: "active" },
  { key: "sphere", titleKey: "home.mode.sphere.title", descKey: "home.mode.sphere.desc", Icon: IconSphere, status: "queued" },
  { key: "qa", titleKey: "home.mode.qa.title", descKey: "home.mode.qa.desc", Icon: IconSparkles, status: "queued" },
];

const FEATURES: {
  key: string;
  href: string;
  titleZh: string;
  titleEn: string;
  descZh: string;
  descEn: string;
  Icon: IconType;
  badgeZh?: string;
  badgeEn?: string;
}[] = [
  {
    key: "upload",
    href: "/upload",
    titleZh: "上传与分析",
    titleEn: "Upload & analyze",
    descZh: "上传 PDF，选择速览、精读、脉络或问答模式，生成中文解读。",
    descEn: "Upload PDFs and generate Snap, Lens, Sphere, or Q&A reports.",
    Icon: IconUpload,
  },
  {
    key: "daily",
    href: "/daily",
    titleZh: "每日推荐",
    titleEn: "Daily recommendations",
    descZh: "按研究方向拉取 arXiv 候选，筛选后入库并启动解读。",
    descEn: "Review arXiv candidates and promote useful papers into the library.",
    Icon: IconSparkles,
    badgeZh: "方向可配置",
    badgeEn: "Configurable",
  },
  {
    key: "paper-notes",
    href: "/paper-notes",
    titleZh: "顶会雷达",
    titleEn: "Paper-Notes radar",
    descZh: "全量同步外部顶会笔记，支持筛选、预览、入库并中文解读。",
    descEn: "Sync external conference notes, preview Markdown, and start Chinese runs.",
    Icon: IconSearch,
    badgeZh: "新增",
    badgeEn: "New",
  },
  {
    key: "papers",
    href: "/papers",
    titleZh: "本地论文",
    titleEn: "Local papers",
    descZh: "管理论文、分类、阅读状态、元数据、历史解读和同步状态。",
    descEn: "Manage papers, collections, metadata, reading state, and run history.",
    Icon: IconBookOpen,
  },
  {
    key: "library",
    href: "/library",
    titleZh: "语料检索与问答",
    titleEn: "Corpus search & Q&A",
    descZh: "对本地知识库进行关键词、语义或混合检索，并跨文档问答。",
    descEn: "Search local corpora and ask cross-document questions.",
    Icon: IconDatabase,
  },
  {
    key: "knowledge",
    href: "/knowledge",
    titleZh: "知识卡片",
    titleEn: "Knowledge cards",
    descZh: "沉淀观点、方法、结果、局限和可复用写作片段。",
    descEn: "Distill claims, methods, results, limitations, and writing snippets.",
    Icon: IconCards,
  },
  {
    key: "synthesis",
    href: "/synthesis",
    titleZh: "综合",
    titleEn: "Synthesis",
    descZh: "把卡片、论文和证据组织成更高层的研究判断。",
    descEn: "Synthesize cards, papers, and evidence into higher-level insight.",
    Icon: IconLens,
    badgeZh: "新增",
    badgeEn: "New",
  },
  {
    key: "writing",
    href: "/writing",
    titleZh: "写作",
    titleEn: "Writing",
    descZh: "管理写作片段、相关工作素材和可追溯引用。",
    descEn: "Manage writing snippets, related-work material, and traceable citations.",
    Icon: IconPencil,
    badgeZh: "新增",
    badgeEn: "New",
  },
  {
    key: "spaces",
    href: "/knowledge-spaces",
    titleZh: "知识空间",
    titleEn: "Knowledge spaces",
    descZh: "管理本地空间、Dify 数据集绑定和 Markdown 同步预览。",
    descEn: "Organize spaces, bind Dify datasets, and preview synced Markdown.",
    Icon: IconLayers,
  },
  {
    key: "translate",
    href: "/translate",
    titleZh: "在线翻译",
    titleEn: "Translation",
    descZh: "用当前 DeepLX 配置翻译研究文本。",
    descEn: "Translate research text with the configured DeepLX service.",
    Icon: IconDownload,
  },
  {
    key: "health",
    href: "/health",
    titleZh: "维护检查",
    titleEn: "Maintenance",
    descZh: "检查解析、同步、元数据和笔记完整性问题。",
    descEn: "Inspect parsing, sync, metadata, and note-completion issues.",
    Icon: IconWrench,
  },
  {
    key: "settings",
    href: "/settings",
    titleZh: "系统设置",
    titleEn: "Settings",
    descZh: "在线配置 LLM、模型、推理强度和每日推荐关键词方向。",
    descEn: "Configure LLMs, reasoning, API keys, and daily recommendation topics.",
    Icon: IconCog,
    badgeZh: "新增配置",
    badgeEn: "New settings",
  },
];

const FLOW: { key: string; titleZh: string; titleEn: string; descZh: string; descEn: string; Icon: IconType }[] = [
  { key: "1", titleZh: "发现", titleEn: "Discover", descZh: "每日推荐与顶会雷达发现候选论文。", descEn: "Use Daily and Paper-Notes radar to find candidates.", Icon: IconSparkles },
  { key: "2", titleZh: "入库", titleEn: "Ingest", descZh: "把值得读的论文导入本地库。", descEn: "Promote useful papers into the local library.", Icon: IconBookOpen },
  { key: "3", titleZh: "解读", titleEn: "Analyze", descZh: "按速览、精读、脉络或问答生成报告。", descEn: "Run Snap, Lens, Sphere, or Q&A analysis.", Icon: IconLens },
  { key: "4", titleZh: "沉淀", titleEn: "Reuse", descZh: "沉淀卡片、写作片段和知识空间。", descEn: "Reuse cards, writing snippets, and knowledge spaces.", Icon: IconCards },
];

export default function Home() {
  const { locale, t } = useTranslation();
  const zh = locale === "zh";

  return (
    <div className="relative overflow-hidden">
      <div aria-hidden className="ambient-aurora" />
      <div aria-hidden className="bg-grid-fade h-[640px]" />

      <div className="relative mx-auto max-w-6xl px-6 pb-24 pt-14 sm:pt-20">
        <section className="grid gap-12 lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
          <div className="animate-fade-in-up">
            <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card/80 px-3.5 py-1.5 text-xs font-medium text-muted-foreground soft-shadow backdrop-blur">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full rounded-full bg-primary opacity-60 pulse-dot" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
              </span>
              {t("home.eyebrow")}
            </span>

            <h1 className="font-display mt-7 max-w-3xl text-balance text-4xl font-semibold leading-[1.06] tracking-tight sm:text-6xl">
              <span className="text-gradient">{t("home.title")}</span>
            </h1>

            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground">
              {zh
                ? "本地研究工作台：从每日推荐、顶会笔记和 PDF 上传开始，完成中文解读、知识沉淀、语料问答与写作复用。"
                : "A local research workspace for daily discovery, external notes, paper analysis, corpus Q&A, and reusable writing assets."}
            </p>

            <div className="mt-9 flex flex-wrap items-center gap-3">
              <Link href="/upload" className="group inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3.5 font-medium text-primary-foreground transition-colors hover:bg-primary-hover glow-cta">
                {t("home.cta")}
                <IconArrowRight className="text-lg transition-transform group-hover:translate-x-0.5" />
              </Link>
              <Link href="/daily" className="inline-flex items-center gap-2 rounded-xl border border-border bg-card/70 px-6 py-3.5 font-medium text-foreground backdrop-blur transition-colors hover:bg-muted">
                {zh ? "查看每日推荐" : "Open Daily"}
              </Link>
              <Link href="/paper-notes" className="inline-flex items-center gap-2 rounded-xl border border-border bg-card/70 px-6 py-3.5 font-medium text-foreground backdrop-blur transition-colors hover:bg-muted">
                {zh ? "打开顶会雷达" : "Open Radar"}
              </Link>
            </div>

            <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
              {[zh ? "推荐方向可在线调整" : "Editable discovery topics", zh ? "外部笔记隔离入库" : "Isolated external-note intake", zh ? "中文解读与知识沉淀" : "Chinese analysis and reusable knowledge"].map((label) => (
                <span key={label} className="inline-flex items-center gap-1.5">
                  <IconCheck className="text-[15px] text-primary" />
                  {label}
                </span>
              ))}
            </div>
          </div>

          <div className="animate-fade-in-up [animation-delay:120ms]">
            <div className="mock-card float-soft rounded-2xl border border-border bg-card p-5 sm:p-6">
              <div className="flex items-center justify-between gap-3 border-b border-border pb-4">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg icon-tile">
                    <IconBookOpenSmall />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">Paper-Notes / arXiv / local PDFs</p>
                    <p className="text-xs text-muted-foreground">{t("home.panel_label")}</p>
                  </div>
                </div>
                <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-accent px-2.5 py-1 text-[11px] font-medium text-accent-foreground">
                  <span className="h-1.5 w-1.5 rounded-full bg-success pulse-dot" />
                  {t("home.status.active")}
                </span>
              </div>

              <ul className="mt-4 space-y-2.5">
                {[
                  { label: zh ? "每日推荐抓取" : "Daily discovery", Icon: IconSparkles, status: "done" as const },
                  { label: zh ? "顶会笔记同步" : "Paper-Notes sync", Icon: IconSearch, status: "active" as const },
                  { label: zh ? "入库并中文解读" : "Promote and analyze", Icon: IconLens, status: "queued" as const },
                  { label: zh ? "卡片与写作复用" : "Cards and writing reuse", Icon: IconCards, status: "queued" as const },
                ].map(({ label, Icon, status }) => (
                  <li key={label} className={`flex items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors ${status === "active" ? "border-primary/40 bg-accent/60" : "border-border bg-muted/40"}`}>
                    <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-base ${status === "queued" ? "bg-card text-muted-foreground" : "icon-tile"}`}>
                      <Icon />
                    </span>
                    <span className="flex-1 truncate text-sm font-medium">{label}</span>
                    <StatusPill status={status} label={t(`home.status.${status}`)} />
                  </li>
                ))}
              </ul>

              <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="progress-grow h-full w-[68%] rounded-full bg-primary" />
              </div>
            </div>
          </div>
        </section>

        <section className="mt-24">
          <SectionHeading title={zh ? "从发现到复用" : "From discovery to reuse"} sub={zh ? "保留原来的阅读流水线，同时补上外部雷达和可配置推荐方向。" : "The same paper-reading pipeline, now with external radar and editable discovery topics."} />
          <div className="relative mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {FLOW.map(({ key, titleZh, titleEn, descZh, descEn, Icon }, i) => (
              <div key={key} className="animate-fade-in-up relative rounded-2xl border border-border bg-card p-6 soft-shadow" style={{ animationDelay: `${i * 70}ms` }}>
                <div className="flex items-center justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl icon-tile text-xl">
                    <Icon />
                  </span>
                  <span className="font-display text-3xl font-semibold text-border">{`0${i + 1}`}</span>
                </div>
                <h3 className="mt-5 text-base font-semibold">{zh ? titleZh : titleEn}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{zh ? descZh : descEn}</p>
                {i < FLOW.length - 1 && <IconArrowRight className="absolute -right-3.5 top-1/2 hidden -translate-y-1/2 text-lg text-muted-foreground lg:block" />}
              </div>
            ))}
          </div>
        </section>

        <section className="mt-24">
          <SectionHeading title={t("home.features_heading")} sub={zh ? "保留完整模块入口，新增功能用标签标出，避免首页信息过载。" : "All main modules remain available; new capabilities are marked without overloading the page."} />
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ key, href, titleZh, titleEn, descZh, descEn, Icon, badgeZh, badgeEn }, i) => (
              <Link key={key} href={href} className="feature-card animate-fade-in-up group rounded-2xl border border-border bg-card p-6 soft-shadow" style={{ animationDelay: `${i * 45}ms` }}>
                <div className="relative flex items-start justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl icon-tile text-xl">
                    <Icon />
                  </span>
                  <span className="flex items-center gap-2">
                    {(badgeZh || badgeEn) && (
                      <span className="rounded-full border border-primary/25 bg-accent px-2 py-1 text-[11px] font-medium text-primary">
                        {zh ? badgeZh : badgeEn}
                      </span>
                    )}
                    <IconArrowRight className="text-lg text-muted-foreground opacity-0 transition-all duration-200 group-hover:translate-x-0.5 group-hover:opacity-100" />
                  </span>
                </div>
                <h3 className="relative mt-5 text-lg font-semibold">{zh ? titleZh : titleEn}</h3>
                <p className="relative mt-2 text-sm leading-relaxed text-muted-foreground">{zh ? descZh : descEn}</p>
              </Link>
            ))}
          </div>
        </section>

        <section className="mt-24">
          <SectionHeading title={t("home.modes_heading")} sub={t("home.modes_sub")} />
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {MODES.map(({ key, titleKey, descKey, Icon }, i) => (
              <div key={key} className="feature-card animate-fade-in-up rounded-2xl border border-border bg-card p-6 soft-shadow" style={{ animationDelay: `${i * 60}ms` }}>
                <span className="flex h-11 w-11 items-center justify-center rounded-xl icon-tile text-xl">
                  <Icon />
                </span>
                <h3 className="relative mt-5 text-lg font-semibold">{t(titleKey)}</h3>
                <p className="relative mt-2 text-sm leading-relaxed text-muted-foreground">{t(descKey)}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-24">
          <div className="cta-band rounded-3xl border border-border px-8 py-12 text-center soft-shadow sm:px-12 sm:py-16">
            <div aria-hidden className="ambient-aurora opacity-50" />
            <div className="relative">
              <h2 className="font-display text-2xl font-semibold tracking-tight sm:text-4xl">
                {zh ? "推荐方向会变，配置不必重建。" : "Research focus changes; configuration should not require rebuilds."}
              </h2>
              <p className="mx-auto mt-3 max-w-xl text-muted-foreground">
                {zh ? "现在可以直接在设置页调整每日推荐关键词，再回到每日推荐刷新候选论文。" : "Edit daily recommendation topics in Settings, then refresh Daily candidates."}
              </p>
              <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
                <Link href="/settings" className="group inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3.5 font-medium text-primary-foreground transition-colors hover:bg-primary-hover glow-cta">
                  {zh ? "配置推荐方向" : "Configure topics"}
                  <IconArrowRight className="text-lg transition-transform group-hover:translate-x-0.5" />
                </Link>
                <Link href="/daily" className="inline-flex items-center gap-2 rounded-xl border border-border bg-card/70 px-6 py-3.5 font-medium text-foreground backdrop-blur transition-colors hover:bg-muted">
                  {t("home.feature.daily.title")}
                </Link>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function SectionHeading({ eyebrow, title, sub }: { eyebrow?: string; title: string; sub: string }) {
  return (
    <div className="max-w-2xl">
      {eyebrow && <span className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">{eyebrow}</span>}
      <h2 className="font-display mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h2>
      <p className="mt-2 text-muted-foreground">{sub}</p>
    </div>
  );
}

function StatusPill({ status, label }: { status: "done" | "active" | "queued"; label: string }) {
  if (status === "done") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-success">
        <IconCheck className="text-[13px]" />
        {label}
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1.5 text-[11px] font-medium text-primary">
        <span className="h-1.5 w-1.5 rounded-full bg-primary pulse-dot" />
        {label}
      </span>
    );
  }
  return <span className="shrink-0 text-[11px] font-medium text-muted-foreground">{label}</span>;
}

function IconBookOpenSmall({ className }: { className?: string }) {
  return (
    <svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
      <path d="M14 3v4a1 1 0 0 0 1 1h4" />
      <path d="M5 3h9l5 5v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
    </svg>
  );
}
