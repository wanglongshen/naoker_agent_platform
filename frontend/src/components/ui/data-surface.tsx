import type { ReactNode } from "react";

type DataSurfaceProps = {
  children: ReactNode;
  className?: string;
};

export default function DataSurface({ children, className }: DataSurfaceProps) {
  return (
    <div className={`data-surface ${className ?? ""}`}>
      <div className="data-surface-scroll" tabIndex={0}>
        {children}
      </div>
    </div>
  );
}
