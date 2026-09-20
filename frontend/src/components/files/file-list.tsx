"use client";

import { useState } from "react";
import { Table, Button, Tag, Space, Typography } from "antd";
import {
  EyeOutlined,
  DownloadOutlined,
  SwapOutlined,
  EditOutlined,
  DeleteOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileImageOutlined,
  FileTextOutlined,
  FileExcelOutlined,
  FilePptOutlined,
  FileWordOutlined,
  FileZipOutlined,
  VideoCameraOutlined,
  AudioOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { FileListItem } from "@/types/file";
import type { CurrentUser } from "@/types/auth";

interface FileListProps {
  files: FileListItem[];
  loading: boolean;
  onRefresh: () => void;
  folderId: string;
  onPreview: (file: FileListItem) => void;
  onMove?: (file: FileListItem) => void;
  onRename?: (file: FileListItem) => void;
  onDelete?: (file: FileListItem) => void;
  onBatchDelete?: (ids: string[]) => void;
  currentUser: CurrentUser;
  adminView?: boolean;
  readOnly?: boolean;
}

const MEDIA_TYPE_COLORS: Record<string, string> = {
  document: "blue",
  image: "green",
  video: "purple",
  audio: "orange",
  archive: "red",
  spreadsheet: "cyan",
  presentation: "magenta",
  other: "default",
};

function getFileIcon(mediaType: string) {
  if (!mediaType) return <FileOutlined />;
  if (mediaType === "application/pdf") return <FilePdfOutlined />;
  if (mediaType.startsWith("image/")) return <FileImageOutlined />;
  if (mediaType.startsWith("video/")) return <VideoCameraOutlined />;
  if (mediaType.startsWith("audio/")) return <AudioOutlined />;
  if (mediaType.includes("spreadsheet") || mediaType.includes("excel")) return <FileExcelOutlined />;
  if (mediaType.includes("presentation") || mediaType.includes("powerpoint")) return <FilePptOutlined />;
  if (mediaType.includes("word") || mediaType.includes("document")) return <FileWordOutlined />;
  if (mediaType.includes("zip") || mediaType.includes("rar") || mediaType.includes("7z") || mediaType.includes("gzip") || mediaType.includes("tar")) return <FileZipOutlined />;
  if (mediaType.startsWith("text/")) return <FileTextOutlined />;
  return <FileOutlined />;
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const size = bytes / Math.pow(1024, i);
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function FileList({
  files, loading, onRefresh, onPreview, onMove, onRename, onDelete, onBatchDelete, currentUser, adminView, readOnly,
}: FileListProps) {
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [batchOpen, setBatchOpen] = useState(false);

  const columns: ColumnsType<FileListItem> = [
    {
      title: "文件名",
      dataIndex: "original_filename",
      key: "filename",
      render: (_fn: string, record: FileListItem) => (
        <Space>
          {getFileIcon(record.media_type)}
          <Typography.Text>{_fn}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "类型",
      dataIndex: "media_type",
      key: "media_type",
      width: 100,
      render: (mt: string) => {
        if (mt.startsWith("image/")) return <Tag color="green">图片</Tag>;
        if (mt.includes("pdf")) return <Tag color="red">PDF</Tag>;
        if (mt.includes("word") || mt.includes("document")) return <Tag color="blue">Word</Tag>;
        if (mt.includes("sheet") || mt.includes("excel")) return <Tag color="cyan">Excel</Tag>;
        if (mt.includes("presentation") || mt.includes("powerpoint")) return <Tag color="magenta">PPT</Tag>;
        if (mt.startsWith("video/")) return <Tag color="purple">视频</Tag>;
        if (mt.startsWith("audio/")) return <Tag color="orange">音频</Tag>;
        if (mt.includes("zip") || mt.includes("rar") || mt.includes("7z") || mt.includes("gzip") || mt.includes("tar")) return <Tag color="red">压缩包</Tag>;
        if (mt.startsWith("text/")) return <Tag>文本</Tag>;
        return <Tag>{mt.split("/")[1]?.toUpperCase() || mt}</Tag>;
      },
    },
    {
      title: "大小",
      dataIndex: "size_bytes",
      key: "size_bytes",
      width: 100,
      render: (size: number) => formatFileSize(size),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 170,
      render: (date: string) => formatDate(date),
    },
    {
      title: "操作",
      key: "actions",
      width: 240,
      render: (_: unknown, record: FileListItem) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => onPreview(record)}>预览</Button>
          <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => {
            const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
            const link = document.createElement("a");
            link.href = `${baseUrl}/api/files/${record.id}/download?download=1`;
            link.download = record.original_filename;
            link.click();
          }}>下载</Button>
          {!adminView && onMove && onRename && (
            <>
              <Button type="link" size="small" icon={<SwapOutlined />} onClick={() => onMove(record)}>移动</Button>
              <Button type="link" size="small" icon={<EditOutlined />} onClick={() => onRename(record)}>重命名</Button>
            </>
          )}
          {(!adminView || record.owner_user_id === currentUser.id) && onDelete && (
            <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => onDelete(record)}>删除</Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      {onBatchDelete && selectedRowKeys.length > 0 ? (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "8px 16px", background: "#fef0e5", borderBottom: "1px solid #f5e0cc",
        }}>
          <Typography.Text style={{ fontSize: 13 }}>
            已选 <Typography.Text strong style={{ color: "#D96313" }}>{selectedRowKeys.length}</Typography.Text> 个文件
          </Typography.Text>
          <Space>
            <Button size="small" onClick={() => setSelectedRowKeys([])}>取消选择</Button>
            <Button size="small" danger type="primary" icon={<DeleteOutlined />}
              onClick={() => {
                if (!batchOpen) {
                  setBatchOpen(true);
                  return;
                }
                onBatchDelete(selectedRowKeys.map(String));
                setSelectedRowKeys([]);
                setBatchOpen(false);
              }}>
              批量删除
            </Button>
          </Space>
        </div>
      ) : null}
      <Table<FileListItem>
        rowKey="id"
        columns={columns}
        dataSource={files}
        loading={loading}
        pagination={false}
        size="middle"
        rowSelection={readOnly ? undefined : {
          selectedRowKeys,
          onChange: (keys) => { setSelectedRowKeys(keys); setBatchOpen(false); },
        }}
      />
    </>
  );
}
