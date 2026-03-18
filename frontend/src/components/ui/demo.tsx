'use client'

import { Card } from "@/components/ui/card"
import { Spotlight } from "@/components/ui/spotlight"

function BouncingBasketball() {
  return (
    <div className="w-full h-full flex items-center justify-center relative">
      {/* Glow effect */}
      <div className="absolute w-48 h-48 bg-orange-500/20 rounded-full blur-3xl animate-pulse" />
      
      {/* Basketball */}
      <div className="relative" style={{ animation: "bounce-ball 2s ease-in-out infinite" }}>
        <svg width="160" height="160" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
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
      <div 
        className="absolute bottom-8 w-32 h-4 bg-orange-500/10 rounded-full blur-sm"
        style={{ animation: "shadow-pulse 2s ease-in-out infinite" }}
      />
    </div>
  );
}

export function SplineSceneBasic() {
  return (
    <Card className="w-full h-[500px] bg-black/[0.96] relative overflow-hidden border-none rounded-none">
      <Spotlight
        className="-top-40 left-0 md:left-60 md:-top-20"
        fill="white"
      />
      
      <div className="flex h-full flex-col md:flex-row max-w-7xl mx-auto">
        {/* Left content */}
        <div className="flex-1 p-8 relative z-10 flex flex-col justify-center">
          <h1 className="text-4xl md:text-6xl font-extrabold bg-clip-text text-transparent bg-gradient-to-b from-neutral-50 to-neutral-500 tracking-tight">
            Dominate the Glass.
            <br/> Predict the Edge.
          </h1>
          <p className="mt-6 text-neutral-300 max-w-lg text-lg leading-relaxed">
            The mathematical model for NBA Rebound Parlays. We crunch 
            defensive schemes, cannibalization limits, and teammate correlation 
            matrices to find the absolute best bets on the board.
          </p>
          <div className="mt-8">
             <button 
               onClick={() => document.querySelector('#edge-section')?.scrollIntoView({ behavior: 'smooth' })}
               className="bg-emerald-500 hover:bg-emerald-600 text-white font-bold py-3 px-8 rounded-full transition-colors duration-200"
             >
               View Daily Cheat Sheet
             </button>
          </div>
        </div>

        {/* Right content - Basketball */}
        <div className="flex-1 relative min-h-[300px] md:min-h-full">
          <BouncingBasketball />
        </div>
      </div>
    </Card>
  )
}
