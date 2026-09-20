"use client";

import { useMemo, useRef, useState } from "react";
import { Tree, Skeleton, Dropdown, type TreeDataNode, type MenuProps } from "antd";
import { FolderOutlined, FolderOpenOutlined, HomeOutlined } from "@ant-design/icons";
import type { FolderNode, UserFolderGroup } from "@/types/file";

interface FolderTreeProps {
  treeData: FolderNode[];
  selectedFolderId: string;
  loading: boolean;
  onSelect: (folderId: string | null) => void;
  rootLabel?: string;
  onRenameFolder?: (folder: FolderNode) => void;
  onDeleteFolder?: (folder: FolderNode) => void;
  adminGroups?: UserFolderGroup[];
  selectedUserId?: string;
  onSelectUser?: (userId: string | null) => void;
}

function buildTreeData(nodes: FolderNode[], rootLabel?: string): TreeDataNode[] {
  function buildBranch(parentId: string | null): TreeDataNode[] {
    return nodes
      .filter((n) => n.parent_folder_id === parentId)
      .map((node) => ({
        key: node.id,
        title: `${node.name} (${node.child_file_count})`,
        icon: ({ expanded }: { expanded?: boolean }) =>
          expanded ? <FolderOpenOutlined /> : <FolderOutlined />,
        selectable: true,
        children: buildBranch(node.id),
      } as TreeDataNode));
  }

  const rootNode: TreeDataNode = {
    key: "",
    title: rootLabel || "全部文件",
    icon: <HomeOutlined />,
    selectable: true,
    children: buildBranch(null),
  };

  return [rootNode];
}

function buildAdminTreeData(groups: UserFolderGroup[]): TreeDataNode[] {
  return groups.map((g) => {
    function buildBranch(parentId: string | null): TreeDataNode[] {
      return g.folders
        .filter((n) => n.parent_folder_id === parentId)
        .map((node) => ({
          key: `folder:${node.id}`,
          title: `${node.name} (${node.child_file_count})`,
          icon: ({ expanded }: { expanded?: boolean }) =>
            expanded ? <FolderOpenOutlined /> : <FolderOutlined />,
          selectable: true,
          children: buildBranch(node.id),
        } as TreeDataNode));
    }
    return {
      key: `user:${g.user_id}`,
      title: g.display_name || g.username,
      icon: <HomeOutlined />,
      selectable: true,
      children: buildBranch(null),
    } as TreeDataNode;
  });
}

export default function FolderTree({
  treeData,
  selectedFolderId,
  loading,
  onSelect,
  rootLabel,
  onRenameFolder,
  onDeleteFolder,
  adminGroups,
  selectedUserId,
  onSelectUser,
}: FolderTreeProps) {
  const isAdmin = !!adminGroups;
  const treeNodes = useMemo(
    () =>
      isAdmin
        ? buildAdminTreeData(adminGroups ?? [])
        : buildTreeData(treeData, rootLabel),
    [isAdmin, adminGroups, treeData, rootLabel]
  );

  const selectedKeys = isAdmin
    ? [selectedUserId ? `user:${selectedUserId}` : "", ...(selectedFolderId ? [`folder:${selectedFolderId}`] : [])]
    : [selectedFolderId || ""];

  const handleSelect = (keys: React.Key[]) => {
    if (keys.length === 0) return;
    const key = keys[0] as string;
    if (isAdmin) {
      if (key.startsWith("user:")) {
        onSelectUser?.(key.slice(5));
        onSelect(null);
      } else if (key.startsWith("folder:")) {
        onSelect(key.slice(7));
      }
    } else {
      onSelect(key || null);
    }
  };

  const [contextFolder, setContextFolder] = useState<FolderNode | null>(null);
  const contextRef = useRef<HTMLDivElement>(null);

  const contextMenuItems: MenuProps["items"] = [
    {
      key: "rename",
      label: "重命名",
      onClick: () => {
        if (contextFolder && onRenameFolder) onRenameFolder(contextFolder);
      },
    },
    {
      key: "delete",
      label: "删除",
      danger: true,
      onClick: () => {
        if (contextFolder && onDeleteFolder) onDeleteFolder(contextFolder);
      },
    },
  ];

  if (loading) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }

  if (isAdmin) {
    return (
      <div className="folder-tree">
        <Tree
          showIcon
          defaultExpandAll
          treeData={treeNodes}
          selectedKeys={selectedKeys}
          onSelect={handleSelect}
          style={{ background: "transparent" }}
        />
      </div>
    );
  }

  return (
    <div className="folder-tree" ref={contextRef}>
      <Dropdown
        menu={{ items: contextMenuItems }}
        trigger={["contextMenu"]}
        open={contextFolder !== null}
        onOpenChange={(open) => { if (!open) setContextFolder(null); }}
      >
        <div style={{ height: "100%" }}>
          <Tree
            showIcon
            defaultExpandAll
            treeData={treeNodes}
            selectedKeys={selectedKeys}
            onSelect={handleSelect}
            onRightClick={({ node }) => {
              if (!node.key) return;
              const folder = treeData.find((f) => f.id === node.key);
              if (folder) setContextFolder(folder);
            }}
            style={{ background: "transparent" }}
          />
        </div>
      </Dropdown>
    </div>
  );
}
