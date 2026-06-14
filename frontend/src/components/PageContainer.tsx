import type { ReactNode } from "react";

/**
 * Single source of truth for interior-page width + padding, so every page
 * stops picking its own max-w / px / py ad hoc. Pure layout wrapper — CSS only.
 *
 *   form     — focused single-column forms (e.g. upload)
 *   settings — settings / mid-width detail
 *   content  — standard list & detail pages (default)
 *   wide     — dense multi-column dashboards
 */
const WIDTHS = {
  form: "max-w-3xl",
  settings: "max-w-4xl",
  content: "max-w-6xl",
  wide: "max-w-7xl",
} as const;

export function PageContainer({
  size = "content",
  className = "",
  children,
}: {
  size?: keyof typeof WIDTHS;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`mx-auto w-full ${WIDTHS[size]} px-5 py-8 ${className}`}>
      {children}
    </div>
  );
}

export default PageContainer;
