export type AnswerFeedback = "like" | "dislike" | null;

const KEY_PREFIX = "agent-answer-feedback:";
const feedbackKey = (runId: string) => `${KEY_PREFIX}${runId}`;

export function readAnswerFeedback(runId: string): AnswerFeedback {
  try {
    const value = window.localStorage.getItem(feedbackKey(runId));
    return value === "like" || value === "dislike" ? value : null;
  } catch {
    return null;
  }
}

export function writeAnswerFeedback(runId: string, next: AnswerFeedback): AnswerFeedback {
  try {
    if (next) {
      window.localStorage.setItem(feedbackKey(runId), next);
    } else {
      window.localStorage.removeItem(feedbackKey(runId));
    }
  } catch {
    /* storage unavailable - gracefully ignore */
  }
  return next;
}

export async function shareAnswer({ text, url }: { text: string; url: string }): Promise<"shared" | "copied"> {
  if (typeof navigator.share === "function") {
    await navigator.share({ text, url });
    return "shared";
  }
  await navigator.clipboard.writeText(url);
  return "copied";
}
