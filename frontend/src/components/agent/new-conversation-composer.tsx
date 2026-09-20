"use client";

import React from "react";

import ChatComposer from "@/components/agent/chat-composer";
import type { PendingFile } from "@/components/agent/attachment-input";

type Props = {
  action: (formData: FormData) => void | Promise<void>;
  sessionId?: string;
  pendingFiles?: PendingFile[];
  onPendingFilesChange?: (files: PendingFile[]) => void;
};

export default function NewConversationComposer({ action, sessionId }: Props) {
  return (
    <ChatComposer
      sessionId={sessionId}
      placeholder="给 Agent Loop 发送消息"
      onSubmit={async ({ goal, attachmentIds }) => {
        const formData = new FormData();
        formData.set("goal", goal);
        formData.set("attachment_ids", attachmentIds.join(","));
        await action(formData);
      }}
    />
  );
}
