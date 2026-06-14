import type { ComponentType, ReactNode } from "react";

/**
 * Shared interior-page header — matches the landing page style:
 * subtle ambient accent, clay icon tile, optional eyebrow, serif title,
 * muted subtitle, and a right-aligned actions slot.
 *
 * Purely presentational + CSS-only effects, so it adds no runtime cost.
 */
export function PageHeader({
  icon: Icon,
  eyebrow,
  title,
  subtitle,
  actions,
  className = "",
}: {
  icon?: ComponentType<{ className?: string }>;
  eyebrow?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={`relative mb-6 flex flex-wrap items-start justify-between gap-4 ${className}`}
    >
      <div aria-hidden className="page-accent" />
      <div className="relative flex items-start gap-3.5">
        {Icon && (
          <span className="icon-tile flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-xl">
            <Icon />
          </span>
        )}
        <div className="min-w-0">
          {eyebrow && (
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
              {eyebrow}
            </span>
          )}
          <h1 className="font-display text-2xl font-semibold leading-tight tracking-tight sm:text-[1.7rem]">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {actions && (
        <div className="relative flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      )}
    </header>
  );
}
