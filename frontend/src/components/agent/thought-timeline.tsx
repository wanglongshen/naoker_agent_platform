"use client";

import { useMemo, useState } from "react";

import type { AgentRunEvent, AgentStep } from "@/types/agent";

function formatActionLabel(actionType: string): string {
  return actionType === "http_request" ? "智能检索" : actionType;
}

export default function ThoughtTimeline({ steps, events }: { steps: AgentStep[]; events: AgentRunEvent[] }) {
  const [expandedStepIds, setExpandedStepIds] = useState<Record<string, boolean>>({});
  const thinkingEvents = useMemo(
    () => events.filter((event) => event.event_type === "plan_created"),
    [events]
  );

  const thoughtMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const event of thinkingEvents) {
      const stepIndex = Number(event.payload.step_index);
      const thought = String(event.payload.thought_summary ?? "");
      if (!Number.isNaN(stepIndex) && thought) {
        map.set(stepIndex, thought);
      }
    }
    return map;
  }, [thinkingEvents]);

  return (
    <section className="thinking-inline-block">
      <div className="thinking-inline-header">
        <span className="thinking-inline-title">已思考</span>
        <span className="thinking-inline-subtitle">展示 agent 的每一步思考摘要与执行结果</span>
      </div>

      <div className="thinking-inline-list">
        {steps.length === 0 ? (
          <div className="empty-card">任务尚未产生执行步骤。</div>
        ) : (
          steps.map((step) => {
            const expanded = expandedStepIds[step.id] ?? false;
            const thought = thoughtMap.get(step.step_number) ?? step.thought_summary;

            return (
              <article key={step.id} className="thought-inline-item">
                <button
                  type="button"
                  className="thought-inline-toggle"
                  onClick={() => setExpandedStepIds((prev) => ({ ...prev, [step.id]: !expanded }))}
                >
                  <div>
                    <div className="thought-inline-meta">第 {step.step_number + 1} 步 &middot; {formatActionLabel(step.action_type ?? "")} &middot; {step.status}</div>
                    <div className="thought-inline-summary">{thought}</div>
                  </div>
                  <span className="thought-toggle">{expanded ? "收起" : "展开"}</span>
                </button>

                {expanded ? (
                  <div className="thought-inline-body">
                    <div className="thought-subsection">
                      <div className="thought-subtitle">动作参数</div>
                      <pre>{JSON.stringify(step.action_payload, null, 2)}</pre>
                    </div>
                    <div className="thought-subsection">
                      <div className="thought-subtitle">观察结果</div>
                      <pre>{JSON.stringify(step.observation, null, 2)}</pre>
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
