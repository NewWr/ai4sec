"use client";

import { LanguageProvider, LanguageToggle, useTranslation } from "@/lib/i18n";
import type { ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS: { href: string; en: string; zh: string }[] = [
  { href: "/upload", en: "Upload & Analyze", zh: "上传与分析" },
  { href: "/daily", en: "Daily", zh: "每日推荐" },
  { href: "/papers", en: "Papers", zh: "本地论文" },
  { href: "/library", en: "Knowledge Base", zh: "知识库" },
  { href: "/knowledge", en: "Cards", zh: "知识卡片" },
  { href: "/synthesis", en: "Synthesis", zh: "综合" },
  { href: "/writing", en: "Writing", zh: "写作" },
  { href: "/knowledge-spaces", en: "Knowledge Spaces", zh: "知识空间" },
  { href: "/translate", en: "Translate", zh: "翻译" },
  { href: "/health", en: "Maintenance", zh: "维护" },
  { href: "/settings", en: "Settings", zh: "设置" },
];

function NavLink({ href, label }: { href: string; label: string }) {
  const pathname = usePathname();
  const active = pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`nav-link ${active ? "nav-link-active" : ""}`}
    >
      {label}
    </Link>
  );
}

function NavBar() {
  const { t, locale } = useTranslation();

  return (
    <nav className="sticky top-0 z-40 h-14 overflow-hidden border-b border-border bg-background/75 backdrop-blur-md">
      <div className="flex h-full min-w-0 items-center gap-3 px-4 sm:px-6">
        <Link
          href="/"
          className="group flex shrink-0 items-center gap-2.5 font-semibold tracking-tight"
        >
          <span className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg border border-border bg-card transition-colors group-hover:border-[color-mix(in_srgb,var(--primary)_45%,var(--border))]">
            <Image
              src="/scholar.png"
              alt="Scholar"
              width={28}
              height={28}
              className="h-7 w-7 rounded object-contain"
              priority
            />
          </span>
          <span className="font-display text-[15px]">{t("nav.brand")}</span>
        </Link>
        <div className="hidden h-5 w-px shrink-0 bg-border sm:block" />
        <div className="flex h-full min-w-0 flex-1 items-center gap-1 overflow-x-auto overflow-y-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.href}
              href={item.href}
              label={locale === "en" ? item.en : item.zh}
            />
          ))}
        </div>
        <div className="shrink-0">
          <LanguageToggle />
        </div>
      </div>
    </nav>
  );
}

export default function ClientLayout({ children }: { children: ReactNode }) {
  return (
    <LanguageProvider>
      <NavBar />
      <main>{children}</main>
    </LanguageProvider>
  );
}
