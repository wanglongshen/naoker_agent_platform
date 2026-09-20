import { render, screen } from "@testing-library/react";
import PageSummary from "./page-summary";

test("renders supplied real values without trends or fabricated metrics", () => {
  render(<PageSummary items={[{ label: "组织成员", value: 24 }, { label: "当前角色", value: 10 }]} />);
  expect(screen.getByText("组织成员")).toBeVisible();
  expect(screen.getByText("24")).toBeVisible();
  expect(screen.queryByText(/较上月|安全事件|%/)).not.toBeInTheDocument();
});
