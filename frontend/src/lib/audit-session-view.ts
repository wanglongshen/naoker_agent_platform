import { agentApi } from "@/lib/agent-api";
import type { AuditSessionTranscript } from "@/types/agent";

export type AuditSessionView = AuditSessionTranscript & {
  warning?: string;
};

export async function loadAuditSessionView(sessionId: string): Promise<AuditSessionView> {
  const data = await agentApi.getAuditSessionTranscript(sessionId);

  if (!data.owner || !data.session || !Array.isArray(data.turns)) {
    return {
      ...data,
      warning: "audit transcript response missing required fields",
    };
  }

  if (data.turns.length > 0 && !data.turns[0].run.session_id) {
    return {
      ...data,
      warning: "audit transcript turn missing session association",
    };
  }

  return data;
}
