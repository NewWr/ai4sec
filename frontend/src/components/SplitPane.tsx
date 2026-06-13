"use client";

import { useCallback, useRef, useState } from "react";
import type { CSSProperties } from "react";

interface SplitPaneProps {
  left: React.ReactNode;
  right: React.ReactNode;
  defaultLeftWidth?: number; // percentage, default 55
  mobileLeftHeight?: number; // viewport height, default 58
  mobileRightHeight?: number; // viewport height, default 68
  stackBelow?: "md" | "lg";
  leftPaneClassName?: string;
  rightPaneClassName?: string;
}

export default function SplitPane({
  left,
  right,
  defaultLeftWidth = 55,
  mobileLeftHeight = 58,
  mobileRightHeight = 68,
  stackBelow = "lg",
  leftPaneClassName = "min-h-0 overflow-auto",
  rightPaneClassName = "min-h-0 overflow-auto",
}: SplitPaneProps) {
  const [leftWidth, setLeftWidth] = useState(defaultLeftWidth);
  const dragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const onMouseDown = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const pct = ((e.clientX - rect.left) / rect.width) * 100;
    setLeftWidth(Math.max(20, Math.min(80, pct)));
  }, []);

  const onMouseUp = useCallback(() => {
    dragging.current = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  }, []);

  const stackClasses =
    stackBelow === "md"
      ? {
          container: "flex-col overflow-y-auto overflow-x-hidden md:flex-row md:overflow-hidden",
          left: "h-[var(--mobile-left-height)] md:h-auto md:[width:var(--left-width)]",
          resizer: "hidden md:block",
          right: "h-[var(--mobile-right-height)] md:h-auto md:[width:var(--right-width)]",
        }
      : {
          container: "flex-col overflow-y-auto overflow-x-hidden lg:flex-row lg:overflow-hidden",
          left: "h-[var(--mobile-left-height)] lg:h-auto lg:[width:var(--left-width)]",
          resizer: "hidden lg:block",
          right: "h-[var(--mobile-right-height)] lg:h-auto lg:[width:var(--right-width)]",
        };

  const paneStyle = {
    "--left-width": `${leftWidth}%`,
    "--right-width": `${100 - leftWidth}%`,
    "--mobile-left-height": `${mobileLeftHeight}vh`,
    "--mobile-right-height": `${mobileRightHeight}vh`,
  } as CSSProperties;

  return (
    <div
      ref={containerRef}
      className={`flex h-full min-h-0 ${stackClasses.container}`}
      style={paneStyle}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      <div
        className={`w-full shrink-0 ${stackClasses.left} ${leftPaneClassName}`}
      >
        {left}
      </div>
      <div
        className={`group relative w-px shrink-0 cursor-col-resize bg-border ${stackClasses.resizer}`}
        onMouseDown={onMouseDown}
      >
        {/* Wider invisible hit area for easier grabbing */}
        <div className="absolute inset-y-0 -left-2 -right-2 z-10" />
        {/* Visible grip */}
        <div className="absolute left-1/2 top-1/2 h-9 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-border transition-colors group-hover:bg-primary" />
      </div>
      <div
        className={`w-full shrink-0 ${stackClasses.right} ${rightPaneClassName}`}
      >
        {right}
      </div>
    </div>
  );
}
