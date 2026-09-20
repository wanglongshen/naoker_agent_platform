"use client";

import { useState } from "react";
import { LoadingOutlined } from "@ant-design/icons";

import { agentApi } from "@/lib/agent-api";
import type { AgentRun } from "@/types/agent";

type Props = {
  run: AgentRun;
  onSubmitted: () => Promise<void> | void;
};

export default function QuestionCard({ run, onSubmitted }: Props) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const questions = run.pending_questions ?? [];
  if (questions.length === 0) return null;

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await agentApi.answerPendingQuestions(run.id, answers);
      await onSubmitted();
    } catch {
      setError("提交失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="question-card">
      <div className="question-card-header">
        <span className="status-pill status-inline status-awaiting_question">
          等待回答
        </span>
        <span className="question-card-title">开工前先确认几个问题</span>
      </div>
      <div className="question-card-body">
        {questions.map((q, index) => (
          <div key={`${run.id}-q${index}`} className="question-card-item">
            <label className="question-card-label">
              <span className="question-card-index">{index + 1}</span>
              <span>
                <span className="question-card-question">{q.question}</span>
                {q.affects ? (
                  <span className="question-card-affects">影响：{q.affects}</span>
                ) : null}
              </span>
            </label>
            <textarea
              className="question-card-textarea"
              rows={2}
              placeholder="请输入回答…"
              value={answers[q.question] ?? ""}
              onChange={(e) =>
                setAnswers((current) => ({
                  ...current,
                  [q.question]: e.currentTarget.value,
                }))
              }
            />
          </div>
        ))}
      </div>
      {error ? (
        <div className="question-card-error" role="alert">
          {error}
        </div>
      ) : null}
      <div className="question-card-footer">
        <button
          type="submit"
          className="question-card-submit"
          disabled={submitting || Object.keys(answers).length === 0}
        >
          {submitting ? <LoadingOutlined /> : "提交并继续"}
        </button>
      </div>
    </form>
  );
}
