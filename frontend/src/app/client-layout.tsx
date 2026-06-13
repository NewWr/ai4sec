"use client";

import { LanguageProvider, LanguageToggle, useTranslation } from "@/lib/i18n";
import type { ReactNode } from "react";
import Image from "next/image";
import { usePathname } from "next/navigation";

function NavLink({ href, label }: { href: string; label: string }) {
  const pathname = usePathname();
  const active = pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
  return (
    <a
      href={href}
      className={`inline-flex h-full shrink-0 items-center whitespace-nowrap text-sm transition-colors ${
        active
          ? "text-foreground font-medium"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </a>
  );
}

function NavBar() {
  const { t } = useTranslation();

  return (
    <nav className="sticky top-0 z-40 h-14 overflow-hidden border-b border-border bg-background/80 backdrop-blur-md">
      <div className="flex h-full min-w-0 items-center gap-4 px-4 sm:px-6">
        <a href="/" className="flex shrink-0 items-center gap-2.5 font-semibold tracking-tight">
          <Image
            src="/scholar.png"
            alt="Scholar"
            width={28}
            height={28}
            className="h-7 w-7 rounded-lg object-contain"
            priority
          />
          <span className="text-[15px]">{t("nav.brand")}</span>
        </a>
        <div className="hidden h-5 w-px shrink-0 bg-border sm:block" />
        <div className="flex h-full min-w-0 flex-1 items-center gap-4 overflow-x-auto overflow-y-hidden [scrollbar-width:none] sm:gap-5 [&::-webkit-scrollbar]:hidden">
          <NavLink href="/upload" label={t("nav.upload")} />
          <NavLink href="/daily" label="每日推荐" />
          <NavLink href="/papers" label={t("nav.papers")} />
          <NavLink href="/knowledge" label="知识卡片" />
          <NavLink href="/synthesis" label="综合" />
          <NavLink href="/writing" label="写作" />
          <NavLink href="/knowledge-spaces" label="知识库" />
          <NavLink href="/translate" label={t("nav.translate")} />
          <NavLink href="/health" label="维护" />
          <NavLink href="/settings" label="设置" />
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
