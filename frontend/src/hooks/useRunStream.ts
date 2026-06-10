"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getRunStreamUrl } from "@/lib/api";
import type { SSEEvent } from "@/lib/types";

interface UseRunStreamReturn {
  events: SSEEvent[];
  isConnected: boolean;
  isDone: boolean;
  error: string | null;
  connect: (runId: string) => void;
}

export function useRunStream(): UseRunStreamReturn {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isDone, setIsDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const activeRunIdRef = useRef<string>("");
  const reconnectAttemptsRef = useRef(0);
  const lastEventIdRef = useRef(0);
  const connectTimeRef = useRef<number>(0);

  const closeSource = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const connect = useCallback((runId: string) => {
    const isNewRun = activeRunIdRef.current !== runId;
    if (isNewRun) {
      setEvents([]);
      setIsDone(false);
      setError(null);
      lastEventIdRef.current = 0;
      reconnectAttemptsRef.current = 0;
      activeRunIdRef.current = runId;
    }

    clearReconnectTimer();
    closeSource();

    setIsConnected(true);
    connectTimeRef.current = performance.now();

    const url = getRunStreamUrl(runId, lastEventIdRef.current);
    console.log(`[SSE] Connecting to ${url}`);
    const source = new EventSource(url);
    eventSourceRef.current = source;

    source.onopen = () => {
      reconnectAttemptsRef.current = 0;
      console.log(`[SSE] Connected (${(performance.now() - connectTimeRef.current).toFixed(0)}ms)`);
    };

    source.onmessage = (e) => {
      const elapsed = ((performance.now() - connectTimeRef.current) / 1000).toFixed(1);
      try {
        const parsed: SSEEvent = JSON.parse(e.data);
        console.log(`[SSE +${elapsed}s] ${parsed.event}`, parsed.data);
        const eventId = Number(e.lastEventId || parsed.seq || 0);
        if (Number.isFinite(eventId) && eventId > lastEventIdRef.current) {
          lastEventIdRef.current = eventId;
        }
        setEvents((prev) => [...prev, parsed]);

        if (parsed.event === "done" || parsed.event === "end") {
          console.log(`[SSE] Stream completed at +${elapsed}s`);
          clearReconnectTimer();
          setIsDone(true);
          setIsConnected(false);
          closeSource();
        } else if (parsed.event === "error" || parsed.event === "cancelled") {
          console.error(`[SSE] Error at +${elapsed}s:`, parsed.data?.error);
          setError(String(parsed.data?.error || "Unknown error"));
          clearReconnectTimer();
          setIsConnected(false);
          closeSource();
        } else if (parsed.event === "timeout") {
          console.warn(`[SSE] Timeout at +${elapsed}s — stream disconnected, polling will continue`);
          setIsConnected(false);
          closeSource();
        }
      } catch {
        console.warn(`[SSE +${elapsed}s] Failed to parse:`, e.data);
      }
    };

    source.onerror = (e) => {
      const elapsed = ((performance.now() - connectTimeRef.current) / 1000).toFixed(1);
      console.error(`[SSE +${elapsed}s] Connection error`, e);
      setIsConnected(false);
      closeSource();
      if (activeRunIdRef.current !== runId || reconnectAttemptsRef.current >= 5) return;

      reconnectAttemptsRef.current += 1;
      const delay = Math.min(8000, 500 * 2 ** (reconnectAttemptsRef.current - 1));
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connect(runId);
      }, delay);
    };
  }, [clearReconnectTimer, closeSource]);

  useEffect(() => {
    return () => {
      clearReconnectTimer();
      closeSource();
    };
  }, [clearReconnectTimer, closeSource]);

  return { events, isConnected, isDone, error, connect };
}
