import type { SVGProps } from "react";

/**
 * Lightweight stroke-icon set (no external dependency).
 * Icons scale with font-size by default (1em) and accept a className
 * so callers can size them with Tailwind utilities (e.g. `w-5 h-5`).
 */
type IconProps = SVGProps<SVGSVGElement>;

function Svg({ children, ...props }: IconProps) {
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
      {...props}
    >
      {children}
    </svg>
  );
}

/** Anthropic-style burst / asterisk — used as the brand mark. */
export function IconBurst(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 2.5v19M2.5 12h19M5.2 5.2l13.6 13.6M18.8 5.2 5.2 18.8" />
    </Svg>
  );
}

/** Insight Snap — quick triage (lightning). */
export function IconSnap(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M13 2 4.5 13.5H11l-1 8.5L19.5 10H13l1-8Z" />
    </Svg>
  );
}

/** Logic Lens — deep analysis (magnifier). */
export function IconLens(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </Svg>
  );
}

/** Research Sphere — citation landscape (globe). */
export function IconSphere(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3c2.6 2.6 2.6 15.4 0 18M12 3c-2.6 2.6-2.6 15.4 0 18" />
    </Svg>
  );
}

/** Smart Q&A — auto routing (sparkles). */
export function IconSparkles(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3.5 13.6 8 18 9.6 13.6 11.2 12 15.7 10.4 11.2 6 9.6 10.4 8 12 3.5Z" />
      <path d="M18.5 14.5l.8 2.1 2.2.8-2.2.8-.8 2.1-.8-2.1-2.2-.8 2.2-.8.8-2.1Z" />
    </Svg>
  );
}

export function IconUpload(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 16V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </Svg>
  );
}

export function IconArrowRight(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </Svg>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m20 6-11 11-5-5" />
    </Svg>
  );
}

export function IconDownload(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3v12" />
      <path d="m7 11 5 5 5-5" />
      <path d="M5 21h14" />
    </Svg>
  );
}

export function IconChevronLeft(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m15 18-6-6 6-6" />
    </Svg>
  );
}

export function IconChevronRight(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m9 18 6-6-6-6" />
    </Svg>
  );
}

export function IconMinus(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12h14" />
    </Svg>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  );
}

export function IconBookOpen(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 7v14" />
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H12v18H6.5A2.5 2.5 0 0 0 4 23V5.5Z" />
      <path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H12v18h5.5A2.5 2.5 0 0 1 20 23V5.5Z" />
    </Svg>
  );
}

export function IconCards(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="4" y="5" width="13" height="15" rx="2" />
      <path d="M8 9h5M8 13h5M8 17h3" />
      <path d="M8 3h10a2 2 0 0 1 2 2v12" />
    </Svg>
  );
}

export function IconDatabase(props: IconProps) {
  return (
    <Svg {...props}>
      <ellipse cx="12" cy="5" rx="7" ry="3" />
      <path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5" />
      <path d="M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
    </Svg>
  );
}

export function IconWrench(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M14.7 6.3a4.2 4.2 0 0 0 5 5L10.8 20.2a2.5 2.5 0 0 1-3.5-3.5l8.9-8.9a4.2 4.2 0 0 1-1.5-1.5Z" />
      <path d="M7.8 17.2 6 19" />
    </Svg>
  );
}

export function IconCog(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v3M12 18.5v3M4.5 4.5l2.1 2.1M17.4 17.4l2.1 2.1M2.5 12h3M18.5 12h3M4.5 19.5l2.1-2.1M17.4 6.6l2.1-2.1" />
    </Svg>
  );
}

/** Writing — pencil. */
export function IconPencil(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z" />
    </Svg>
  );
}

/** Translate — languages. */
export function IconLanguages(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 5h7M9 3v2c0 4-2.5 7-6 8" />
      <path d="M5 9c0 2.5 2.8 4.7 6 5.5" />
      <path d="m13 21 4-9 4 9M14.5 17h5" />
    </Svg>
  );
}

/** Library — search. */
export function IconSearch(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </Svg>
  );
}

/** Knowledge spaces — layers. */
export function IconLayers(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 13 9 5 9-5M3 18l9 5 9-5" />
    </Svg>
  );
}

/** Refresh — circular arrows. */
export function IconRefresh(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M21 12a9 9 0 1 1-2.6-6.4" />
      <path d="M21 4v5h-5" />
    </Svg>
  );
}

/** Close — X. */
export function IconX(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M18 6 6 18M6 6l12 12" />
    </Svg>
  );
}

/** Delete — trash can. */
export function IconTrash(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 7h16" />
      <path d="M10 11v6M14 11v6" />
      <path d="M6 7l1 14h10l1-14" />
      <path d="M9 7V4h6v3" />
    </Svg>
  );
}
