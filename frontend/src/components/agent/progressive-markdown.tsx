"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  createTypingAnimationState,
  advanceTypingAnimation,
  type TypingAnimationState,
} from "@/lib/typing-animation";

const TYPING_SPEED_MS = 20;

function classifyHref(href: string | undefined): { href: string; external: boolean } {
  if (!href) return { href: "", external: false };
  if (href.includes("\\")) return { href: "", external: false };
  try {
    const url = new URL(href);
    return ["http:", "https:", "mailto:"].includes(url.protocol)
      ? { href, external: true }
      : { href: "", external: false };
  } catch {
    return { href: "", external: false };
  }
}

const mdComponents = {
  a: ({ href, children, ...props }: any) => {
    const { href: safeHref, external } = classifyHref(href);
    return (
      <a href={safeHref} {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})} {...props}>
        {children}
        {external ? <span className="sr-only">（在新标签页中打开）</span> : null}
      </a>
    );
  },
  table: ({ children, ...props }: any) => (
    <div className="table-scroll" tabIndex={0}><table {...props}>{children}</table></div>
  ),
  pre: ({ children, ...props }: any) => (
    <div className="code-scroll" tabIndex={0}><pre {...props}>{children}</pre></div>
  ),
};

const CompletedBlock = React.memo(
  function CompletedBlock({ content }: { content: string }) {
    return <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>{content}</ReactMarkdown>;
  },
  (prev, next) => prev.content === next.content,
);

function StreamingTail({ targetText, onComplete }: { targetText: string; onComplete?: () => void }) {
  const stateRef = useRef<TypingAnimationState>(createTypingAnimationState());
  const targetRef = useRef(targetText);
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef<number | null>(null);
  const frameCounterRef = useRef(0);
  const [displayed, setDisplayed] = useState("");

  useEffect(() => {
    targetRef.current = targetText;

    if (!targetText) {
      stateRef.current = createTypingAnimationState();
      setDisplayed("");
      return;
    }

    function tick(now: number) {
      const elapsed = lastTimeRef.current !== null ? now - lastTimeRef.current : TYPING_SPEED_MS;
      lastTimeRef.current = now;
      const next = advanceTypingAnimation(
        stateRef.current,
        targetRef.current,
        elapsed,
        TYPING_SPEED_MS,
      );
      stateRef.current = next;

      frameCounterRef.current += 1;
      if (frameCounterRef.current % 2 === 0) {
        setDisplayed(next.displayedText);
      }

      if (next.displayedText !== targetRef.current) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setDisplayed(next.displayedText);
        if (onComplete) onComplete();
      }
    }

    rafRef.current = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(rafRef.current);
  }, [targetText]);

  return (
    <span className="streaming-tail">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>
        {displayed}
      </ReactMarkdown>
      <span className="streaming-cursor">|</span>
    </span>
  );
}

export default function ProgressiveMarkdown({ text, terminal, animateOnTerminal = false }: { text: string; terminal: boolean; animateOnTerminal?: boolean }) {
  const [typedComplete, setTypedComplete] = useState(false);

  useEffect(() => {
    setTypedComplete(false);
  }, [text, terminal]);

  const { completed, active } = useMemo(() => {
    if (!text) return { completed: [] as string[], active: "" };
    if (terminal && (!animateOnTerminal || typedComplete)) return { completed: [text], active: "" };
    return { completed: [], active: text };
  }, [text, terminal, animateOnTerminal, typedComplete]);

  if (!text) return null;

  return (
    <>
      {completed.map((block, i) => (
        <CompletedBlock key={`${i}-${block.slice(0, 40)}`} content={block} />
      ))}
      {active ? (
        <StreamingTail
          targetText={active}
          onComplete={terminal ? () => setTypedComplete(true) : undefined}
        />
      ) : null}
    </>
  );
}
