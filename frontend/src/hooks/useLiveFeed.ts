/**
 * Connects to the PAPIS WebSocket event feed at /ws/events.
 *
 * Returns:
 *   events   — rolling buffer of the last `maxEvents` events (newest first)
 *   status   — "connecting" | "connected" | "disconnected" | "error"
 *   clear    — empties the local event buffer
 *
 * Reconnects automatically with exponential back-off (1s → 2s → 4s … 30s cap).
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type FeedStatus = "connecting" | "connected" | "disconnected" | "error";

export interface LiveEvent {
  type: string;
  package?: string;
  source?: string;
  version?: string;
  occurred_at: string;
  clients?: number;
  [key: string]: unknown;
}

const WS_URL = "ws://127.0.0.1:8765/ws/events";

const MAX_RECONNECT_DELAY_MS = 30_000;

export function useLiveFeed(maxEvents = 50) {
  const [events, setEvents]   = useState<LiveEvent[]>([]);
  const [status, setStatus]   = useState<FeedStatus>("connecting");
  const wsRef                 = useRef<WebSocket | null>(null);
  const delayRef              = useRef(1000);
  const unmountedRef          = useRef(false);

  const connect = useCallback(() => {
    if (unmountedRef.current) return;
    setStatus("connecting");

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      delayRef.current = 1000;   // reset back-off on successful connect
    };

    ws.onmessage = (e: MessageEvent) => {
      try {
        const ev: LiveEvent = JSON.parse(e.data as string);
        if (ev.type === "ping") return;   // ignore keepalive frames
        setEvents(prev => [ev, ...prev].slice(0, maxEvents));
      } catch {
        // malformed frame — ignore
      }
    };

    ws.onerror = () => {
      setStatus("error");
    };

    ws.onclose = () => {
      if (unmountedRef.current) return;
      setStatus("disconnected");
      // Exponential back-off reconnect
      const delay = delayRef.current;
      delayRef.current = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS);
      setTimeout(connect, delay);
    };
  }, [maxEvents]);

  useEffect(() => {
    unmountedRef.current = false;
    connect();
    return () => {
      unmountedRef.current = true;
      wsRef.current?.close();
    };
  }, [connect]);

  const clear = useCallback(() => setEvents([]), []);

  return { events, status, clear };
}