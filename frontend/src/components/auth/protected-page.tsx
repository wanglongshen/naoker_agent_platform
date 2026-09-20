"use client";

import { type ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchCurrentUser } from "@/lib/auth";
import { hasPermission } from "@/lib/permissions";
import { copy } from "@/lib/copy";
import type { CurrentUser } from "@/types/auth";

interface ProtectedPageProps {
  permission: string;
  children: (user: CurrentUser) => ReactNode;
  loading?: ReactNode;
  noPermission?: ReactNode;
}

export default function ProtectedPage({
  permission,
  children,
  loading,
  noPermission,
}: ProtectedPageProps) {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [state, setState] = useState<"loading" | "authorized" | "forbidden" | "unauthenticated">(
    "loading"
  );

  useEffect(() => {
    fetchCurrentUser()
      .then((currentUser) => {
        if (!currentUser) {
          setState("unauthenticated");
          router.push("/login");
          return;
        }
        if (!hasPermission(currentUser, permission)) {
          setState("forbidden");
          return;
        }
        setUser(currentUser);
        setState("authorized");
      })
      .catch(() => {
        setState("forbidden");
      });
  }, [permission, router]);

  if (state === "loading") {
    return loading ?? <div>{copy.common.loading}</div>;
  }

  if (state === "unauthenticated") {
    return null;
  }

  if (state === "forbidden") {
    return noPermission ?? <div>无权访问</div>;
  }

  return <>{children(user!)}</>;
}
