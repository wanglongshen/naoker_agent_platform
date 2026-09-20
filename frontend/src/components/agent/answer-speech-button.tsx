"use client";

import React, { useEffect, useState } from "react";
import { browserSpeech } from "@/lib/browser-speech";

type Props = {
  ownerId: string;
  text: string;
};

function SpeakerIcon() {
  return (
    <svg aria-hidden="true" width="21" height="21" viewBox="0 0 21 21" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
      <polygon points="9 4 5 7.3 2 7.3 2 13.7 5 13.7 9 17 9 4" />
      <path d="M15.5 4a8.2 8.2 0 0 1 0 13M12.5 7.4a4.1 4.1 0 0 1 0 6.2" />
    </svg>
  );
}

export default function AnswerSpeechButton({ ownerId, text }: Props) {
  const [speaking, setSpeaking] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    return () => {
      browserSpeech.stop(ownerId);
    };
  }, [ownerId]);

  if (!browserSpeech.supported()) return null;

  function toggle() {
    if (speaking) {
      browserSpeech.stop(ownerId);
      return;
    }
    setFailed(false);
    const started = browserSpeech.speak(
      ownerId,
      text,
      () => setSpeaking(false),
      () => setFailed(true),
    );
    setSpeaking(started);
  }

  return (
    <div className="answer-speech-control">
      <button
        type="button"
        className="answer-icon-action"
        aria-label={speaking ? "停止朗读" : "朗读回答"}
        title={speaking ? "停止朗读" : "朗读回答"}
        onClick={toggle}
      >
        <SpeakerIcon />
      </button>
      {failed ? (
        <span role="status" className="answer-speech-error">
          朗读不可用，请检查浏览器语音设置。
        </span>
      ) : null}
    </div>
  );
}
