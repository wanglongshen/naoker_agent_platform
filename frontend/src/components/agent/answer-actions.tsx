"use client";

import React, { useEffect, useRef, useState } from "react";
import AnswerSpeechButton from "@/components/agent/answer-speech-button";
import { readAnswerFeedback, writeAnswerFeedback, shareAnswer, type AnswerFeedback } from "@/lib/answer-feedback";

function CopyIcon() {
  return (
    <svg aria-hidden="true" width="21" height="21" viewBox="0 0 21 21" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
      <rect x="7" y="7" width="11" height="11" rx="1.3" />
      <path d="M4 14H3.4C2.5 14 2 13.5 2 12.6V3.4C2 2.5 2.5 2 3.4 2h9.2C13.5 2 14 2.5 14 3.4V4" />
    </svg>
  );
}

function SpeechIcon() {
  return (
    <svg aria-hidden="true" width="21" height="21" viewBox="0 0 21 21" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
      <polygon points="9 4 5 7.3 2 7.3 2 13.7 5 13.7 9 17 9 4" />
      <path d="M15.5 4a8.2 8.2 0 0 1 0 13M12.5 7.4a4.1 4.1 0 0 1 0 6.2" />
    </svg>
  );
}

function RegenerateIcon() {
  return (
    <svg aria-hidden="true" width="21" height="21" viewBox="0 0 21 21" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
      <path d="M3.5 10.5a7 7 0 0 1 12.9-3.2L17.5 8.5" />
      <path d="M17.5 3.5v5h-5" />
      <path d="M17.5 10.5a7 7 0 0 1-12.9 3.2L3.5 12.5" />
      <path d="M3.5 17.5v-5h5" />
    </svg>
  );
}

function LikeIcon() {
  return (
    <svg aria-hidden="true" width="21" height="21" viewBox="0 0 21 21" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6.5 9.3h-3a1 1 0 0 0-1 1v7.5a1 1 0 0 0 1 1h3" />
      <path d="M6.5 9.3V17a1.1 1.1 0 0 0 .4.9l3.7 3.1c.7.6 1.7.2 1.8-.7l.5-3.6h4.2c1.3 0 2.2-1.2 1.8-2.4l-1.8-5.4c-.3-.9-1-1.4-2-1.4H10.2" />
    </svg>
  );
}

function DislikeIcon() {
  return (
    <svg aria-hidden="true" width="21" height="21" viewBox="0 0 21 21" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.5 11.7h3a1 1 0 0 0 1-1V3.2a1 1 0 0 0-1-1h-3" />
      <path d="M14.5 11.7V4a1.1 1.1 0 0 0-.4-.9L10.4 0c-.7-.6-1.7-.2-1.8.7L8.1 4.3H3.9c-1.3 0-2.2 1.2-1.8 2.4l1.8 5.4c.3.9 1 1.4 2 1.4h5.1" />
    </svg>
  );
}

function ShareIcon() {
  return (
    <svg aria-hidden="true" width="21" height="21" viewBox="0 0 21 21" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.5 2.5v12" />
      <path d="M6.5 6.5l4-4 4 4" />
      <path d="M4.5 9.5v5.5a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V9.5" />
    </svg>
  );
}

type Props = {
  ownerId: string;
  text: string;
  sessionId: string;
  onRegenerate: (() => void) | (() => Promise<void>);
};

export default function AnswerActions({ ownerId, text, sessionId, onRegenerate }: Props) {
  const [copied, setCopied] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<AnswerFeedback>(() => readAnswerFeedback(ownerId));
  const feedbackRef = useRef(feedback);
  feedbackRef.current = feedback;

  useEffect(() => {
    setFeedback(readAnswerFeedback(ownerId));
  }, [ownerId]);

  const hasText = text.trim().length > 0;

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // clipboard unavailable; ignore
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  async function handleLike() {
    const next = feedback === "like" ? null : "like";
    writeAnswerFeedback(ownerId, next);
    setFeedback(next);
  }

  async function handleDislike() {
    const next = feedback === "dislike" ? null : "dislike";
    writeAnswerFeedback(ownerId, next);
    setFeedback(next);
  }

  async function handleShare() {
    try {
      const url = `${window.location.origin}/agent/sessions/${sessionId}`;
      const result = await shareAnswer({ text, url });
      setStatus(result === "shared" ? "已转发" : "已复制链接");
      setTimeout(() => setStatus(null), 2000);
    } catch {
      setStatus("转发失败");
      setTimeout(() => setStatus(null), 2000);
    }
  }

  async function handleRegenerate() {
    if (regenerating) return;
    setRegenerating(true);
    try {
      await onRegenerate();
    } catch {
      setStatus("再生失败");
      setTimeout(() => setStatus(null), 2000);
    } finally {
      setRegenerating(false);
    }
  }

  return (
    <div className="answer-actions">
      <button
        type="button"
        className="answer-icon-action"
        aria-label="复制回答"
        title="复制回答"
        onClick={copy}
      >
        <CopyIcon />
      </button>

      <AnswerSpeechButton ownerId={ownerId} text={text} />

      {hasText ? (
        <button
          type="button"
          className="answer-icon-action"
          aria-label="重新生成回答"
          title="重新生成回答"
          onClick={handleRegenerate}
          disabled={regenerating}
        >
          <RegenerateIcon />
        </button>
      ) : null}

      {hasText ? (
        <button
          type="button"
          className={`answer-icon-action${feedback === "like" ? " is-selected" : ""}`}
          aria-label="赞回答"
          title="赞回答"
          onClick={handleLike}
        >
          <LikeIcon />
        </button>
      ) : null}

      {hasText ? (
        <button
          type="button"
          className={`answer-icon-action${feedback === "dislike" ? " is-selected" : ""}`}
          aria-label="不喜欢回答"
          title="不喜欢回答"
          onClick={handleDislike}
        >
          <DislikeIcon />
        </button>
      ) : null}

      {hasText ? (
        <button
          type="button"
          className="answer-icon-action"
          aria-label="转发回答"
          title="转发回答"
          onClick={handleShare}
        >
          <ShareIcon />
        </button>
      ) : null}

      {copied || status ? (
        <div className="answer-action-status" aria-live="polite">
          {copied ? "已复制" : status}
        </div>
      ) : null}
    </div>
  );
}
