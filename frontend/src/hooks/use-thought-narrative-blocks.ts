"use client";

import { useMemo } from "react";
import type { AgentRunEvent } from "@/types/agent";
import type { ThoughtNarrativeBlock } from "@/lib/thought-narrative";
import { buildThoughtNarrativeBlocks } from "@/lib/thought-narrative";

export default function useThoughtNarrativeBlocks(
  events: AgentRunEvent[],
): ThoughtNarrativeBlock[] {
  return useMemo(() => buildThoughtNarrativeBlocks(events), [events]);
}
