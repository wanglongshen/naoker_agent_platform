import { describe, expect, test } from "vitest";
import { copy } from "@/lib/copy";

describe("中文文案词典", () => {
  test("提供统一的系统标题和状态映射", () => {
    expect(copy.app.title).toBe("脑壳工作台");
    expect(copy.status.active).toBe("启用");
    expect(copy.status.disabled).toBe("停用");
  });

  test("提供登录和通用操作文案", () => {
    expect(copy.auth.signIn).toBe("登录");
    expect(copy.common.save).toBe("保存");
    expect(copy.common.requestFailed).toBe("请求失败，请稍后重试。");
  });
});
