"use client";

import { useEffect, useMemo, useState } from "react";

import { buildStepMap, describeEvent } from "@/lib/event-narrative";
import { agentApi } from "@/lib/agent-api";
import type { AgentRun, AgentRunEvent, AgentStep } from "@/types/agent";

type Props = {
  selectedRun: AgentRun | null;
};

type TimelineItem = {
  id: string;
  eventType: string;
  title: string;
  description: string;
  createdAt: string;
  payload: Record<string, unknown>;
};

function eventTitle(eventType: string): string {
  switch (eventType) {
    case "run_queued":
      return "已加入队列";
    case "run_started":
      return "开始执行";
    case "plan_created":
      return "生成计划";
    case "step_completed":
      return "完成一步执行";
    case "run_retry_scheduled":
      return "安排重试";
    case "run_retry_resumed":
      return "恢复执行";
    case "run_failed":
      return "执行失败";
    case "run_completed":
    case "run_succeeded":
      return "完成任务";
    default:
      return eventType;
  }
}

export default function LandingRunEventTimeline({ selectedRun }: Props) {
  const [events, setEvents] = useState<AgentRunEvent[]>([]);
  const [steps, setSteps] = useState<AgentStep[]>([]);

  useEffect(() => {
    if (!selectedRun) {
      setEvents([]);
      setSteps([]);
      return;
    }

    let cancelled = false;
    const runId = selectedRun.id;

    async function load() {
      try {
        const [latestEvents, stepsResponse] = await Promise.all([
          agentApi.getRunEvents(runId),
          agentApi.getAttemptSteps(runId, (selectedRun as Record<string, unknown>).current_attempt_id as string ?? "", 1, 50),
        ]);
        if (!cancelled) {
          setEvents(latestEvents);
          setSteps(stepsResponse.items);
        }
      } catch {
        if (!cancelled) {
          setEvents([]);
          setSteps([]);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [selectedRun]);

  const items = useMemo(() => {
    if (!selectedRun) {
      return [] as TimelineItem[];
    }

    const stepMap = buildStepMap(steps);

    return [...events]
      .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
      .map((event) => ({
        id: event.id,
        eventType: event.event_type,
        title: eventTitle(event.event_type),
        description: describeEvent(event, selectedRun, stepMap) ?? "该事件已记录，展开原始事件可查看完整结构。",
        createdAt: event.created_at,
        payload: event.payload,
      }));
  }, [events, selectedRun, steps]);

  return (
    <section className="landing-event-panel" aria-label="Agent Loop 事件流">
      <div className="landing-event-header">
        <div>
          <div className="section-eyebrow">系统记录</div>
          <h2>Agent Loop 事件流</h2>
          {selectedRun ? <div className="landing-event-current-run">当前任务：{selectedRun.goal}</div> : null}
        </div>
        <span className="section-hint">展示当前选中任务从启动到结束的全过程事件序列</span>
      </div>

      <div className="landing-event-list">
        {!selectedRun ? (
          <div className="empty-card">请选择一个任务以查看事件流。</div>
        ) : items.length === 0 ? (
          <div className="empty-card">当前任务还没有产生事件。</div>
        ) : (
          items.map((item, index) => (
            <article key={item.id} className="landing-event-timeline-item">
              <div className="landing-event-marker-column">
                <div className="landing-event-marker" />
                {index < items.length - 1 ? <div className="landing-event-line" /> : null}
              </div>
              <div className="landing-event-card">
                <div className="landing-event-item-top">
                  <div className="landing-event-title">{item.title}</div>
                  <span className={`status-pill landing-status-pill status-${selectedRun.status}`}>{selectedRun.status}</span>
                </div>
                <div className="landing-event-time">{item.createdAt}</div>
                <div className="landing-event-summary">{item.description}</div>
                <details className="landing-event-raw">
                  <summary>查看原始事件</summary>
                  <pre>{JSON.stringify({ event_type: item.eventType, payload: item.payload, created_at: item.createdAt }, null, 2)}</pre>
                </details>
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  );
}
