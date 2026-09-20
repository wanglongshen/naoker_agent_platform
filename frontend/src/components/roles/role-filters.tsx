"use client";

import { Input, Select, Button, Space } from "antd";
import { copy } from "@/lib/copy";

interface RoleFiltersProps {
  keyword: string;
  status: string;
  onFilterChange: (filters: { keyword: string; status: string }) => void;
  onSearch: () => void;
}

export default function RoleFilters({
  keyword,
  status,
  onFilterChange,
  onSearch,
}: RoleFiltersProps) {
  return (
    <div className="data-workspace-filters">
      <Space wrap>
        <Input.Search
          placeholder="搜索角色"
          value={keyword}
          onChange={(e) =>
            onFilterChange({ keyword: e.target.value, status })
          }
          onSearch={onSearch}
          enterButton={copy.common.search}
          style={{ width: 200 }}
        />
        <Select
          value={status || undefined}
          onChange={(value) =>
            onFilterChange({ keyword, status: value })
          }
          style={{ width: 120 }}
          allowClear
          placeholder="全部状态"
        >
          <Select.Option value="active">{copy.status.active}</Select.Option>
          <Select.Option value="disabled">{copy.status.disabled}</Select.Option>
        </Select>
        <Button
          onClick={() => {
            onFilterChange({ keyword: "", status: "" });
            setTimeout(() => onSearch(), 0);
          }}
        >
          {copy.common.reset}
        </Button>
      </Space>
    </div>
  );
}
