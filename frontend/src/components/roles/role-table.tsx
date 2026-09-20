"use client";

import { Space, Table, Tag, Typography, Button } from "antd";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, EditOutlined, StopOutlined } from "@ant-design/icons";
import type { RoleListItem } from "@/types/role";
import type { CurrentUser } from "@/types/auth";
import {
  hasPermission,
  ROLE_UPDATE,
  ROLE_DELETE,
  ROLE_STATUS,
} from "@/lib/permissions";
import { copy } from "@/lib/copy";

interface RoleTableProps {
  roles: RoleListItem[];
  currentUser: CurrentUser;
  onEdit: (role: RoleListItem) => void;
  onToggleStatus: (role: RoleListItem) => void;
  onDelete: (role: RoleListItem) => void;
}

export default function RoleTable({
  roles,
  currentUser,
  onEdit,
  onToggleStatus,
  onDelete,
}: RoleTableProps) {
  const columns: ColumnsType<RoleListItem> = [
    {
      title: copy.role.name,
      dataIndex: "name",
      key: "name",
      render: (name: string) => <Typography.Text strong>{name}</Typography.Text>,
    },
    {
      title: copy.role.description,
      dataIndex: "description",
      key: "description",
      render: (desc: string | null) => desc || "—",
    },
    {
      title: "权限数量",
      dataIndex: "permission_count",
      key: "permission_count",
    },
    {
      title: copy.user.status,
      dataIndex: "status",
      key: "status",
      render: (status: string) => (
        <Tag className="warm-tag" color={status === "active" ? "success" : "default"}>
          {status === "active" ? copy.status.active : copy.status.disabled}
        </Tag>
      ),
    },
    {
      title: "系统角色",
      dataIndex: "is_system",
      key: "is_system",
      render: (isSystem: boolean) =>
        isSystem ? <Tag className="warm-tag" color="gold">系统角色</Tag> : "—",
    },
    {
      title: <div style={{ textAlign: "left" }}>操作</div>,
      key: "actions",
      width: 260,
      align: "right",
      fixed: "right",
      render: (_: unknown, role: RoleListItem) => {
        const isSystem = role.is_system;
        const editButton = hasPermission(currentUser, ROLE_UPDATE) ? (
          <Button size="small" type="text" icon={<EditOutlined />} onClick={() => onEdit(role)}>
            {copy.common.edit}
          </Button>
        ) : null;
        if (isSystem) {
          return (
            <div style={{ display: "flex", justifyContent: "center" }}>{editButton}</div>
          );
        }
        return (
          <Space size={2}>
            {editButton}
            {hasPermission(currentUser, ROLE_STATUS) && (
              <Button
                size="small"
                type="text"
                icon={<StopOutlined />}
                onClick={() => onToggleStatus(role)}
              >
                {role.status === "active" ? "停用" : "启用"}
              </Button>
            )}
            {hasPermission(currentUser, ROLE_DELETE) && (
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => onDelete(role)}
              >
                {copy.common.delete}
              </Button>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <Table
      dataSource={roles}
      columns={columns}
      rowKey="id"
      pagination={false}
      scroll={{ x: 1000 }}
    />
  );
}
