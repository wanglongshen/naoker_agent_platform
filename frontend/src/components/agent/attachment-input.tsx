"use client";

import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { formatFileSize, getFileFormatLabel, getFileTypeIconKey, type FileTypeIconKey } from "@/lib/file-card-meta";

export type PendingFile = { file: File; key: string };

export type AttachmentInputHandle = {
  addFiles: (files: File[]) => string | null;
};

const MAX_FILES = 10;
const MAX_BYTES = 20_000_000;

let keyCounter = 0;
function nextKey() { return `pending-${++keyCounter}`; }

function FileTypeIcon({ type }: { type: FileTypeIconKey }) {  const common = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (type) {
    case "text":
      return (
        <svg aria-hidden="true" {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M8 13h8M8 17h5" />
        </svg>
      );
    case "doc":
      return (
        <svg aria-hidden="true" {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M12 18v-6M9 15h6" />
        </svg>
      );
    case "pdf":
      return (
        <svg aria-hidden="true" {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M9 12v6M9 12a2 2 0 0 1 2-2h1v6h-1a2 2 0 0 1-2-2z" />
        </svg>
      );
    case "image":
      return (
        <svg aria-hidden="true" {...common}>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <circle cx="9" cy="10" r="2" />
          <path d="m5 19 5-5 3 3 4-4 2 2" />
        </svg>
      );
    default:
      return (
        <svg aria-hidden="true" {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
        </svg>
      );
  }
}

interface AttachmentInputProps {
  pendingFiles?: PendingFile[];
  onPendingFilesChange?: (files: PendingFile[]) => void;
}

const AttachmentInput = forwardRef<AttachmentInputHandle, AttachmentInputProps>(function AttachmentInput(
  { pendingFiles, onPendingFilesChange },
  ref,
) {
  const [localPending, setLocalPending] = useState<PendingFile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const pendingInputRef = useRef<HTMLInputElement>(null);

  const files = pendingFiles ?? localPending;
  const setFiles = onPendingFilesChange ?? setLocalPending;

  useEffect(() => {
    const form = pendingInputRef.current?.form;
    if (!form) return;
    const clear = () => {
      setFiles([]);
      setError(null);
    };
    form.addEventListener("reset", clear);
    return () => form.removeEventListener("reset", clear);
  }, [setFiles]);

  const addFiles = (incoming: File[]): string | null => {
    if (incoming.length === 0) return null;
    const remaining = MAX_FILES - files.length;
    if (remaining <= 0) {
      const message = `最多上传 ${MAX_FILES} 个文件`;
      setError(message);
      return message;
    }
    const tooLarge = incoming.find((file) => file.size > MAX_BYTES);
    if (tooLarge) {
      const message = `${tooLarge.name} 超过 20 MB`;
      setError(message);
      return message;
    }
    const accepted = incoming.slice(0, remaining);
    const newFiles: PendingFile[] = accepted.map((file) => ({ file, key: nextKey() }));
    if (newFiles.length > 0) {
      setError(null);
      setFiles([...files, ...newFiles]);
    }
    return null;
  };

  useImperativeHandle(ref, () => ({ addFiles }));

  function handlePendingFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.currentTarget.files;
    if (!selected || selected.length === 0) return;
    addFiles(Array.from(selected));
    event.currentTarget.value = "";
  }

  return (
    <div className="composer-attachment-wrap">
      <button type="button" className="composer-attachment-button" aria-label="添加附件" onClick={() => pendingInputRef.current?.click()}>
        <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21.4 11.6 12 21a6 6 0 0 1-8.5-8.5l10-10a4 4 0 0 1 5.7 5.7l-10 10a2 2 0 0 1-2.9-2.8l9.4-9.4" />
        </svg>
        <span className="composer-attachment-tooltip" role="tooltip">
          支持拖拽或选择文件
          <small>最多 10 个，单个 20 MB</small>
        </span>
      </button>
      <input
        ref={pendingInputRef}
        type="file"
        name="attachments"
        multiple
        hidden
        onChange={handlePendingFiles}
      />
      {error ? <div role="alert" className="composer-attachment-error">{error}</div> : null}
    </div>
  );
});

export function FileCardGrid({
  files,
  onRemove,
}: {
  files: PendingFile[];
  onRemove: (key: string) => void;
}) {
  if (files.length === 0) return null;
  return (
    <div className="composer-file-card-grid" aria-label="已选择附件">
      {files.map(({ file, key }) => (
        <div key={key} className="composer-file-card" title={file.name}>
          <span className="composer-file-card-icon" data-file-icon={getFileTypeIconKey(file)}>
            <FileTypeIcon type={getFileTypeIconKey(file)} />
          </span>
          <div className="composer-file-card-body">
            <div className="composer-file-card-name">{file.name}</div>
            <div className="composer-file-card-meta">
              {getFileFormatLabel(file)} · {formatFileSize(file.size)}
            </div>
          </div>
          <button
            type="button"
            className="composer-file-card-remove"
            aria-label={`移除 ${file.name}`}
            onClick={() => onRemove(key)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

export default AttachmentInput;
