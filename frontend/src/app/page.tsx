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
} from "@/components/icons";
import type { ComponentType } from "react";

const MODES: {
  key: string;
  titleKey: string;
  descKey: string;
  Icon: ComponentType<{ className?: string }>;
}[] = [
  { key: "snap", titleKey: "home.mode.snap.title", descKey: "home.mode.snap.desc", Icon: IconSnap },
  { key: "lens", titleKey: "home.mode.lens.title", descKey: "home.mode.lens.desc", Icon: IconLens },
  { key: "sphere", titleKey: "home.mode.sphere.title", descKey: "home.mode.sphere.desc", Icon: IconSphere },
  { key: "qa", titleKey: "home.mode.qa.title", descKey: "home.mode.qa.desc", Icon: IconSparkles },
];

const FEATURES: {
  key: string;
  href: string;
  titleKey: string;
  descKey: string;
  Icon: ComponentType<{ className?: string }>;
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

export default function Home() {
  const { t } = useTranslation();

  return (
    <div className="mx-auto max-w-6xl px-6 pb-24 pt-14 sm:pt-20">
      {/* Hero */}
      <section className="grid gap-10 lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
        <div className="animate-fade-in-up">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-medium text-muted-foreground soft-shadow">
            <span className="h-1.5 w-1.5 rounded-full bg-primary" />
            {t("home.eyebrow")}
          </span>

          <h1 className="font-display mt-7 max-w-3xl text-balance text-4xl font-semibold leading-[1.08] tracking-tight sm:text-6xl">
            {t("home.title")}
          </h1>

          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground">
            {t("home.subtitle")}
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link
              href="/upload"
              className="group inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3.5 font-medium text-primary-foreground transition-colors hover:bg-primary-hover"
            >
              {t("home.cta")}
              <IconArrowRight className="text-lg transition-transform group-hover:translate-x-0.5" />
            </Link>
            <Link
              href="/papers"
              className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-6 py-3.5 font-medium text-foreground transition-colors hover:bg-muted"
            >
              {t("home.secondary_cta")}
            </Link>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {FEATURES.slice(0, 6).map(({ key, href, titleKey, Icon }) => (
            <Link
              key={key}
              href={href}
              className="flex min-h-20 items-center gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:bg-muted"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent text-lg text-primary">
                <Icon />
              </span>
              <span className="text-sm font-medium leading-snug">{t(titleKey)}</span>
            </Link>
          ))}
        </div>
      </section>

      {/* Capabilities */}
      <section className="mt-20">
        <div className="mb-8">
          <h2 className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">
            {t("home.features_heading")}
          </h2>
          <p className="mt-2 max-w-2xl text-muted-foreground">{t("home.features_sub")}</p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ key, href, titleKey, descKey, Icon }) => (
            <Link
              key={key}
              href={href}
              className="lift rounded-2xl border border-border bg-card p-6 soft-shadow"
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent text-xl text-primary">
                <Icon />
              </span>
              <h3 className="mt-5 text-lg font-semibold">{t(titleKey)}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {t(descKey)}
              </p>
            </Link>
          ))}
        </div>
      </section>

      {/* Modes */}
      <section className="mt-20">
        <div className="mb-8">
          <h2 className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">
            {t("home.modes_heading")}
          </h2>
          <p className="mt-2 max-w-2xl text-muted-foreground">{t("home.modes_sub")}</p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {MODES.map(({ key, titleKey, descKey, Icon }) => (
            <div
              key={key}
              className="lift rounded-2xl border border-border bg-card p-6 soft-shadow"
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent text-xl text-primary">
                <Icon />
              </span>
              <h3 className="mt-5 text-lg font-semibold">{t(titleKey)}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {t(descKey)}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
