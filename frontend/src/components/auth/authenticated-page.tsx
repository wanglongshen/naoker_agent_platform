"use client";

import { type ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchCurrentUser } from "@/lib/auth";
import { copy } from "@/lib/copy";
import type { CurrentUser } from "@/types/auth";

interface AuthenticatedPageProps {
  children: (user: CurrentUser) => ReactNode;
  loading?: ReactNode;
}

export default function AuthenticatedPage({ children, loading }: AuthenticatedPageProps) {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [state, setState] = useState<"loading" | "authenticated">("loading");

  useEffect(() => {
    fetchCurrentUser()
      .then((currentUser) => {
        if (!currentUser) {
          router.push("/login");
          return;
        }
        setUser(currentUser);
        setState("authenticated");
      })
      .catch(() => {
        router.push("/login");
      });
  }, [router]);

  if (state === "loading") {
    return loading ?? <div>{copy.common.loading}</div>;
  }

  if (!user) {
    return null;
  }

  return <>{children(user)}</>;
}
