"use client";

import { useEffect, useRef } from "react";

const BOTTOM_THRESHOLD_PX = 40;

function scrollToBottom<T extends HTMLElement>(el: T) {
  if (typeof el.scrollTo === "function") {
    el.scrollTo({ top: el.scrollHeight });
  } else {
    el.scrollTop = el.scrollHeight;
  }
}

export function useSmartAutoScroll<T extends HTMLElement>(
  ref: React.RefObject<T | null>,
  deps: unknown[],
): { reset: () => void } {
  const shouldFollowRef = useRef(true);
  const isFirstRunRef = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onScroll = () => {
      const nearBottom =
        el.scrollTop + el.clientHeight >= el.scrollHeight - BOTTOM_THRESHOLD_PX;
      shouldFollowRef.current = nearBottom;
    };
    const onPointerDown = () => {
      shouldFollowRef.current = false;
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    el.addEventListener("mousedown", onPointerDown, true);
    el.addEventListener("touchstart", onPointerDown, {
      passive: true,
      capture: true,
    });
    return () => {
      el.removeEventListener("scroll", onScroll);
      el.removeEventListener("mousedown", onPointerDown, true);
      el.removeEventListener("touchstart", onPointerDown, {
        capture: true,
      } as EventListenerOptions);
    };
  }, [ref]);

  useEffect(() => {
    if (isFirstRunRef.current) {
      isFirstRunRef.current = false;
      return;
    }
    const el = ref.current;
    if (el && shouldFollowRef.current) {
      scrollToBottom(el);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const reset = () => {
    shouldFollowRef.current = true;
    const el = ref.current;
    if (el) {
      scrollToBottom(el);
    }
  };

  return { reset };
}
