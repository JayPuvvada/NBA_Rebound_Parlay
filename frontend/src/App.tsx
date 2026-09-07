import { lazy, Suspense, useEffect, useState, type KeyboardEvent } from "react";
import { SplineSceneBasic } from "@/components/ui/demo";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { PersonalProvider } from "@/components/PersonalProvider";
import { AccountProvider } from "@/components/AccountProvider";
import { MyPicks } from "@/components/ui/MyPicks";
import { demoEnabled } from "@/lib/personal-picks";
import "./index.css";

const CheatSheet = lazy(() => import("@/components/ui/CheatSheet").then((module) => ({ default: module.CheatSheet })));
const PredictForm = lazy(() => import("@/components/ui/PredictForm").then((module) => ({ default: module.PredictForm })));

const personalDemo = demoEnabled(import.meta.env.VITE_PERSONAL_DEMO, window.location.hostname);
type Tab = "edge" | "lookup" | "picks";
const tabs: Tab[] = ["edge", "lookup", "picks"];

function tabFromLocation(): Tab {
  if (window.location.hash === "#picks") return "picks";
  return window.location.hash === "#lookup" ? "lookup" : "edge";
}

function AppContent() {
  const [activeTab, setActiveTab] = useState<Tab>(tabFromLocation);

  useEffect(() => {
    const syncTab = () => setActiveTab(tabFromLocation());
    window.addEventListener("hashchange", syncTab);
    window.addEventListener("popstate", syncTab);
    return () => {
      window.removeEventListener("hashchange", syncTab);
      window.removeEventListener("popstate", syncTab);
    };
  }, []);

  const selectTab = (tab: Tab) => {
    setActiveTab(tab);
    const nextHash = `#${tab}`;
    if (window.location.hash !== nextHash) window.history.pushState(null, "", nextHash);
  };

  const viewDailyEdge = () => {
    selectTab("edge");
    window.requestAnimationFrame(() => {
      document.querySelector("#edge-section")?.scrollIntoView({ behavior: "smooth" });
    });
  };

  const navigateTabs = (event: KeyboardEvent<HTMLDivElement>) => {
    let nextTab: Tab | null = null;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") nextTab = tabs[(tabs.indexOf(activeTab) + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    if (event.key === "Home") nextTab = "edge";
    if (event.key === "End") nextTab = tabs[tabs.length - 1];
    if (!nextTab) return;

    event.preventDefault();
    selectTab(nextTab);
    window.requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`#${nextTab}-tab`)?.focus());
  };

  return (
    <main className="min-h-screen bg-black text-white dark">
      {/* 3D Hero Section */}
      <SplineSceneBasic onViewEdge={viewDailyEdge} />

      {/* Tab Navigation */}
      <div className="mx-auto max-w-7xl px-4 pt-8 sm:px-8">
        <div className="flex w-fit flex-wrap gap-1 rounded-lg bg-zinc-900/50 p-1" role="tablist" aria-label="Projection tools" onKeyDown={navigateTabs}>
          <button
            id="edge-tab"
            type="button"
            role="tab"
            aria-selected={activeTab === "edge"}
            aria-controls="edge-panel"
            tabIndex={activeTab === "edge" ? 0 : -1}
            onClick={() => selectTab("edge")}
            className={`rounded-md px-3 py-2.5 text-sm font-semibold transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 sm:px-5 ${
              activeTab === "edge"
                ? "bg-emerald-600 text-white shadow-lg shadow-emerald-900/30"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            🔥 Daily Edge
          </button>
          <button
            id="lookup-tab"
            type="button"
            role="tab"
            aria-selected={activeTab === "lookup"}
            aria-controls="lookup-panel"
            tabIndex={activeTab === "lookup" ? 0 : -1}
            onClick={() => selectTab("lookup")}
            className={`rounded-md px-3 py-2.5 text-sm font-semibold transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 sm:px-5 ${
              activeTab === "lookup"
                ? "bg-emerald-600 text-white shadow-lg shadow-emerald-900/30"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            🏀 Player Lookup
          </button>
          <button id="picks-tab" type="button" role="tab" aria-selected={activeTab === "picks"} aria-controls="picks-panel" tabIndex={activeTab === "picks" ? 0 : -1} onClick={() => selectTab("picks")} className={`rounded-md px-3 py-2.5 text-sm font-semibold focus-visible:ring-2 focus-visible:ring-emerald-400 sm:px-5 ${activeTab === "picks" ? "bg-emerald-600 text-white" : "text-zinc-400 hover:text-zinc-200"}`}>My Picks</button>
        </div>
      </div>

      {/* Tab Content */}
      <section
        id="edge-section"
        className="mx-auto max-w-7xl p-4 pb-24 sm:p-8"
      >
        <div id={`${activeTab}-panel`} role="tabpanel" aria-labelledby={`${activeTab}-tab`}>
          <ErrorBoundary resetKey={activeTab}>
            <Suspense fallback={<div className="h-64 animate-pulse rounded-lg bg-zinc-900/60" aria-label="Loading section" />}>
              {activeTab === "edge" ? <CheatSheet /> : activeTab === "lookup" ? <PredictForm /> : <MyPicks />}
            </Suspense>
          </ErrorBoundary>
        </div>
      </section>
    </main>
  );
}

export default function App() {
  return personalDemo ? <PersonalProvider><AppContent /></PersonalProvider> : <AccountProvider><AppContent /></AccountProvider>;
}
