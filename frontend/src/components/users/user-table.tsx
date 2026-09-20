"use client";

import type { UserListItem } from "@/types/user";
import type { CurrentUser } from "@/types/auth";
import {
  hasPermission,
  USER_UPDATE,
  USER_DELETE,
  USER_STATUS,
  USER_RESET_PASSWORD,
} from "@/lib/permissions";
import { copy } from "@/lib/copy";
import { resolveAvatarUrl } from "@/lib/avatar";
import { Space, Table, Tag, Typography, Button, Avatar } from "antd";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, EditOutlined, KeyOutlined, StopOutlined, UserOutlined, WalletOutlined } from "@ant-design/icons";

const { Text } = Typography;

interface UserTableProps {
  users: UserListItem[];
  currentUser: CurrentUser;
  onEdit: (user: UserListItem) => void;
  onToggleStatus: (user: UserListItem) => void;
  onResetPassword: (user: UserListItem) => void;
  onDelete: (user: UserListItem) => void;
  balances?: Record<string, number>;
  onRecharge?: (user: UserListItem) => void;
}

function RoleTags({ roles }: { roles: UserListItem["roles"] }) {
  if (roles.length === 0) return <>—</>;

  const visible = roles.slice(0, 2);
  const overflow = roles.length - 2;

  return (
    <span className="role-tags">
      {visible.map((r) => (
        <span key={r.id} className="role-tag">
          {r.name}
        </span>
      ))}
      {overflow > 0 && (
        <span className="role-tag role-tag-overflow" title={roles.map((r) => r.name).join(", ")}>
          +{overflow}
        </span>
      )}
    </span>
  );
}

function UserActions({
  user,
  currentUser,
  onEdit,
  onToggleStatus,
  onResetPassword,
  onDelete,
  onRecharge,
}: {
  user: UserListItem;
  currentUser: CurrentUser;
  onEdit: (user: UserListItem) => void;
  onToggleStatus: (user: UserListItem) => void;
  onResetPassword: (user: UserListItem) => void;
  onDelete: (user: UserListItem) => void;
  onRecharge?: (user: UserListItem) => void;
}) {
  return (
    <Space size={2}>
      {onRecharge && (
        <Button size="small" type="text" icon={<WalletOutlined />} onClick={() => onRecharge(user)}>
          充值积点
        </Button>
      )}
      {hasPermission(currentUser, USER_UPDATE) && (
        <Button size="small" type="text" icon={<EditOutlined />} onClick={() => onEdit(user)}>
          {copy.common.edit}
        </Button>
      )}
      {hasPermission(currentUser, USER_STATUS) && (
        <Button
          size="small"
          type="text"
          icon={<StopOutlined />}
          disabled={user.is_builtin}
          title={user.is_builtin ? "内置账号不可禁用" : undefined}
          onClick={() => onToggleStatus(user)}
        >
          {user.status === "active" ? "停用" : "启用"}
        </Button>
      )}
      {hasPermission(currentUser, USER_RESET_PASSWORD) && (
        <Button size="small" type="text" icon={<KeyOutlined />} onClick={() => onResetPassword(user)}>
          {copy.user.resetPassword}
        </Button>
      )}
      {hasPermission(currentUser, USER_DELETE) && (
        <Button
          size="small"
          type="text"
          danger
          icon={<DeleteOutlined />}
          disabled={user.is_builtin}
          title={user.is_builtin ? "内置账号不可删除" : undefined}
          onClick={() => onDelete(user)}
        >
          {copy.common.delete}
        </Button>
      )}
    </Space>
  );
}

export default function UserTable({
  users,
  currentUser,
  onEdit,
  onToggleStatus,
  onResetPassword,
  onDelete,
  balances,
  onRecharge,
}: UserTableProps) {
  const columns: ColumnsType<UserListItem> = [
    {
      title: "头像",
      key: "avatar",
      width: 64,
      render: (_, user) => (
        <Avatar size={36} src={resolveAvatarUrl(user.avatar_url)} icon={user.avatar_url ? undefined : <UserOutlined />}>
          {!user.avatar_url && user.display_name?.[0]}
        </Avatar>
      ),
    },
    {
      title: copy.user.username,
      dataIndex: "username",
      key: "username",
      className: "user-hierarchy-primary",
      render: (value) => <Text strong>{value}</Text>,
    },
    {
      title: copy.user.displayName,
      dataIndex: "display_name",
      key: "display_name",
    },
    {
      title: copy.user.email,
      dataIndex: "email",
      key: "email",
      className: "user-hierarchy-secondary",
      render: (value) => (
        <Text type="secondary" style={{ fontSize: "0.8rem" }}>{value || "—"}</Text>
      ),
    },
    {
      title: copy.user.phone,
      dataIndex: "phone",
      key: "phone",
      className: "user-hierarchy-secondary",
      render: (value) => (
        <Text type="secondary" style={{ fontSize: "0.8rem" }}>{value || "—"}</Text>
      ),
    },
    {
      title: copy.user.roles,
      key: "roles",
      render: (_, user) => <RoleTags roles={user.roles} />,
    },
    {
      title: copy.user.status,
      dataIndex: "status",
      key: "status",
      render: (status) => (
        <Tag className="warm-tag" color={status === "active" ? "success" : "default"}>
          {status === "active" ? copy.status.active : copy.status.disabled}
        </Tag>
      ),
    },
    {
      title: "余额",
      key: "balance",
      render: (_, user) => {
        const balance = balances?.[user.id];
        return (
          <Text style={{ fontSize: "0.8rem" }}>{balance == null ? "—" : balance.toLocaleString()}</Text>
        );
      },
    },
    {
      title: "创建时间",
      key: "created_at",
      render: (_, user) => (
        <Text type="secondary" style={{ fontSize: "0.8rem" }}>
          {user.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}
        </Text>
      ),
    },
    {
      title: <div style={{ textAlign: "left" }}>操作</div>,
      key: "actions",
      align: "right",
      fixed: "right",
      width: 440,
      render: (_, user) => (
        <UserActions
          user={user}
          currentUser={currentUser}
          onEdit={onEdit}
          onToggleStatus={onToggleStatus}
          onResetPassword={onResetPassword}
          onDelete={onDelete}
          onRecharge={onRecharge}
        />
      ),
    },
  ];

  return (
    <Table
      rowKey="id"
      columns={columns}
      dataSource={users}
      pagination={false}
      scroll={{ x: 1280 }}
    />
  );
}
