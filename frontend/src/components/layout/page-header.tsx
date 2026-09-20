import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  actions?: ReactNode;
  eyebrow?: string;
  description?: string;
}

export default function PageHeader({ title, actions, eyebrow, description }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div className="page-header-copy">
        {eyebrow ? <span className="page-eyebrow">{eyebrow}</span> : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  );
}
