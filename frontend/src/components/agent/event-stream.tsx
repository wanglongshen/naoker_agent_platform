"use client";

import React, { useMemo } from "react";

import { useRunEventStream } from "@/hooks/use-run-event-stream";
import type { AgentRun, AgentRunEvent } from "@/types/agent";

type Props = {
  runId: string;
  initialEvents: AgentRunEvent[];
  initialRun?: AgentRun | null;
};

export default function EventStream({ runId, initialEvents, initialRun = null }: Props) {
  const streamState = useRunEventStream({ runId, initialEvents, initialRun });

  const sorted = useMemo(
    () => [...streamState.events].sort((a, b) => a.seq - b.seq),
    [streamState.events]
  );

  return (
    <section className="events-block events-block-secondary" aria-label="系统执行事件">
      <div className="section-title-row section-title-row-secondary">
        <div>
          <div className="section-eyebrow">系统记录</div>
          <h2>事件流</h2>
        </div>
        <span className="section-hint">展示系统级执行事件{streamState.connection === "open" ? "，实时更新中" : ""}</span>
      </div>
      <div className="events-list events-list-condensed">
        {sorted.map((eventItem) => (
          <div key={eventItem.id} className="event-row event-row-secondary">
            <div className="event-meta event-meta-secondary">
              <div className="event-type">{eventItem.event_type}</div>
              <div className="event-time">{eventItem.created_at}</div>
            </div>
            <pre className="event-payload event-payload-secondary">{JSON.stringify(eventItem.payload, null, 2)}</pre>
          </div>
        ))}
      </div>
    </section>
  );
}
