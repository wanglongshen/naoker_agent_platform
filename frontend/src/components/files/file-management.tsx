"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { hasPermission, FILE_UPLOAD, FILE_MANAGE_FOLDERS, FILE_ADMIN_VIEW } from "@/lib/permissions";
import { copy } from "@/lib/copy";
import type { CurrentUser } from "@/types/auth";
import type { FileListItem, FolderNode, FileListResponse, UserFolderGroup } from "@/types/file";
import PageHeader from "@/components/layout/page-header";
import DataSurface from "@/components/ui/data-surface";
import { Button, Alert, Empty, Pagination, Skeleton, Input, Select, Space, Layout } from "antd";
import { UploadOutlined, FolderAddOutlined, SearchOutlined, HistoryOutlined } from "@ant-design/icons";
import FolderTree from "./folder-tree";
import FileList from "./file-list";
import UploadModal from "./upload-modal";
import PreviewDrawer from "./preview-drawer";
import MoveModal from "./move-modal";
import FolderCreateModal from "./folder-create-modal";
import FolderRenameModal from "./folder-rename-modal";
import GenerationRecordsModal from "./generation-records-modal";
import ConfirmDialog from "@/components/users/confirm-dialog";

const { Sider, Content } = Layout;

interface FileManagementProps {
  currentUser: CurrentUser;
  adminView?: boolean;
}

const PAGE_SIZE = 20;

type DialogState =
  | { kind: "none" }
  | { kind: "upload" }
  | { kind: "uploadFolder" }
  | { kind: "preview"; file: FileListItem }
  | { kind: "move"; file: FileListItem }
  | { kind: "rename"; file: FileListItem }
  | { kind: "delete"; file: FileListItem }
  | { kind: "createFolder" }
  | { kind: "renameFolder"; folder: FolderNode }
  | { kind: "deleteFolder"; folder: FolderNode };

export default function FileManagement({ currentUser, adminView }: FileManagementProps) {
  const [files, setFiles] = useState<FileListItem[]>([]);
  const [folderTree, setFolderTree] = useState<FolderNode[]>([]);
  const [adminGroups, setAdminGroups] = useState<UserFolderGroup[] | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [folderId, setFolderId] = useState<string>("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [keyword, setKeyword] = useState("");
  const [mediaType, setMediaType] = useState("");
  const [loading, setLoading] = useState(true);
  const [treeLoading, setTreeLoading] = useState(true);
  const [userTreeLoading, setUserTreeLoading] = useState(true);
  const [error, setError] = useState("");
  const [mounted, setMounted] = useState(false);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [actionError, setActionError] = useState("");
  const [generationsOpen, setGenerationsOpen] = useState(false);

  const canUpload = hasPermission(currentUser, FILE_UPLOAD);
  const canManageFolders = hasPermission(currentUser, FILE_MANAGE_FOLDERS);

  const selectedUser = selectedUserId ?? currentUser.id;
  const ownView = !adminView || selectedUser === currentUser.id;

  const fetchFolders = useCallback(async () => {
    try {
      if (adminView) {
        const data = await api<UserFolderGroup[]>("/api/files/folders/admin");
        setAdminGroups(data);
      } else {
        const data = await api<FolderNode[]>("/api/files/folders");
        setFolderTree(data);
      }
    } catch {
      // silent fail for tree
    } finally {
      setTreeLoading(false);
      setUserTreeLoading(false);
    }
  }, [adminView]);

  const fetchFiles = useCallback(async (currentPage: number) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (adminView) {
        if (selectedUser) params.set("user_id", selectedUser);
        if (folderId) params.set("folder_id", folderId);
        if (keyword) params.set("keyword", keyword);
        if (mediaType) params.set("media_type", mediaType);
        params.set("page", String(currentPage));
        params.set("page_size", String(PAGE_SIZE));
        const data = await api<FileListResponse>(`/api/files/admin?${params.toString()}`);
        setFiles(data.items);
        setPage(data.page);
        setTotal(data.total);
      } else {
        if (folderId) params.set("folder_id", folderId);
        if (keyword) params.set("keyword", keyword);
        if (mediaType) params.set("media_type", mediaType);
        params.set("page", String(currentPage));
        params.set("page_size", String(PAGE_SIZE));
        const data = await api<FileListResponse>(`/api/files?${params.toString()}`);
        setFiles(data.items);
        setPage(data.page);
        setTotal(data.total);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.common.requestFailed);
    } finally {
      setLoading(false);
    }
  }, [adminView, folderId, keyword, mediaType, selectedUser]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (adminView && selectedUserId === null) {
      setSelectedUserId(currentUser.id);
    }
  }, [adminView, currentUser.id, selectedUserId]);

  useEffect(() => {
    if (!mounted) return;
    fetchFolders();
  }, [mounted, fetchFolders]);

  useEffect(() => {
    if (!mounted) return;
    fetchFiles(1);
  }, [mounted, fetchFiles]);

  function handleFolderSelect(folderId: string | null) {
    setFolderId(folderId ?? "");
  }

  function handleUserSelect(userId: string | null) {
    setSelectedUserId(userId);
    setFolderId("");
  }

  function handleSearch() {
    fetchFiles(1);
  }

  function handlePageChange(newPage: number) {
    fetchFiles(newPage);
  }

  function handleSuccess() {
    setActionError("");
    fetchFiles(page);
    fetchFolders();
  }

  function handlePreview(file: FileListItem) {
    setDialog({ kind: "preview", file });
  }

  function handleMove(file: FileListItem) {
    setDialog({ kind: "move", file });
  }

  function handleRename(file: FileListItem) {
    setDialog({ kind: "rename", file });
  }

  function handleDelete(file: FileListItem) {
    setDialog({ kind: "delete", file });
  }

  async function handleBatchDelete(ids: string[]) {
    if (ids.length === 0) return;
    setActionError("");
    try {
      await api("/api/files/batch", {
        method: "DELETE",
        body: JSON.stringify({ ids }),
        csrf: true,
      });
      handleSuccess();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "批量删除失败");
    }
  }

  function handleRenameFolder(folder: FolderNode) {
    setDialog({ kind: "renameFolder", folder });
  }

  function handleDeleteFolder(folder: FolderNode) {
    setDialog({ kind: "deleteFolder", folder });
  }

  const mediaTypeOptions = [
    { value: "", label: "全部类型" },
    { value: "document", label: "文档" },
    { value: "image", label: "图片" },
    { value: "video", label: "视频" },
    { value: "audio", label: "音频" },
    { value: "archive", label: "压缩包" },
    { value: "other", label: "其他" },
  ];

  if (loading && files.length === 0) {
    return (
      <div>
        <div className="page-hero">
          <PageHeader title={adminView ? copy.navigation.files : copy.navigation.myFiles} />
        </div>
        <div className="content">
          <DataSurface>
            <Skeleton active paragraph={{ rows: 8 }} />
          </DataSurface>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <div className="page-hero">
          <PageHeader title={adminView ? copy.navigation.files : copy.navigation.myFiles} />
        </div>
        <div className="content">
          <DataSurface>
            <Alert
              type="error"
              showIcon
              title={error}
              action={
                <Button size="small" onClick={() => fetchFiles(1)}>
                  {copy.common.retry}
                </Button>
              }
            />
          </DataSurface>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-hero">
        <PageHeader
          title={adminView ? copy.navigation.files : copy.navigation.myFiles}
          actions={
            <Space>
              {canUpload && ownView && (
                <>
                  <Button type="primary" icon={<UploadOutlined />} onClick={() => setDialog({ kind: "upload" })}>
                    上传文件
                  </Button>
                  <Button type="primary" icon={<UploadOutlined />} onClick={() => setDialog({ kind: "uploadFolder" })}>
                    上传文件夹
                  </Button>
                </>
              )}
              {canManageFolders && ownView && (
                <Button icon={<FolderAddOutlined />} onClick={() => setDialog({ kind: "createFolder" })}>
                  新建文件夹
                </Button>
              )}
              <Button icon={<HistoryOutlined />} onClick={() => setGenerationsOpen(true)}>
                生成记录
              </Button>
            </Space>
          }
        />
      </div>
      <div className="content">
        <Layout style={{ background: "transparent", gap: 16 }}>
          <Sider width={240} theme="light" style={{ background: "transparent", paddingRight: 16 }}>
            <FolderTree
              treeData={folderTree}
              selectedFolderId={folderId}
              loading={adminView ? userTreeLoading : treeLoading}
              onSelect={handleFolderSelect}
              rootLabel={currentUser.display_name || currentUser.username}
              onRenameFolder={ownView ? handleRenameFolder : undefined}
              onDeleteFolder={ownView ? handleDeleteFolder : undefined}
              adminGroups={adminView ? (adminGroups ?? undefined) : undefined}
              selectedUserId={adminView ? selectedUser : undefined}
              onSelectUser={handleUserSelect}
            />
          </Sider>
          <Content>
            <DataSurface>
              <div className="data-surface-toolbar">
                <Space wrap>
                  <Input
                    placeholder="搜索文件..."
                    prefix={<SearchOutlined />}
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    onPressEnter={handleSearch}
                    style={{ width: 200 }}
                    allowClear
                  />
                  <Select
                    value={mediaType}
                    onChange={(v) => setMediaType(v)}
                    options={mediaTypeOptions}
                    style={{ width: 120 }}
                  />
                  <Button onClick={handleSearch} type="primary">
                    {copy.common.search}
                  </Button>
                </Space>
              </div>
              {actionError ? <Alert type="error" showIcon title={actionError} /> : null}
              {files.length === 0 ? (
                <Empty description="暂无文件">
                  {canUpload && ownView && (
                    <Button type="primary" icon={<UploadOutlined />} onClick={() => setDialog({ kind: "upload" })}>
                      上传文件
                    </Button>
                  )}
                </Empty>
              ) : (
                <>
                  <FileList
                    files={files}
                    loading={loading}
                    onRefresh={handleSuccess}
                    folderId={folderId}
                    onPreview={handlePreview}
                    onMove={ownView ? handleMove : undefined}
                    onRename={ownView ? handleRename : undefined}
                    onDelete={ownView ? handleDelete : undefined}
                    onBatchDelete={ownView ? handleBatchDelete : undefined}
                    readOnly={adminView && !ownView}
                    currentUser={currentUser}
                    adminView={adminView}
                  />
                  <Pagination
                    current={page}
                    pageSize={PAGE_SIZE}
                    total={total}
                    onChange={handlePageChange}
                    showTotal={(total) => `共 ${total} 条`}
                    showSizeChanger={false}
                  />
                </>
              )}
            </DataSurface>
          </Content>
        </Layout>
      </div>

      <UploadModal
        open={dialog.kind === "upload"}
        folderId={folderId}
        onClose={() => setDialog({ kind: "none" })}
        onSuccess={handleSuccess}
      />

      <GenerationRecordsModal
        open={generationsOpen}
        folderId={folderId || null}
        onClose={() => setGenerationsOpen(false)}
      />

      <UploadModal
        open={dialog.kind === "uploadFolder"}
        folderId={folderId}
        directory
        onClose={() => setDialog({ kind: "none" })}
        onSuccess={handleSuccess}
      />

      <PreviewDrawer
        open={dialog.kind === "preview"}
        file={dialog.kind === "preview" ? dialog.file : null}
        onClose={() => setDialog({ kind: "none" })}
      />

      <MoveModal
        open={dialog.kind === "move"}
        file={dialog.kind === "move" ? dialog.file : null}
        treeData={folderTree}
        currentFolderId={folderId}
        onClose={() => setDialog({ kind: "none" })}
        onSuccess={handleSuccess}
      />

      <FolderCreateModal
        open={dialog.kind === "createFolder"}
        parentId={folderId}
        onClose={() => setDialog({ kind: "none" })}
        onSuccess={handleSuccess}
      />

      <FolderRenameModal
        open={dialog.kind === "renameFolder"}
        folderId={dialog.kind === "renameFolder" ? dialog.folder.id : ""}
        folderName={dialog.kind === "renameFolder" ? dialog.folder.name : ""}
        onClose={() => setDialog({ kind: "none" })}
        onSuccess={handleSuccess}
      />

      <ConfirmDialog
        open={dialog.kind === "deleteFolder"}
        title="删除文件夹"
        message={dialog.kind === "deleteFolder" ? `确认删除文件夹"${dialog.folder.name}"？该文件夹下的所有内容将一并删除，该操作不可撤销。` : ""}
        confirmLabel="删除"
        isDestructive
        onConfirm={async () => {
          if (dialog.kind !== "deleteFolder") return;
          try {
            await api(`/api/files/folders/${dialog.folder.id}`, { method: "DELETE", csrf: true });
            setDialog({ kind: "none" });
            handleSuccess();
          } catch (err) {
            setActionError(err instanceof Error ? err.message : "操作失败");
          }
        }}
        onClose={() => setDialog({ kind: "none" })}
      />

      <ConfirmDialog
        open={dialog.kind === "rename"}
        title="重命名文件"
        message={dialog.kind === "rename" ? `请输入"${dialog.file.original_filename}"的新名称：` : ""}
        confirmLabel="确认"
        onConfirm={async () => {
          if (dialog.kind !== "rename") return;
          // Rename handled inline via prompt
        }}
        onClose={() => setDialog({ kind: "none" })}
      />

      <ConfirmDialog
        open={dialog.kind === "delete"}
        title="删除文件"
        message={dialog.kind === "delete" ? `确认删除"${dialog.file.original_filename}"？该操作不可撤销。` : ""}
        confirmLabel="删除"
        isDestructive
        onConfirm={async () => {
          if (dialog.kind !== "delete") return;
          try {
            await api(`/api/files/${dialog.file.id}`, { method: "DELETE", csrf: true });
            setDialog({ kind: "none" });
            handleSuccess();
          } catch (err) {
            setActionError(err instanceof Error ? err.message : "操作失败");
          }
        }}
        onClose={() => setDialog({ kind: "none" })}
      />
    </div>
  );
}
