"use client";

import ProtectedPage from "@/components/auth/protected-page";
import FileManagement from "@/components/files/file-management";
import { FILE_ADMIN_VIEW } from "@/lib/permissions";

export default function AdminFilesPage() {
  return (
    <ProtectedPage permission={FILE_ADMIN_VIEW}>
      {(user) => <FileManagement currentUser={user} adminView />}
    </ProtectedPage>
  );
}
