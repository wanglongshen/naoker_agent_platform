"use client";

import { useEffect, useState } from "react";
import { fetchCurrentUser } from "@/lib/auth";
import ProfilePage from "@/components/profile/profile-page";
import type { CurrentUser } from "@/types/auth";

export default function SettingsProfilePage() {
  const [user, setUser] = useState<CurrentUser | null>(null);

  useEffect(() => {
    fetchCurrentUser().then((u) => setUser(u));
  }, []);

  if (!user) return null;

  return <ProfilePage currentUser={user} />;
}
