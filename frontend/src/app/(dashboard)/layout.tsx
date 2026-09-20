"use client";

import { type ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchCurrentUser } from "@/lib/auth";
import DashboardShell from "@/components/layout/dashboard-shell";
import type { CurrentUser } from "@/types/auth";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unauthenticated">("loading");

  useEffect(() => {
    fetchCurrentUser()
      .then((currentUser) => {
        if (!currentUser) {
          setState("unauthenticated");
          router.push("/login");
          return;
        }
        setUser(currentUser);
        setState("ready");
      })
      .catch(() => {
        setState("unauthenticated");
        router.push("/login");
      });
  }, [router]);

  if (state === "loading") {
    return <div>加载中...</div>;
  }

  if (state === "unauthenticated") {
    return null;
  }

  return <DashboardShell currentUser={user!}>{children}</DashboardShell>;
}
