"use client";

import { useMemo, useState } from "react";

import type { AgentRunEvent, AgentStep } from "@/types/agent";

type Props = {
  steps: AgentStep[];
  events: AgentRunEvent[];
};

function formatActionLabel(actionType: string): string {
  return actionType === "http_request" ? "智能检索" : actionType;
}

export default function ThoughtProcess({ steps, events }: Props) {
  const [expanded, setExpanded] = useState(true);

  const thinkingEvents = useMemo(
    () => events.filter((event) => event.event_type === "plan_created"),
    [events]
  );

  const items = useMemo(() => {
    const eventMap = new Map<number, AgentRunEvent>();
    for (const event of thinkingEvents) {
      const stepIndex = Number(event.payload.step_index);
      if (!Number.isNaN(stepIndex)) {
        eventMap.set(stepIndex, event);
      }
    }

    return steps.map((step) => ({
      step,
      thought: String(eventMap.get(step.step_number)?.payload.thought_summary ?? step.thought_summary),
    }));
  }, [steps, thinkingEvents]);

  return (
    <section className="thought-process-block">
      <button type="button" className="thought-process-header" onClick={() => setExpanded((value) => !value)}>
        <div className="thought-process-header-left">
          <span className="thought-process-icon">&loz;</span>
          <span className="thought-process-title">已思考</span>
          <span className="thought-process-duration">展示执行推理与中间过程</span>
        </div>
        <span className="thought-process-toggle">{expanded ? "\u2304" : "\u203a"}</span>
      </button>

      {expanded ? (
        <div className="thought-process-content">
          {items.length === 0 ? (
            <div className="empty-card">任务尚未产生执行步骤。</div>
          ) : (
            items.map(({ step, thought }) => (
              <div key={step.id} className="thought-process-item">
                <div className="thought-process-line" />
                <div className="thought-process-body">
                  <div className="thought-process-summary">{thought}</div>
                  <div className="thought-process-meta">
                    第 {step.step_number + 1} 步 &middot; {formatActionLabel(step.action_type ?? "")} &middot; {step.status}
                  </div>
                  <div className="thought-process-panels">
                    <div className="thought-subsection">
                      <div className="thought-subtitle">动作参数</div>
                      <pre>{JSON.stringify(step.action_payload, null, 2)}</pre>
                    </div>
                    <div className="thought-subsection">
                      <div className="thought-subtitle">观察结果</div>
                      <pre>{JSON.stringify(step.observation, null, 2)}</pre>
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      ) : null}
    </section>
  );
}
