"use client";

import React, { useRef, useState, useCallback, useEffect } from "react";
import { LoadingOutlined } from "@ant-design/icons";

import AttachmentInput, { FileCardGrid, type AttachmentInputHandle, type PendingFile } from "@/components/agent/attachment-input";
import SubmitTextarea from "@/components/agent/submit-textarea";
import { useSpeechRecognition } from "@/hooks/use-speech-recognition";
import { agentApi } from "@/lib/agent-api";

function MicrophoneIcon({ active }: { active?: boolean }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" x2="12" y1="19" y2="22" />
      {active ? <line x1="8" x2="16" y1="23" y2="23" /> : null}
    </svg>
  );
}

function SendArrow() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="12" y1="19" x2="12" y2="5" />
      <polyline points="5 12 12 5 19 12" />
    </svg>
  );
}

export type ChatComposerProps = {
  sessionId?: string;
  placeholder: string;
  submitLabel?: string;
  onSubmit: (input: { goal: string; attachmentIds: string[] }) => Promise<void> | void;
  disabled?: boolean;
  autoFocus?: boolean;
  onFileCardsChange?: () => void;
  projectOptions?: { value: string; label: string }[];
  projectFolderId?: string | null;
  onProjectChange?: (value: string | null) => void;
};

export default function ChatComposer({
  sessionId,
  placeholder,
  submitLabel,
  onSubmit,
  disabled = false,
  autoFocus = false,
  onFileCardsChange,
  projectOptions,
  projectFolderId,
  onProjectChange,
}: ChatComposerProps) {
  const [pendingFiles, setPendingFiles] = React.useState<PendingFile[]>([]);
  const [uploading, setUploading] = React.useState(false);
  const [uploadError, setUploadError] = React.useState<string | null>(null);
  const [value, setValue] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const attachmentRef = useRef<AttachmentInputHandle>(null);
  const projectWrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!projectMenuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (projectWrapRef.current && !projectWrapRef.current.contains(e.target as Node)) {
        setProjectMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [projectMenuOpen]);

  const speech = useSpeechRecognition({
    disabled: disabled || uploading,
    onFinalTranscript: useCallback(
      (append) => setValue((current) => append(current)),
      [],
    ),
  });

  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;

    function onResize() {
      if (textareaRef.current && document.activeElement === textareaRef.current) {
        textareaRef.current.scrollIntoView({ block: "nearest" });
      }
    }

    viewport.addEventListener("resize", onResize);
    return () => viewport.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (pendingFiles.length > 0) {
      onFileCardsChange?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFiles]);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };
  const handleDragLeave = () => setIsDragOver(false);
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length > 0) attachmentRef.current?.addFiles(files);
  };

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    speech.stop();
    const goal = value.trim();
    if (!goal || disabled) return;

    if (pendingFiles.length > 0 && !sessionId) {
      setUploadError("请在会话中上传文件");
      return;
    }

    setUploading(true);
    setUploadError(null);
    try {
      const ids: string[] = [];
      if (sessionId) {
        for (const { file } of pendingFiles) {
          const formData = new FormData();
          formData.append("file", file);
          const attachment = await agentApi.uploadAttachment(sessionId, formData);
          ids.push(attachment.id);
        }
      }
      await onSubmit({
        goal,
        attachmentIds: ids,
      });
      setValue("");
      formRef.current?.reset();
      setPendingFiles([]);
    } catch {
      setUploadError("上传附件失败，请重试");
    } finally {
      setUploading(false);
    }
  }

  return (
    <form
      ref={formRef}
      onSubmit={handleSubmit}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`chat-composer${isDragOver ? " chat-composer-dragover" : ""}`}
    >
      <div className="chat-composer-panel">
        <FileCardGrid files={pendingFiles} onRemove={(key) => setPendingFiles(pendingFiles.filter((f) => f.key !== key))} />
        <div className="chat-composer-textarea-wrap">
          <SubmitTextarea
            name="goal"
            className="composer-textarea chat-composer-textarea"
            placeholder={placeholder}
            rows={2}
            disabled={disabled}
            autoFocus={autoFocus}
            value={value}
            onChange={(e) => setValue(e.currentTarget.value)}
          />
        </div>
        {speech.interimText && (
          <div className="composer-speech-interim" aria-hidden="true">
            {speech.interimText}
          </div>
        )}
        {speech.state === "error" && speech.message && (
          <div className="composer-speech-error" role="alert">
            {speech.message}
          </div>
        )}
        {uploadError && (
          <div className="composer-speech-error" role="alert">
            {uploadError}
          </div>
        )}
        <div className="chat-composer-toolbar">
          <div className="chat-composer-toolbar-left">
            {projectOptions && onProjectChange ? (
              <div className="composer-project-wrap" ref={projectWrapRef}>
                <button
                  type="button"
                  className="composer-project-capsule"
                  data-bound={projectFolderId ? "true" : "false"}
                  aria-label="选择项目"
                  aria-expanded={projectMenuOpen}
                  onClick={() => setProjectMenuOpen((open) => !open)}
                >
                  <span>📁</span>
                  <span>
                    {projectFolderId
                      ? projectOptions.find((o) => o.value === projectFolderId)?.label ?? "未绑定项目"
                      : "未绑定项目"}
                  </span>
                  <span style={{ fontSize: 9, opacity: 0.7 }}>▾</span>
                </button>
                {projectMenuOpen ? (
                  <div className="composer-project-menu" role="menu">
                    <div className="composer-project-menu-hint">选择项目（文件操作仅限所选项目）</div>
                    {projectOptions.map((o) => (
                      <div
                        key={o.value}
                        role="menuitem"
                        className={`composer-project-menu-item${projectFolderId === o.value ? " is-selected" : ""}`}
                        onClick={() => {
                          setProjectMenuOpen(false);
                          onProjectChange(o.value);
                        }}
                      >
                        <span>📁</span>
                        <span>{o.label}</span>
                        {projectFolderId === o.value ? <span className="composer-project-menu-check">✓</span> : null}
                      </div>
                    ))}
                    {projectOptions.length === 0 ? (
                      <div className="composer-project-menu-empty">还没有项目，请先在「我的文件」创建文件夹</div>
                    ) : null}
                    <div className="composer-project-menu-divider" />
                    <div
                      role="menuitem"
                      className="composer-project-menu-item composer-project-menu-unbind"
                      onClick={() => {
                        setProjectMenuOpen(false);
                        onProjectChange(null);
                      }}
                    >
                      <span>✕</span>
                      <span>解除绑定（全局）</span>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="chat-composer-toolbar-right">
            <AttachmentInput
              ref={attachmentRef}
              pendingFiles={pendingFiles}
              onPendingFilesChange={setPendingFiles}
            />
            {speech.supported && (
              <>
                <button
                  type="button"
                  className={`composer-voice-button${speech.state === "listening" ? " is-listening" : ""}`}
                  aria-label={speech.state === "listening" ? "停止语音输入" : "语音输入"}
                  aria-pressed={speech.state === "listening"}
                  aria-describedby="speech-input-status"
                  disabled={disabled || uploading}
                  onClick={speech.state === "listening" ? speech.stop : speech.start}
                >
                  <MicrophoneIcon active={speech.state === "listening"} />
                  <span>{speech.state === "listening" ? "正在聆听…" : "语音输入"}</span>
                </button>
                <span
                  id="speech-input-status"
                  className="sr-only"
                  aria-live="polite"
                >
                  {speech.message ?? (speech.state === "listening" ? "正在聆听" : "")}
                </span>
              </>
            )}
            {!speech.supported && (
              <span className="composer-speech-unsupported" id="speech-input-help">
                语音输入需要浏览器语音支持。
              </span>
            )}
            <button
              type="submit"
              className="composer-send-circle"
              aria-label="发送消息"
              disabled={disabled || uploading || !value.trim()}
            >
              {uploading ? <LoadingOutlined /> : <SendArrow />}
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}
