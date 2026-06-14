/**
 * Shared loading spinner. One inline spinner for the whole app so buttons and
 * panels stop hand-rolling their own border-spinner markup.
 *
 * Inherits the current text color (border-current), so it works on solid
 * buttons (text-primary-foreground) and ghost buttons alike. CSS-only.
 */
const SIZES = {
  sm: "h-3.5 w-3.5 border-2",
  md: "h-4 w-4 border-2",
  lg: "h-10 w-10 border-[3px]",
} as const;

export function Spinner({
  size = "md",
  className = "",
}: {
  size?: keyof typeof SIZES;
  className?: string;
}) {
  return (
    <span
      role="status"
      aria-label="加载中"
      className={`inline-block shrink-0 animate-spin rounded-full border-current/30 border-t-current motion-reduce:animate-none ${SIZES[size]} ${className}`}
    />
  );
}

export default Spinner;
