"use client";

import React from "react";

import AnswerActions from "@/components/agent/answer-actions";
import ProgressiveMarkdown from "@/components/agent/progressive-markdown";
import { isActivelyStreamingRun } from "@/lib/animation-eligibility";
import type { AgentRun } from "@/types/agent";

function classifyHref(href: string | undefined): { href: string; external: boolean } {
  if (!href) return { href: "", external: false };
  if (href.includes("\\")) return { href: "", external: false };
  try { new URL(href); } catch { return { href: "", external: false }; }
  const url = new URL(href);
  return ["http:", "https:", "mailto:"].includes(url.protocol)
    ? { href, external: true }
    : { href: "", external: false };
}

type AnswerDisplayStatus = "running" | "terminal" | "inactive";

export function normalizeAnswerDisplayStatus(status: string): AnswerDisplayStatus {
  if (status === "running") return "running";
  if (["succeeded", "completed", "failed", "cancelled"].includes(status)) return "terminal";
  return "inactive";
}

function extractFinalAnswer(run: AgentRun): string | null {
  const value = (run as Record<string, unknown>).result as Record<string, unknown> | undefined;
  const answer = value?.final_answer;
  return typeof answer === "string" && answer.trim() ? answer : null;
}

export function shouldAnimateFinalAnswer(run: AgentRun, streamingAnswer: string, answerStreamId: string | null, isLiveRun = true): boolean {
  return isActivelyStreamingRun(run.status, isLiveRun) &&
    (Boolean(streamingAnswer.trim()) || Boolean(answerStreamId));
}

export default function FinalAnswerPanel({
  run,
  streamingAnswer = "",
  answerStreamId = null,
  isLiveRun = true,
  wasLiveStreamed = false,
  onRegenerate,
}: {
  run: AgentRun;
  streamingAnswer?: string;
  answerStreamId?: string | null;
  isLiveRun?: boolean;
  wasLiveStreamed?: boolean;
  onRegenerate?: () => void;
}) {
  const finalAnswer = extractFinalAnswer(run);
  const streamedAnswer = streamingAnswer.trim() ? streamingAnswer : null;
  const shouldAnimate = shouldAnimateFinalAnswer(run, streamingAnswer, answerStreamId, isLiveRun);
  const answerToRender = shouldAnimate
    ? streamedAnswer ?? finalAnswer
    : finalAnswer ?? streamedAnswer;
  const renderedAnswer = answerToRender;
  if (answerStreamId && !streamedAnswer && !renderedAnswer) {
    return (
      <section className="final-answer-panel">
        <div className="final-answer-loading">
          <span className="final-answer-loading-dot">正在生成回答</span>
        </div>
      </section>
    );
  }

  if (renderedAnswer || run.status === "succeeded") {
    const answerText = renderedAnswer ?? "";
    const isTerminal = !shouldAnimate;
    const displayText = shouldAnimate ? (renderedAnswer ?? "") : answerText;
    return (
      <section className="final-answer-panel" aria-labelledby={`answer-heading-${run.id}`}>
        <h2 id={`answer-heading-${run.id}`} className="sr-only">最终回答</h2>
        {answerText ? (
          <div className="final-answer-prose" aria-live={shouldAnimate ? "polite" : "off"} data-streaming={shouldAnimate ? "true" : "false"}>
            <ProgressiveMarkdown text={displayText} terminal={isTerminal} animateOnTerminal={wasLiveStreamed} />
          </div>
        ) : (
          <div className="final-answer-panel-empty">
            <div className="final-answer-placeholder-title">本次任务已完成</div>
            <div className="final-answer-placeholder-text">但没有返回可展示的最终回答。</div>
          </div>
        )}
        {isTerminal && answerText.trim() ? (
          <div className="answer-actions-row">
            <AnswerActions ownerId={run.id} text={answerText} sessionId={run.session_id} onRegenerate={onRegenerate ?? (() => {})} />
          </div>
        ) : null}
      </section>
    );
  }

  if (run.status === "retry_wait") {
    return (
      <section className="final-answer-panel">
        <div className="final-answer-panel-empty">
          <div className="final-answer-placeholder-title">正在重试</div>
          <div className="final-answer-placeholder-text">
            系统将在数秒后自动恢复执行。
          </div>
        </div>
      </section>
    );
  }

  if (run.status === "failed") {
    const isTimeout = run.failure_code === "run_timeout_exceeded";
    return (
      <section className="final-answer-panel">
        <div className="final-answer-panel-empty">
          <div className="final-answer-placeholder-title">
            {isTimeout ? "执行超时，任务未完成" : "本次任务未成功生成最终回答"}
          </div>
          <div className="final-answer-placeholder-text">
            {isTimeout
              ? "任务执行超过时间上限，已完成的步骤结果仍然保留；可重试或简化任务。"
              : "请查看上方思考过程与下方执行状态，必要时可重试任务。"}
          </div>
        </div>
      </section>
    );
  }

  if (run.status === "cancelled") {
    return (
      <section className="final-answer-panel">
        <div className="final-answer-panel-empty">
          <div className="final-answer-placeholder-title">任务已取消</div>
        </div>
      </section>
    );
  }

  return null;
}
