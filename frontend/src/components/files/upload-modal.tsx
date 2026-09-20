"use client";

import { useRef, useState } from "react";
import { Modal, Upload, Alert, Progress, Typography } from "antd";
import { InboxOutlined } from "@ant-design/icons";
import type { UploadFile, UploadProps } from "antd";
import { api, ApiError } from "@/lib/api";

const { Dragger } = Upload;

interface UploadModalProps {
  open: boolean;
  folderId: string;
  directory?: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export default function UploadModal({ open, folderId, directory = false, onClose, onSuccess }: UploadModalProps) {
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(0);
  const dirInputRef = useRef<HTMLInputElement>(null);

  function handleClose() {
    setFileList([]);
    setError("");
    setUploading(false);
    setProgress(0);
    onClose();
  }

  function handleFiles(files: FileList | File[]) {
    setError("");
    const items: UploadFile[] = Array.from(files).map((f, i) => ({
      uid: `${Date.now()}-${i}`,
      name: (f as any).webkitRelativePath || f.name,
      status: "done" as const,
      originFileObj: f as any,
    }));
    setFileList((prev) => [...prev, ...items]);
  }

  const uploadProps: UploadProps = {
    multiple: !directory,
    fileList,
    beforeUpload: () => false,
    onRemove: (file) => setFileList((prev) => prev.filter((f) => f.uid !== file.uid)),
    showUploadList: { showPreviewIcon: false },
    onChange: (info) => setFileList(info.fileList),
  };

  async function handleUpload() {
    if (fileList.length === 0) {
      setError("请选择要上传的文件。");
      return;
    }
    setUploading(true);
    setError("");
    setProgress(0);

    const formData = new FormData();
    if (folderId) formData.append("folder_id", folderId);
    fileList.forEach((file) => {
      const raw = (file as any).originFileObj ?? file;
      const relativePath = (file as any).webkitRelativePath || raw.webkitRelativePath || "";
      if (relativePath) {
        // 上传文件夹：文件名携带相对路径（如 "sub/dir/file.md"），后端据此重建目录结构
        formData.append("file", raw, relativePath);
      } else {
        formData.append("file", raw, raw.name || file.name);
      }
    });

    try {
      await api("/api/files/upload", { method: "POST", body: formData, csrf: true });
      setProgress(100);
      setTimeout(() => { handleClose(); onSuccess(); }, 400);
    } catch (err) {
      setError(err instanceof ApiError ? err.message || "上传失败" : "上传失败，请稍后重试。");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Modal
      title={directory ? "上传文件夹" : "上传文件"}
      open={open}
      onOk={handleUpload}
      onCancel={handleClose}
      okText={uploading ? "上传中..." : `开始上传 (${fileList.length} 个文件)`}
      cancelText="取消"
      confirmLoading={uploading}
      destroyOnHidden
      width={560}
    >
      {error ? <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} /> : null}

      {directory ? (
        <>
          {fileList.length === 0 ? (
            <div
              style={{ border: "2px dashed #d9e0ea", borderRadius: 12, padding: 40, textAlign: "center", cursor: "pointer" }}
              onClick={() => {
                const input = document.createElement("input");
                input.type = "file";
                (input as any).webkitdirectory = true;
                input.onchange = (e) => {
                  const files = (e.target as HTMLInputElement).files;
                  if (files) handleFiles(files);
                };
                input.click();
              }}
            >
              <InboxOutlined style={{ fontSize: 40, color: "#D96313", marginBottom: 12 }} />
              <p style={{ fontSize: 15, fontWeight: 500, color: "#172033" }}>点击选择文件夹</p>
              <p style={{ fontSize: 12, color: "#8b99ab", marginTop: 4 }}>将上传文件夹内的所有文件</p>
            </div>
          ) : (
            <Dragger {...uploadProps} directory>
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">拖拽文件夹到此区域</p>
              <p className="ant-upload-hint">将上传文件夹内的所有文件</p>
            </Dragger>
          )}
        </>
      ) : (
        <Dragger {...uploadProps}>
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p className="ant-upload-hint">支持 PDF、Word、Excel、PPT、文本、图片、视频、音频、压缩包等格式，魔术字节自动识别</p>
        </Dragger>
      )}

      {fileList.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            已选择 {fileList.length} 个文件
          </Typography.Text>
          {uploading ? <Progress percent={progress} size="small" style={{ marginTop: 4 }} /> : null}
        </div>
      ) : null}
    </Modal>
  );
}
