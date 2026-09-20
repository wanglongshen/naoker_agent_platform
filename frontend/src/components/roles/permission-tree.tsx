"use client";

import { useMemo } from "react";
import { Tree, Typography, Space } from "antd";
import type { TreeDataNode } from "antd";
import type { PermissionSummary } from "@/types/role";
import { copy } from "@/lib/copy";

interface PermissionTreeProps {
  permissions: PermissionSummary[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  readOnly: boolean;
}

interface ModuleGroup {
  module: string;
  label: string;
  permissions: PermissionSummary[];
}

function moduleLabel(module: string): string {
  switch (module) {
    case "user":
      return copy.navigation.users;
    case "role":
      return copy.navigation.roles;
    default:
      return "系统管理";
  }
}

function groupPermissions(permissions: PermissionSummary[]): ModuleGroup[] {
  const map = new Map<string, PermissionSummary[]>();
  const order: string[] = [];
  for (const p of permissions) {
    if (!map.has(p.module)) {
      map.set(p.module, []);
      order.push(p.module);
    }
    map.get(p.module)!.push(p);
  }
  for (const [, perms] of map) {
    perms.sort((a, b) => {
      const codeA = a.code;
      const codeB = b.code;
      if (codeA < codeB) return -1;
      if (codeA > codeB) return 1;
      return a.name.localeCompare(b.name);
    });
  }
  return order.map((mod) => ({
    module: mod,
    label: moduleLabel(mod),
    permissions: map.get(mod)!,
  }));
}

export default function PermissionTree({
  permissions,
  selectedIds,
  onChange,
  readOnly,
}: PermissionTreeProps) {
  const groups = useMemo(() => groupPermissions(permissions), [permissions]);
  const validPermIds = useMemo(() => new Set(permissions.map((p) => p.id)), [permissions]);

  const treeData: TreeDataNode[] = groups.map((group) => ({
    key: group.module,
    title: <span className="permission-group-title">{group.label}</span>,
    children: group.permissions.map((permission) => ({
      key: permission.id,
      title: (
        <Space direction="vertical" size={0}>
          <span>{permission.name}</span>
          {permission.description ? (
            <Typography.Text type="secondary">{permission.description}</Typography.Text>
          ) : null}
        </Space>
      ),
    })),
  }));

  return (
    <div className="permission-tree-container">
      <Tree
        checkable
        selectable={false}
        disabled={readOnly}
        checkedKeys={selectedIds}
        onCheck={(keys) => {
          const checked = Array.isArray(keys) ? keys : keys.checked;
          onChange(checked.filter((k) => validPermIds.has(k as string)) as string[]);
        }}
        treeData={treeData}
      />
    </div>
  );
}
