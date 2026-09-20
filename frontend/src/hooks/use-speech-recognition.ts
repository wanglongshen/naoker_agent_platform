"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type SpeechRecognitionState =
  | "unsupported"
  | "idle"
  | "listening"
  | "error";

export type UseSpeechRecognitionResult = {
  state: SpeechRecognitionState;
  interimText: string;
  message: string | null;
  supported: boolean;
  start: () => void;
  stop: () => void;
  dispose: () => void;
};

export function useSpeechRecognition(options: {
  onFinalTranscript: (append: (currentText: string) => string) => void;
  disabled: boolean;
}): UseSpeechRecognitionResult {
  const { onFinalTranscript, disabled } = options;
  const onFinalRef = useRef(onFinalTranscript);
  onFinalRef.current = onFinalTranscript;

  const [state, setState] = useState<SpeechRecognitionState>(() =>
    isSpeechSupported() ? "idle" : "unsupported",
  );
  const [interimText, setInterimText] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const generationRef = useRef(0);
  const finalKeysRef = useRef<Set<string>>(new Set());
  const errorMessageRef = useRef<string | null>(null);

  function getCtor(): SpeechRecognitionConstructor | null {
    if (typeof window === "undefined") return null;
    return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
  }

  function isSpeechSupported(): boolean {
    if (typeof window === "undefined") return false;
    if ((window as any).isSecureContext === false) return false;
    return getCtor() !== null;
  }

  function invalidate(abort: boolean) {
    generationRef.current += 1;
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (recognition) {
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      if (abort) recognition.abort();
      else recognition.stop();
    }
    finalKeysRef.current.clear();
    setInterimText("");
    setState("idle");
  }

  const start = useCallback(() => {
    if (disabled) return;
    if (!isSpeechSupported()) return;

    invalidate(false);

    const Ctor = getCtor();
    if (!Ctor) return;

    try {
      const recognition = new Ctor();
      const generation = generationRef.current;
      errorMessageRef.current = null;

      recognition.lang = "zh-CN";
      recognition.continuous = false;
      recognition.interimResults = true;

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        if (
          generation !== generationRef.current ||
          recognitionRef.current !== recognition
        )
          return;

        let currentInterim = "";
        let hasFinal = false;
        const results = event.results;

        for (let i = event.resultIndex; i < results.length; i++) {
          const result = results[i];
          if (result.isFinal) {
            hasFinal = true;
            const transcript = result[0]?.transcript?.trim();
            if (!transcript) continue;

            const key = `${generation}:${i}:${transcript}`;
            if (finalKeysRef.current.has(key)) continue;
            finalKeysRef.current.add(key);

            const onFinal = onFinalRef.current;
            if (
              generation === generationRef.current &&
              recognitionRef.current === recognition
            ) {
              onFinal((current) => {
                const trimmed = current.trim();
                return trimmed ? `${trimmed} ${transcript}` : transcript;
              });
            }
          } else {
            const alt = result[0];
            if (alt?.transcript) {
              currentInterim += alt.transcript;
            }
          }
        }

        if (
          generation === generationRef.current &&
          recognitionRef.current === recognition
        ) {
          if (hasFinal) {
            setInterimText("");
          } else if (currentInterim) {
            setInterimText(currentInterim);
          }
        }
      };

      recognition.onend = () => {
        if (
          generation !== generationRef.current ||
          recognitionRef.current !== recognition
        )
          return;

        recognitionRef.current = null;
        setState("idle");
        setInterimText("");
      };

      recognition.onerror = (event: { error: string }) => {
        if (
          generation !== generationRef.current ||
          recognitionRef.current !== recognition
        )
          return;

        const messages: Record<string, string> = {
          "not-allowed": "浏览器未授予麦克风权限。",
          "service-not-allowed": "浏览器语音服务不可用。",
          "audio-capture": "未检测到可用麦克风。",
          network: "语音服务连接失败，请稍后重试。",
          "no-speech": "未识别到语音，请再试一次。",
        };

        const errorMsg = messages[event.error] || `语音识别错误：${event.error}`;
        errorMessageRef.current = errorMsg;
        setMessage(errorMsg);
        setState("error");
      };

      recognitionRef.current = recognition;
      recognition.start();
      setState("listening");
      setMessage(null);
    } catch (err) {
      const errorMsg =
        err instanceof Error
          ? `语音识别启动失败：${err.message}`
          : "语音识别启动失败。";
      setMessage(errorMsg);
      setState("error");
    }
  }, [disabled, state]);

  const stop = useCallback(() => {
    invalidate(false);
    if (errorMessageRef.current !== null) {
      setMessage(errorMessageRef.current);
    }
  }, []);

  const dispose = useCallback(() => {
    invalidate(true);
  }, []);

  // visibilitychange, pagehide, and unmount cleanup
  useEffect(() => {
    function onVisibilityChange() {
      if (document.hidden && recognitionRef.current) {
        invalidate(true);
      }
    }

    function onPageHide() {
      if (recognitionRef.current) {
        invalidate(true);
      }
    }

    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("pagehide", onPageHide);
      invalidate(true);
    };
  }, []);

  // Update state when supported status changes
  useEffect(() => {
    if (!isSpeechSupported()) {
      setState("unsupported");
    }
  }, []);

  return {
    state,
    interimText,
    message,
    supported: isSpeechSupported(),
    start,
    stop,
    dispose,
  };
}
