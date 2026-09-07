import { useState, type ReactNode } from "react";
import { PersonalContext } from "@/lib/personal-context";
import { demoCredentials, readPicks, writePicks, SESSION_KEY, type SavedPick } from "@/lib/personal-picks";

export function PersonalProvider({ children }: { children: ReactNode }) {
  const [initial] = useState(() => {
    try {
      return { picks: readPicks(window.localStorage), signedIn: window.sessionStorage.getItem(SESSION_KEY) === "jay", error: "" };
    } catch {
      return { picks: [], signedIn: false, error: "Browser storage is unavailable or saved data is unreadable. Existing data has not been overwritten; saving is disabled." };
    }
  });
  const [picks, setPicks] = useState<SavedPick[]>(initial.picks);
  const [signedIn, setSignedIn] = useState(initial.signedIn);
  const [error, setError] = useState(initial.error);

  const persist = (next: SavedPick[]) => {
    if (initial.error) return false;
    try {
      writePicks(window.localStorage, next, signedIn);
      setPicks(next);
      setError("");
      return true;
    } catch {
      setError("Could not save this change. Check that browser storage is allowed and the test profile is signed in.");
      return false;
    }
  };

  return <PersonalContext.Provider value={{
    picks, signedIn, error,
    login: (username, password) => {
      if (!demoCredentials(username, password)) return false;
      try {
        window.sessionStorage.setItem(SESSION_KEY, "jay");
        setSignedIn(true);
        return true;
      } catch { setError("Browser session storage is unavailable."); return false; }
    },
    logout: () => {
      setSignedIn(false);
      try { window.sessionStorage.removeItem(SESSION_KEY); }
      catch { setError("Could not clear the browser session marker. This is a demo, not a secure account."); }
    },
    save: pick => persist(picks.some(p => p.id === pick.id) ? picks : [pick, ...picks]),
    remove: id => { persist(picks.filter(p => p.id !== id)); },
    grade: (id, result) => { persist(picks.map(p => p.id === id ? { ...p, result } : p)); },
  }}>{children}</PersonalContext.Provider>;
}
