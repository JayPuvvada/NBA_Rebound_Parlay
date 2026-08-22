import { useState } from "react";
import { SplineSceneBasic } from "@/components/ui/demo";
import { CheatSheet } from "@/components/ui/CheatSheet";
import { PredictForm } from "@/components/ui/PredictForm";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import "./index.css";

function App() {
  const [activeTab, setActiveTab] = useState<"edge" | "lookup">("edge");

  return (
    <main className="min-h-screen bg-black text-white dark">
      {/* 3D Hero Section */}
      <SplineSceneBasic />

      {/* Tab Navigation */}
      <div className="max-w-7xl mx-auto px-8 pt-8">
        <div className="flex gap-1 bg-zinc-900/50 p-1 rounded-lg w-fit">
          <button
            onClick={() => setActiveTab("edge")}
            className={`px-5 py-2.5 rounded-md text-sm font-semibold transition-all duration-200 ${
              activeTab === "edge"
                ? "bg-emerald-600 text-white shadow-lg shadow-emerald-900/30"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            🔥 Daily Edge
          </button>
          <button
            onClick={() => setActiveTab("lookup")}
            className={`px-5 py-2.5 rounded-md text-sm font-semibold transition-all duration-200 ${
              activeTab === "lookup"
                ? "bg-emerald-600 text-white shadow-lg shadow-emerald-900/30"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            🏀 Player Lookup
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <section id="edge-section" className="max-w-7xl mx-auto p-8 pb-24">
        <ErrorBoundary>
          {activeTab === "edge" ? <CheatSheet /> : <PredictForm />}
        </ErrorBoundary>
      </section>
    </main>
  );
}

export default App;
