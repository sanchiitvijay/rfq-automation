import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { JobDetailPage } from "./features/jobs/JobDetailPage";
import { JobsPage } from "./features/jobs/JobsPage";

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<JobsPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
