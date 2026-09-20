"use client";

import React from "react";

import FinalAnswerPanel from "@/components/agent/final-answer-panel";
import ThoughtNarrative from "@/components/agent/thought-narrative";
import { useRunEventStream } from "@/hooks/use-run-event-stream";
import type { AgentRun, AgentRunEvent, AgentStep } from "@/types/agent";

type Props = {
  run: AgentRun;
  steps: AgentStep[];
  initialEvents: AgentRunEvent[];
};

export default function DetailConversation({ run, steps, initialEvents }: Props) {
  const streamState = useRunEventStream({ runId: run.id, initialEvents, initialRun: run });
  const streamedRun = streamState.run ?? run;

  return (
    <div className="detail-single-column-main">
      <div className="message-row message-row-user">
        <div className="message-bubble message-bubble-user">{run.goal}</div>
      </div>

      <ThoughtNarrative
        run={streamedRun}
        steps={steps.map((s) => ({ id: s.id, step_number: s.step_number, thought_summary: s.thought_summary ?? "", action_type: s.action_type ?? "", status: s.status }))}
        events={streamState.narrativeEvents}
      />
      <FinalAnswerPanel
        run={streamedRun}
        streamingAnswer={streamState.answerText}
        answerStreamId={streamState.answerStreamId}
      />
    </div>
  );
}
