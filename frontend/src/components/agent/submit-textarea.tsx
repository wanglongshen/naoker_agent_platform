"use client";

import React, { type KeyboardEvent, useEffect, useRef } from "react";

type Props = {
  name: string;
  className: string;
  placeholder: string;
  rows: number;
  required?: boolean;
  disabled?: boolean;
  autoFocus?: boolean;
  value?: string;
  onChange?: React.ChangeEventHandler<HTMLTextAreaElement>;
};

export default function SubmitTextarea(props: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { disabled, autoFocus, ...rest } = props;

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (disabled) return;

    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing &&
      !event.ctrlKey &&
      !event.metaKey
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  useEffect(() => {
    if (autoFocus && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [autoFocus]);

  return (
    <textarea
      ref={textareaRef}
      {...rest}
      disabled={disabled}
      onKeyDown={handleKeyDown}
    />
  );
}
