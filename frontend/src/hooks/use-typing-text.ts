"use client";

import { useEffect, useRef, useState } from "react";

import { advanceTypingAnimation, createTypingAnimationState } from "@/lib/typing-animation";

export const DEFAULT_TYPING_SPEED_MS = 20;

export function advanceTypingText(displayedText: string, targetText: string): string {
  return advanceTypingAnimation(
    { displayedText, remainingMs: DEFAULT_TYPING_SPEED_MS },
    targetText, DEFAULT_TYPING_SPEED_MS, DEFAULT_TYPING_SPEED_MS,
  ).displayedText;
}

type UseTypingTextOptions = {
  speedMs?: number;
  resetKey?: string | number | null;
};

export function useTypingText(targetText: string, options: UseTypingTextOptions = {}): string {
  const { speedMs = DEFAULT_TYPING_SPEED_MS, resetKey = null } = options;
  const [displayedText, setDisplayedText] = useState(targetText);
  const isFirstRenderRef = useRef(true);
  const lastTickAtRef = useRef<number | null>(null);

  useEffect(() => {
    if (isFirstRenderRef.current) { isFirstRenderRef.current = false; return; }
    setDisplayedText("");
    lastTickAtRef.current = null;
  }, [resetKey]);

  useEffect(() => {
    setDisplayedText((current) => {
      if (!targetText) return "";
      if (targetText.length < current.length || !targetText.startsWith(current)) return "";
      return current;
    });
    if (!targetText) lastTickAtRef.current = null;
  }, [targetText]);

  useEffect(() => {
    if (displayedText === targetText) { lastTickAtRef.current = null; return; }
    const timer = window.setTimeout(() => {
      const now = Date.now();
      const previousTickAt = lastTickAtRef.current ?? now - speedMs;
      const elapsedMs = Math.max(now - previousTickAt, speedMs);
      setDisplayedText((current) => {
        const next = advanceTypingAnimation(
          { displayedText: current, remainingMs: speedMs }, targetText, elapsedMs, speedMs,
        ).displayedText;
        lastTickAtRef.current = now;
        return next;
      });
    }, speedMs);
    return () => { window.clearTimeout(timer); };
  }, [displayedText, speedMs, targetText]);

  return displayedText;
}
