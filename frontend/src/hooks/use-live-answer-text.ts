"use client";

import { useEffect, useRef, useState } from "react";

export function useLiveAnswerText(
  targetText: string,
  options: { enabled: boolean; resetKey: string | null },
): string {
  const { enabled, resetKey } = options;
  const [displayedText, setDisplayedText] = useState(enabled ? targetText : "");
  const pendingRef = useRef(false);
  const targetRef = useRef(targetText);
  const resetKeyRef = useRef(resetKey);

  useEffect(() => {
    if (resetKeyRef.current !== resetKey) {
      resetKeyRef.current = resetKey;
      pendingRef.current = false;
      targetRef.current = targetText;
      setDisplayedText(targetText);
      return;
    }
  }, [resetKey, targetText]);

  useEffect(() => {
    if (resetKeyRef.current !== resetKey) return;
    targetRef.current = targetText;
    if (!enabled) {
      setDisplayedText(targetText);
      return;
    }
    if (displayedText === targetText) return;
    if (pendingRef.current) return;
    pendingRef.current = true;
    const id = requestAnimationFrame(() => {
      pendingRef.current = false;
      setDisplayedText(targetRef.current);
    });
    return () => {
      cancelAnimationFrame(id);
      pendingRef.current = false;
    };
  }, [targetText, enabled, displayedText, resetKey]);

  return enabled ? displayedText : targetText;
}
