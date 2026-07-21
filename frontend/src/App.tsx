import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';
import { isOperario, isSupervisor, useAuth } from './store/auth';

import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import ProductsPage from './pages/ProductsPage';
import LabelsPage from './pages/LabelsPage';
import WarehousesPage from './pages/WarehousesPage';
import LocationsPage from './pages/LocationsPage';
import InventoryPage from './pages/InventoryPage';
import ReceptionPage from './pages/ReceptionPage';
import InventoryTransferPage from './pages/InventoryTransferPage';
import InventoryAdjustmentPage from './pages/InventoryAdjustmentPage';
import OrdersPage from './pages/OrdersPage';
import PickingPage from './pages/PickingPage';
import PackingPage from './pages/PackingPage';
import DispatchPage from './pages/DispatchPage';
import SettingsDefontanaPage from './pages/SettingsDefontanaPage';
import SyncJobsPage from './pages/SyncJobsPage';
import MyPickingTasksPage from './pages/MyPickingTasksPage';
import PickingTaskPage from './pages/PickingTaskPage';
import MyPackingTasksPage from './pages/MyPackingTasksPage';
import PackingTaskPage from './pages/PackingTaskPage';
import PackingLabelsPage from './pages/PackingLabelsPage';

/** Wraps a page in ProtectedRoute + Layout. */
function Shell({ children }: { children: ReactElement }) {
  return (
    <ProtectedRoute>
      <Layout>{children}</Layout>
    </ProtectedRoute>
  );
}

/** Restricts a route to supervisor/admin; operarios get redirected to their tasks. */
function SupervisorOnly({ children }: { children: ReactElement }) {
  const { currentUser } = useAuth();
  if (currentUser && !isSupervisor(currentUser.role)) {
    return <Navigate to="/my/picking" replace />;
  }
  return children;
}

/** Redirect root according to role. */
function HomeRedirect() {
  const { currentUser } = useAuth();
  if (currentUser && isOperario(currentUser.role)) {
    return <Navigate to="/my/picking" replace />;
  }
  return (
    <Shell>
      <DashboardPage />
    </Shell>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      {/* Supervisor / admin */}
      <Route path="/" element={<HomeRedirect />} />
      <Route
        path="/products"
        element={
          <Shell>
            <SupervisorOnly>
              <ProductsPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/labels"
        element={
          <Shell>
            <SupervisorOnly>
              <LabelsPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/warehouses"
        element={
          <Shell>
            <SupervisorOnly>
              <WarehousesPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/locations"
        element={
          <Shell>
            <SupervisorOnly>
              <LocationsPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/inventory"
        element={
          <Shell>
            <SupervisorOnly>
              <InventoryPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/inventory/recepcion"
        element={
          <Shell>
            <SupervisorOnly>
              <ReceptionPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/inventory/transferencia"
        element={
          <Shell>
            <SupervisorOnly>
              <InventoryTransferPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/inventory/ajuste"
        element={
          <Shell>
            <SupervisorOnly>
              <InventoryAdjustmentPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/orders"
        element={
          <Shell>
            <SupervisorOnly>
              <OrdersPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/picking"
        element={
          <Shell>
            <SupervisorOnly>
              <PickingPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/packing"
        element={
          <Shell>
            <SupervisorOnly>
              <PackingPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/dispatch"
        element={
          <Shell>
            <SupervisorOnly>
              <DispatchPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/settings/defontana"
        element={
          <Shell>
            <SupervisorOnly>
              <SettingsDefontanaPage />
            </SupervisorOnly>
          </Shell>
        }
      />
      <Route
        path="/sync-jobs"
        element={
          <Shell>
            <SupervisorOnly>
              <SyncJobsPage />
            </SupervisorOnly>
          </Shell>
        }
      />

      {/* Operario */}
      <Route
        path="/my/picking"
        element={
          <Shell>
            <MyPickingTasksPage />
          </Shell>
        }
      />
      <Route
        path="/my/picking/:id"
        element={
          <Shell>
            <PickingTaskPage />
          </Shell>
        }
      />
      <Route
        path="/my/packing"
        element={
          <Shell>
            <MyPackingTasksPage />
          </Shell>
        }
      />
      <Route
        path="/my/packing/:id"
        element={
          <Shell>
            <PackingTaskPage />
          </Shell>
        }
      />
      <Route
        path="/my/packing/:id/labels"
        element={
          <Shell>
            <PackingLabelsPage />
          </Shell>
        }
      />

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
