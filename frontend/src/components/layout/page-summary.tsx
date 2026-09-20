import { Card, Statistic } from "antd";

export default function PageSummary({ items }: { items: Array<{ label: string; value: number }> }) {
  return (
    <div className="page-summary" aria-label="页面统计">
      {items.map((item) => (
        <Card key={item.label} className="summary-card" variant="borderless">
          <Statistic title={item.label} value={item.value} />
        </Card>
      ))}
    </div>
  );
}
