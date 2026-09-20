"use client";

import type { RoleReference } from "@/types/role";
import { copy } from "@/lib/copy";
import { Input, Select, Button, Space } from "antd";

const { Search } = Input;

interface UserFiltersProps {
  keyword: string;
  status: string;
  roleId: string;
  assignableRoles?: RoleReference[];
  onFilterChange: (filters: { keyword: string; status: string; roleId: string }) => void;
  onSearch: () => void;
}

export default function UserFilters({
  keyword,
  status,
  roleId,
  assignableRoles,
  onFilterChange,
  onSearch,
}: UserFiltersProps) {
  return (
    <Space className="user-filters-controls" wrap>
      <Search
        placeholder="搜索用户"
        value={keyword}
        onChange={(e) =>
          onFilterChange({ keyword: e.target.value, status, roleId })
        }
        onSearch={onSearch}
        enterButton={copy.common.search}
        style={{ width: 200 }}
      />
      <Select
        placeholder="全部状态"
        allowClear
        value={status || undefined}
        onChange={(value) =>
          onFilterChange({ keyword, status: value || "", roleId })
        }
        options={[
          { label: copy.status.active, value: "active" },
          { label: copy.status.disabled, value: "disabled" },
        ]}
        style={{ width: 120 }}
      />
      {assignableRoles && assignableRoles.length > 0 && (
        <Select
          placeholder="全部角色"
          allowClear
          value={roleId || undefined}
          onChange={(value) =>
            onFilterChange({ keyword, status, roleId: value || "" })
          }
          options={assignableRoles.map((role) => ({
            label: role.name,
            value: role.id,
          }))}
          style={{ width: 160 }}
        />
      )}
      <Button
        onClick={() => {
          onFilterChange({ keyword: "", status: "", roleId: "" });
          setTimeout(() => onSearch(), 0);
        }}
      >
        {copy.common.reset}
      </Button>
    </Space>
  );
}
