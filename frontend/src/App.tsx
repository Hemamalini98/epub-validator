import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AnimatePresence } from 'framer-motion';
import { Sidebar } from '@/components/Sidebar';
import Dashboard from '@/pages/Dashboard';
import UploadPage from '@/pages/UploadPage';
import FilesPage from '@/pages/FilesPage';
import { ToastProvider } from '@/components/Toaster';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
});

function AnimatedRoutes() {
  const location = useLocation();
  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/"                    element={<Dashboard />} />
        <Route path="/upload"              element={<UploadPage />} />
        <Route path="/files/:folderName"   element={<FilesPage />} />
      </Routes>
    </AnimatePresence>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <div className="flex h-screen overflow-hidden bg-background">
            <Sidebar />
            <main className="flex-1 overflow-y-auto">
              <AnimatedRoutes />
            </main>
          </div>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
