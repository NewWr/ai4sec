"use client";

import Link from "next/link";
import { useTranslation } from "@/lib/i18n";
import {
  IconSnap,
  IconLens,
  IconSphere,
  IconSparkles,
  IconUpload,
  IconArrowRight,
  IconDownload,
  IconPlus,
  IconBookOpen,
  IconCards,
  IconDatabase,
  IconWrench,
  IconCog,
  IconCheck,
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
  titleKey: string;
  descKey: string;
  Icon: IconType;
}[] = [
  { key: "upload", href: "/upload", titleKey: "home.feature.upload.title", descKey: "home.feature.upload.desc", Icon: IconUpload },
  { key: "daily", href: "/daily", titleKey: "home.feature.daily.title", descKey: "home.feature.daily.desc", Icon: IconSparkles },
  { key: "papers", href: "/papers", titleKey: "home.feature.papers.title", descKey: "home.feature.papers.desc", Icon: IconBookOpen },
  { key: "library", href: "/library", titleKey: "home.feature.library.title", descKey: "home.feature.library.desc", Icon: IconDatabase },
  { key: "knowledge", href: "/knowledge", titleKey: "home.feature.knowledge.title", descKey: "home.feature.knowledge.desc", Icon: IconCards },
  { key: "spaces", href: "/knowledge-spaces", titleKey: "home.feature.spaces.title", descKey: "home.feature.spaces.desc", Icon: IconPlus },
  { key: "translate", href: "/translate", titleKey: "home.feature.translate.title", descKey: "home.feature.translate.desc", Icon: IconDownload },
  { key: "health", href: "/health", titleKey: "home.feature.health.title", descKey: "home.feature.health.desc", Icon: IconWrench },
  { key: "settings", href: "/settings", titleKey: "home.feature.settings.title", descKey: "home.feature.settings.desc", Icon: IconCog },
];

const FLOW: { key: string; titleKey: string; descKey: string; Icon: IconType }[] = [
  { key: "1", titleKey: "home.flow.1.title", descKey: "home.flow.1.desc", Icon: IconUpload },
  { key: "2", titleKey: "home.flow.2.title", descKey: "home.flow.2.desc", Icon: IconLens },
  { key: "3", titleKey: "home.flow.3.title", descKey: "home.flow.3.desc", Icon: IconCheck },
  { key: "4", titleKey: "home.flow.4.title", descKey: "home.flow.4.desc", Icon: IconCards },
];

export default function Home() {
  const { t } = useTranslation();

  return (
    <div className="relative overflow-hidden">
      {/* Ambient background layers */}
      <div aria-hidden className="ambient-aurora" />
      <div aria-hidden className="bg-grid-fade h-[640px]" />

      <div className="relative mx-auto max-w-6xl px-6 pb-24 pt-14 sm:pt-20">
        {/* ---------------------------------------------------------- */}
        {/* Hero                                                       */}
        {/* ---------------------------------------------------------- */}
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
              {t("home.subtitle")}
            </p>

            <div className="mt-9 flex flex-wrap items-center gap-3">
              <Link
                href="/upload"
                className="group inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3.5 font-medium text-primary-foreground transition-colors hover:bg-primary-hover glow-cta"
              >
                {t("home.cta")}
                <IconArrowRight className="text-lg transition-transform group-hover:translate-x-0.5" />
              </Link>
              <Link
                href="/papers"
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-card/70 px-6 py-3.5 font-medium text-foreground backdrop-blur transition-colors hover:bg-muted"
              >
                {t("home.secondary_cta")}
              </Link>
            </div>

            <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
              {["home.chip1", "home.chip2", "home.chip3"].map((k) => (
                <span key={k} className="inline-flex items-center gap-1.5">
                  <IconCheck className="text-[15px] text-primary" />
                  {t(k)}
                </span>
              ))}
            </div>
          </div>

          {/* Product mock — live analysis pipeline */}
          <div className="animate-fade-in-up [animation-delay:120ms]">
            <div className="mock-card float-soft rounded-2xl border border-border bg-card p-5 sm:p-6">
              <div className="flex items-center justify-between gap-3 border-b border-border pb-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg icon-tile">
                    <IconBookOpenSmall />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">attention-is-all-you-need.pdf</p>
                    <p className="text-xs text-muted-foreground">{t("home.panel_label")}</p>
                  </div>
                </div>
                <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-accent px-2.5 py-1 text-[11px] font-medium text-accent-foreground">
                  <span className="h-1.5 w-1.5 rounded-full bg-success pulse-dot" />
                  {t("home.status.active")}
                </span>
              </div>

              <ul className="mt-4 space-y-2.5">
                {MODES.map(({ key, titleKey, Icon, status }) => (
                  <li
                    key={key}
                    className={`flex items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors ${
                      status === "active"
                        ? "border-primary/40 bg-accent/60"
                        : "border-border bg-muted/40"
                    }`}
                  >
                    <span
                      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-base ${
                        status === "queued"
                          ? "bg-card text-muted-foreground"
                          : "icon-tile"
                      }`}
                    >
                      <Icon />
                    </span>
                    <span className="flex-1 truncate text-sm font-medium">{t(titleKey)}</span>
                    <StatusPill status={status} label={t(`home.status.${status}`)} />
                  </li>
                ))}
              </ul>

              <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="progress-grow h-full w-[62%] rounded-full bg-primary" />
              </div>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------- */}
        {/* Flow — how it works                                        */}
        {/* ---------------------------------------------------------- */}
        <section className="mt-24">
          <SectionHeading
            eyebrow={t("home.eyebrow")}
            title={t("home.flow_heading")}
            sub={t("home.flow_sub")}
          />

          <div className="relative mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {FLOW.map(({ key, titleKey, descKey, Icon }, i) => (
              <div
                key={key}
                className="animate-fade-in-up relative rounded-2xl border border-border bg-card p-6 soft-shadow"
                style={{ animationDelay: `${i * 70}ms` }}
              >
                <div className="flex items-center justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl icon-tile text-xl">
                    <Icon />
                  </span>
                  <span className="font-display text-3xl font-semibold text-border">
                    {`0${i + 1}`}
                  </span>
                </div>
                <h3 className="mt-5 text-base font-semibold">{t(titleKey)}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                  {t(descKey)}
                </p>
                {i < FLOW.length - 1 && (
                  <IconArrowRight className="absolute -right-3.5 top-1/2 hidden -translate-y-1/2 text-lg text-muted-foreground lg:block" />
                )}
              </div>
            ))}
          </div>
        </section>

        {/* ---------------------------------------------------------- */}
        {/* Workspace modules                                          */}
        {/* ---------------------------------------------------------- */}
        <section className="mt-24">
          <SectionHeading
            title={t("home.features_heading")}
            sub={t("home.features_sub")}
          />

          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ key, href, titleKey, descKey, Icon }, i) => (
              <Link
                key={key}
                href={href}
                className="feature-card animate-fade-in-up group rounded-2xl border border-border bg-card p-6 soft-shadow"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                <div className="relative flex items-start justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl icon-tile text-xl">
                    <Icon />
                  </span>
                  <IconArrowRight className="text-lg text-muted-foreground opacity-0 transition-all duration-200 group-hover:translate-x-0.5 group-hover:opacity-100" />
                </div>
                <h3 className="relative mt-5 text-lg font-semibold">{t(titleKey)}</h3>
                <p className="relative mt-2 text-sm leading-relaxed text-muted-foreground">
                  {t(descKey)}
                </p>
              </Link>
            ))}
          </div>
        </section>

        {/* ---------------------------------------------------------- */}
        {/* Analysis modes                                             */}
        {/* ---------------------------------------------------------- */}
        <section className="mt-24">
          <SectionHeading
            title={t("home.modes_heading")}
            sub={t("home.modes_sub")}
          />

          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {MODES.map(({ key, titleKey, descKey, Icon }, i) => (
              <div
                key={key}
                className="feature-card animate-fade-in-up rounded-2xl border border-border bg-card p-6 soft-shadow"
                style={{ animationDelay: `${i * 60}ms` }}
              >
                <span className="flex h-11 w-11 items-center justify-center rounded-xl icon-tile text-xl">
                  <Icon />
                </span>
                <h3 className="relative mt-5 text-lg font-semibold">{t(titleKey)}</h3>
                <p className="relative mt-2 text-sm leading-relaxed text-muted-foreground">
                  {t(descKey)}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* ---------------------------------------------------------- */}
        {/* Closing CTA band                                           */}
        {/* ---------------------------------------------------------- */}
        <section className="mt-24">
          <div className="cta-band rounded-3xl border border-border px-8 py-12 text-center soft-shadow sm:px-12 sm:py-16">
            <div aria-hidden className="ambient-aurora opacity-50" />
            <div className="relative">
              <h2 className="font-display text-2xl font-semibold tracking-tight sm:text-4xl">
                {t("home.cta_band.title")}
              </h2>
              <p className="mx-auto mt-3 max-w-xl text-muted-foreground">
                {t("home.cta_band.sub")}
              </p>
              <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
                <Link
                  href="/upload"
                  className="group inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3.5 font-medium text-primary-foreground transition-colors hover:bg-primary-hover glow-cta"
                >
                  {t("home.cta")}
                  <IconArrowRight className="text-lg transition-transform group-hover:translate-x-0.5" />
                </Link>
                <Link
                  href="/daily"
                  className="inline-flex items-center gap-2 rounded-xl border border-border bg-card/70 px-6 py-3.5 font-medium text-foreground backdrop-blur transition-colors hover:bg-muted"
                >
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

function SectionHeading({
  eyebrow,
  title,
  sub,
}: {
  eyebrow?: string;
  title: string;
  sub: string;
}) {
  return (
    <div className="max-w-2xl">
      {eyebrow && (
        <span className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
          {eyebrow}
        </span>
      )}
      <h2 className="font-display mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
        {title}
      </h2>
      <p className="mt-2 text-muted-foreground">{sub}</p>
    </div>
  );
}

function StatusPill({
  status,
  label,
}: {
  status: "done" | "active" | "queued";
  label: string;
}) {
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
  return (
    <span className="shrink-0 text-[11px] font-medium text-muted-foreground">
      {label}
    </span>
  );
}

/** Small document glyph for the mock card header. */
function IconBookOpenSmall({ className }: { className?: string }) {
  return (
    <svg
      width="1em"
      height="1em"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <path d="M14 3v4a1 1 0 0 0 1 1h4" />
      <path d="M5 3h9l5 5v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
    </svg>
  );
}
