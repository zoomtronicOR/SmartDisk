import { lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import AccountPage from "./pages/Account";
import AuditPage from "./pages/Audit";
import DashboardPage from "./pages/Dashboard";
import DisksPage from "./pages/Disks";
import DevicesPage from "./pages/Devices";
import LoginPage from "./pages/Login";
import SettingsPage from "./pages/Settings";
import StoragePage from "./pages/Storage";
import UsersPage from "./pages/Users";

// Stranice sa grafikonima se učitavaju tek kada zatrebaju (Recharts je veliki paket).
const AlarmsPage = lazy(() => import("./pages/Alarms"));
const AlarmDetailPage = lazy(() => import("./pages/AlarmDetail"));
const DeviceDetailPage = lazy(() => import("./pages/DeviceDetail"));
const StatisticsPage = lazy(() => import("./pages/Statistics"));
const ReportsPage = lazy(() => import("./pages/Reports"));
const PoolDetailPage = lazy(() => import("./pages/PoolDetail"));
const DiskDetailPage = lazy(() => import("./pages/DiskDetail"));

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <LoginPage />;
  if (user.must_change_password) return <AccountPage forced />;

  const admin = user.role === "admin";
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="uredjaji" element={<DevicesPage />} />
        <Route path="uredjaji/:id" element={<DeviceDetailPage />} />
        <Route path="diskovi" element={<DisksPage />} />
        <Route path="diskovi/:id" element={<DiskDetailPage />} />
        <Route path="skladiste" element={<StoragePage />} />
        <Route path="skladiste/:id" element={<PoolDetailPage />} />
        <Route path="statistika" element={<StatisticsPage />} />
        <Route path="izvestaji" element={<ReportsPage />} />
        <Route path="alarmi" element={<AlarmsPage />} />
        <Route path="alarmi/:id" element={<AlarmDetailPage />} />
        {admin && <Route path="korisnici" element={<UsersPage />} />}
        {admin && <Route path="podesavanja" element={<SettingsPage />} />}
        {admin && <Route path="audit" element={<AuditPage />} />}
        <Route path="nalog" element={<AccountPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
