"use client";

import ProtectedPage from "@/components/auth/protected-page";
import { ROLE_READ } from "@/lib/permissions";
import RoleManagement from "@/components/roles/role-management";

export default function RolesPage() {
  return (
    <ProtectedPage permission={ROLE_READ}>
      {(user) => <RoleManagement currentUser={user} />}
    </ProtectedPage>
  );
}
