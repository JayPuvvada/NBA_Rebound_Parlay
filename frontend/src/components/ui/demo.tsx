'use client'

import { Card } from "@/components/ui/card"
import { Spotlight } from "@/components/ui/spotlight"

function BouncingBasketball() {
  return (
    <div className="w-full h-full flex items-center justify-center relative">
      {/* Glow effect */}
      <div className="absolute w-48 h-48 bg-orange-500/20 rounded-full blur-3xl animate-pulse" />
      
      {/* Basketball */}
      <div className="basketball-animation relative">
        <svg aria-hidden="true" focusable="false" width="160" height="160" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <radialGradient id="ballGrad" cx="40%" cy="35%" r="60%">
              <stop offset="0%" stopColor="#f97316" />
              <stop offset="60%" stopColor="#ea580c" />
              <stop offset="100%" stopColor="#9a3412" />
            </radialGradient>
            <filter id="shadow">
              <feDropShadow dx="0" dy="4" stdDeviation="8" floodColor="#f97316" floodOpacity="0.4" />
            </filter>
          </defs>
          {/* Ball body */}
          <circle cx="100" cy="100" r="90" fill="url(#ballGrad)" filter="url(#shadow)" />
          {/* Seam lines */}
          <path d="M 100 10 C 100 10, 100 190, 100 190" stroke="#1a1a1a" strokeWidth="2.5" fill="none" opacity="0.6" />
          <path d="M 10 100 C 10 100, 190 100, 190 100" stroke="#1a1a1a" strokeWidth="2.5" fill="none" opacity="0.6" />
          <path d="M 30 30 C 60 60, 60 140, 30 170" stroke="#1a1a1a" strokeWidth="2" fill="none" opacity="0.5" />
          <path d="M 170 30 C 140 60, 140 140, 170 170" stroke="#1a1a1a" strokeWidth="2" fill="none" opacity="0.5" />
          {/* Highlight */}
          <ellipse cx="70" cy="65" rx="25" ry="18" fill="white" opacity="0.15" transform="rotate(-20, 70, 65)" />
        </svg>
      </div>
      
      {/* Shadow on floor */}
      <div className="basketball-shadow-animation absolute bottom-8 h-4 w-32 rounded-full bg-orange-500/10 blur-sm" />
    </div>
  );
}

interface HeroProps {
  onViewEdge: () => void;
}

export function SplineSceneBasic({ onViewEdge }: HeroProps) {
  return (
    <Card className="relative w-full overflow-hidden rounded-none border-none bg-black/[0.96] md:h-[500px]">
      <Spotlight
        className="-top-40 left-0 md:left-60 md:-top-20"
        fill="white"
      />
      
      <div className="mx-auto flex min-h-[680px] max-w-7xl flex-col md:h-full md:min-h-0 md:flex-row">
        {/* Left content */}
        <div className="flex-1 p-8 relative z-10 flex flex-col justify-center">
          <h1 className="bg-gradient-to-b from-neutral-50 to-neutral-500 bg-clip-text text-4xl font-extrabold tracking-tight text-transparent md:text-6xl">
            Dominate the Glass.
            <br/> Predict the Edge.
          </h1>
          <p className="mt-6 text-neutral-300 max-w-lg text-lg leading-relaxed">
            Player rebound projections powered by matchup scouting, pace 
            modeling, Monte Carlo simulation, and live odds integration.
          </p>
          <div className="mt-8">
             <button
               type="button"
               onClick={onViewEdge}
               className="rounded-full bg-emerald-500 px-8 py-3 font-bold text-white transition-colors duration-200 hover:bg-emerald-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black"
             >
               View Daily Cheat Sheet
             </button>
          </div>
        </div>

        {/* Right content - Basketball */}
        <div className="relative min-h-[280px] flex-1 md:min-h-full">
          <BouncingBasketball />
        </div>
      </div>
    </Card>
  )
}
