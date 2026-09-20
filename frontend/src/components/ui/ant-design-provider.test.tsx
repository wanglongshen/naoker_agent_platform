import { render, screen } from "@testing-library/react";
import { Button } from "antd";
import AntDesignProvider from "./ant-design-provider";

test("renders children inside the Warm Executive Ant Design provider", () => {
  render(
    <AntDesignProvider>
      <Button type="primary">Primary action</Button>
    </AntDesignProvider>
  );

  expect(screen.getByRole("button", { name: "Primary action" })).toBeVisible();
});
