"use client";

import AuthenticatedPage from "@/components/auth/authenticated-page";
import AppShell from "@/components/layout/app-shell";
import AppHeader from "@/components/layout/app-header";

export default function AgentLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthenticatedPage>
      {(user) => (
        <AppShell currentUser={user}>
          <AppHeader user={user} />
          <div className="agent-route-content">{children}</div>
        </AppShell>
      )}
    </AuthenticatedPage>
  );
}
