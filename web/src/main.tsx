import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, keepPreviousData } from "@tanstack/react-query";
import "./index.css";
import { Layout } from "./components/Layout";
import { Empty } from "./components/ui";

const Today = lazy(() => import("./pages/Today").then((m) => ({ default: m.Today })));
const Sessions = lazy(() => import("./pages/Sessions").then((m) => ({ default: m.Sessions })));
const SessionDetail = lazy(() => import("./pages/SessionDetail").then((m) => ({ default: m.SessionDetail })));
const Calendar = lazy(() => import("./pages/Calendar").then((m) => ({ default: m.Calendar })));
const Battery = lazy(() => import("./pages/Analytics").then((m) => ({ default: m.Battery })));
const EfficiencyPage = lazy(() => import("./pages/Analytics").then((m) => ({ default: m.EfficiencyPage })));
const TiresPage = lazy(() => import("./pages/Analytics").then((m) => ({ default: m.TiresPage })));
const MapPage = lazy(() => import("./pages/Analytics").then((m) => ({ default: m.MapPage })));

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, placeholderData: keepPreviousData, retry: 1 } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<div className="mx-auto mt-40 max-w-[1280px] px-4"><div className="card h-64 animate-pulse" /></div>}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Today />} />
            <Route path="drives" element={<Sessions key="drive" mode="drive" />} />
            <Route path="charges" element={<Sessions key="charge" mode="charge" />} />
            <Route path="parked" element={<Sessions key="parked" mode="parked" />} />
            <Route path="session/:id" element={<SessionDetail />} />
            <Route path="calendar" element={<Calendar />} />
            <Route path="battery" element={<Battery />} />
            <Route path="efficiency" element={<EfficiencyPage />} />
            <Route path="tires" element={<TiresPage />} />
            <Route path="map" element={<MapPage />} />
            <Route path="*" element={<Empty>Page not found.</Empty>} />
          </Route>
        </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
