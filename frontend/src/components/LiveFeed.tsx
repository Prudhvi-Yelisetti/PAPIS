/**
 * Live activity feed panel.
 * Drop this into any page — it subscribes to the WebSocket and renders
 * a scrollable event stream with colour-coded badges and auto-scroll.
 */
import { useEffect, useRef } from "react";
import { useLiveFeed, type FeedStatus, type LiveEvent } from "../hooks/useLiveFeed";
import { sourceColor } from "../api";

interface Props {
  maxEvents?: number;
  autoScroll?: boolean;
}

export default function LiveFeed({ maxEvents = 40, autoScroll = true }: Props) {
  const { events, status, clear } = useLiveFeed(maxEvents);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [events, autoScroll]);

  return (
    <div className="live-feed">
      <div className="live-feed__header">
        <span className="live-feed__title">Live activity</span>
        <StatusDot status={status} />
        <button className="btn btn-ghost btn-sm" onClick={clear}>
          Clear
        </button>
      </div>

      <div className="live-feed__body">
        {events.length === 0 ? (
          <p className="muted live-feed__empty">
            {status === "connecting"
              ? "Connecting to event stream…"
              : "Waiting for package events…"}
          </p>
        ) : (
          /* Render newest-first list (events[0] = most recent) */
          [...events].reverse().map((ev, i) => (
            <EventRow key={`${ev.occurred_at}-${i}`} ev={ev} />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}


// ── sub-components ────────────────────────────────────────────────────────────

function EventRow({ ev }: { ev: LiveEvent }) {
  const time = new Date(ev.occurred_at).toLocaleTimeString();

  return (
    <div className="feed-row">
      <span className="feed-row__time mono">{time}</span>
      <EventTypeBadge type={ev.type} />
      {ev.package && (
        <span className="feed-row__pkg mono">{ev.package}</span>
      )}
      {ev.version && (
        <span className="feed-row__version muted">@{ev.version}</span>
      )}
      {ev.source && ev.source !== "unknown" && (
        <span
          className="source-pill feed-row__source"
          style={{ background: sourceColor(ev.source) }}
        >
          {ev.source}
        </span>
      )}
    </div>
  );
}

function EventTypeBadge({ type }: { type: string }) {
  const cfg: Record<string, { cls: string; label: string }> = {
    install           : { cls: "badge--green",  label: "install"   },
    remove            : { cls: "badge--red",    label: "remove"    },
    update            : { cls: "badge--blue",   label: "update"    },
    duplicate_attempt : { cls: "badge--yellow", label: "duplicate" },
    uv_sync           : { cls: "badge--blue",   label: "uv sync"   },
    connected         : { cls: "badge--green",  label: "connected" },
  };
  const { cls, label } = cfg[type] ?? { cls: "", label: type };
  return <span className={`badge ${cls} feed-row__badge`}>{label}</span>;
}

function StatusDot({ status }: { status: FeedStatus }) {
  const colors: Record<FeedStatus, string> = {
    connecting   : "var(--warning)",
    connected    : "var(--success)",
    disconnected : "var(--text2)",
    error        : "var(--danger)",
  };
  return (
    <span
      title={status}
      style={{
        display      : "inline-block",
        width        : 8,
        height       : 8,
        borderRadius : "50%",
        background   : colors[status],
        marginLeft   : 4,
        flexShrink   : 0,
      }}
    />
  );
}