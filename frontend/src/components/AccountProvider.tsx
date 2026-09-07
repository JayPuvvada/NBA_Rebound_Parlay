import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { PersonalContext } from "@/lib/personal-context";
import { SupabaseAccount } from "@/lib/supabase-account";
import { supabase, supabaseSetupError } from "@/lib/supabase";

export function AccountProvider({ children }: { children: ReactNode }) {
  const [account] = useState(() => new SupabaseAccount(supabase, supabaseSetupError));
  const view = useSyncExternalStore(account.subscribe, account.getSnapshot, account.getSnapshot);
  useEffect(() => {
    const stop = account.start();
    const refresh = () => { if (document.visibilityState === "visible") void account.refresh(); };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => { stop(); window.removeEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh); };
  }, [account]);
  return <PersonalContext.Provider value={{ ...view, login: account.login, logout: account.logout,
    save: account.save, remove: id => { void account.remove(id); },
    grade: (id, result) => { void account.grade(id, result); }, refresh: () => { void account.refresh(); },
  }}>{children}</PersonalContext.Provider>;
}
