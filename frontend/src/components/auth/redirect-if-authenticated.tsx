"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { fetchCurrentUser } from "@/lib/auth";
import { copy } from "@/lib/copy";

export default function RedirectIfAuthenticated({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    fetchCurrentUser()
      .then((currentUser) => {
        if (currentUser) {
          router.replace("/agent");
          return;
        }
        setChecked(true);
      })
      .catch(() => {
        setChecked(true);
      });
  }, [router]);

  if (!checked) {
    return <div>{copy.common.loading}</div>;
  }

  return <>{children}</>;
}
