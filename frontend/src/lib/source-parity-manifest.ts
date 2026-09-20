export type SourceParityEntry = {
  source: string;
  target: string;
  copiedBeforeAdaptation: true;
  adaptations: string[];
};

export const agentLoopSourceParity: readonly SourceParityEntry[] = [
  {
    source: "X:\\01_agent_loop\\frontend\\app\\sessions\\[id]\\page.tsx",
    target: "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx",
    copiedBeforeAdaptation: true,
    adaptations: ["import", "API envelope", "succeeded", "attachment IDs", "/agent", "terminal refresh"],
  },
  {
    source: "X:\\01_agent_loop\\frontend\\components\\SessionConversationStream.tsx",
    target: "frontend/src/components/agent/session-conversation-stream.tsx",
    copiedBeforeAdaptation: true,
    adaptations: ["import", "succeeded"],
  },
  {
    source: "X:\\01_agent_loop\\frontend\\hooks\\useRunEventStream.ts",
    target: "frontend/src/hooks/use-run-event-stream.ts",
    copiedBeforeAdaptation: true,
    adaptations: ["import", "Cookie/CSRF", "terminal refresh"],
  },
  {
    source: "X:\\01_agent_loop\\frontend\\lib\\runStreamReducer.ts",
    target: "frontend/src/lib/run-stream-reducer.ts",
    copiedBeforeAdaptation: true,
    adaptations: ["import", "succeeded"],
  },
  {
    source: "X:\\01_agent_loop\\frontend\\components\\ThoughtNarrative.tsx",
    target: "frontend/src/components/agent/thought-narrative.tsx",
    copiedBeforeAdaptation: true,
    adaptations: ["import"],
  },
  {
    source: "X:\\01_agent_loop\\frontend\\components\\FinalAnswerPanel.tsx",
    target: "frontend/src/components/agent/final-answer-panel.tsx",
    copiedBeforeAdaptation: true,
    adaptations: ["import", "succeeded", "safe markdown"],
  },
  {
    source: "X:\\01_agent_loop\\frontend\\components\\ComposerForm.tsx",
    target: "frontend/src/components/agent/composer-form.tsx",
    copiedBeforeAdaptation: true,
    adaptations: ["import", "Cookie/CSRF"],
  },
  {
    source: "X:\\01_agent_loop\\frontend\\components\\SubmitTextarea.tsx",
    target: "frontend/src/components/agent/submit-textarea.tsx",
    copiedBeforeAdaptation: true,
    adaptations: ["import"],
  },
  {
    source: "X:\\01_agent_loop\\frontend\\components\\AttachmentInput.tsx",
    target: "frontend/src/components/agent/attachment-input.tsx",
    copiedBeforeAdaptation: true,
    adaptations: ["import", "attachment IDs"],
  },
];
