"use client";

import AuthenticatedPage from "@/components/auth/authenticated-page";
import FileManagement from "@/components/files/file-management";

export default function MyFilesPage() {
  return (
    <AuthenticatedPage>
      {(user) => <FileManagement currentUser={user} />}
    </AuthenticatedPage>
  );
}
