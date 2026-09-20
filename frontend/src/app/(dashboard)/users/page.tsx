"use client";

import ProtectedPage from "@/components/auth/protected-page";
import UserManagement from "@/components/users/user-management";
import { USER_READ } from "@/lib/permissions";

export default function UsersPage() {
  return (
    <ProtectedPage permission={USER_READ}>
      {(user) => <UserManagement currentUser={user} />}
    </ProtectedPage>
  );
}
