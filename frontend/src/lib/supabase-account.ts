import type { SupabaseClient, User } from "@supabase/supabase-js";
import type { SavedPick, PickResult } from "./personal-picks";

export const PICK_COLUMNS = "id,player,opponent,date,projection,direction,line,odds,bookmaker,savedAt,result,demo";
export function pickInsert(pick: SavedPick, userId: string) {
  // Pin the request to the initiating user; RLS validates it against the JWT.
  const { id, player, opponent, date, projection, direction, line, odds, bookmaker, demo } = pick;
  return { user_id: userId, id, player, opponent, date, projection, direction, line, odds, bookmaker, demo };
}
export interface AccountView {
  mode: "account"; enabled: boolean; busy: boolean; signedIn: boolean;
  username: string; picks: SavedPick[]; error: string;
}

// Framework-independent store makes auth transitions and late responses testable.
export class SupabaseAccount {
  private view: AccountView;
  private user: User | null = null;
  private generation = 0;
  private changing = false;
  private listeners = new Set<() => void>();
  private client: SupabaseClient | null;
  constructor(client: SupabaseClient | null, setupError = "") {
    this.client = client;
    this.view = { mode: "account", enabled: !!client, busy: !!client, signedIn: false, username: "", picks: [], error: setupError };
  }
  getSnapshot = () => this.view;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private update(value: Partial<AccountView>) { this.view = { ...this.view, ...value }; this.listeners.forEach(listener => listener()); }
  private identify(user: User | null) {
    if (user?.id !== this.user?.id) { ++this.generation; this.update({ picks: [], error: "" }); }
    this.user = user;
    this.update({ signedIn: !!user, username: user?.email || "", ...(!user ? { picks: [], busy: false } : {}) });
  }
  start() {
    if (!this.client) return () => {};
    let active = true;
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const { data: { subscription } } = this.client.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      this.identify(session?.user ?? null);
      // Never await SDK calls inside its auth callback, which holds an auth lock.
      const timer = setTimeout(() => { timers.delete(timer); if (active && !this.changing) void this.load(); }, 0);
      timers.add(timer);
    });
    return () => { active = false; ++this.generation; timers.forEach(clearTimeout); subscription.unsubscribe(); };
  }
  private fail(error: unknown) {
    const message = error && typeof error === "object" && "message" in error ? String(error.message) : "Cannot reach Supabase. Check your connection and whether the project is paused.";
    this.update({ error: message, busy: false });
  }
  private async load() {
    if (!this.client || !this.user) return;
    const userId = this.user.id;
    const current = ++this.generation;
    const isCurrent = () => current === this.generation && this.user?.id === userId;
    this.update({ busy: true });
    try {
      const member = await this.client.from("app_pick_members").select("user_id").eq("user_id", userId).maybeSingle();
      if (member.error) throw member.error;
      if (!member.data) throw Error("This account has not been granted access to saved picks. The owner must add it to app_pick_members.");
      const picks: SavedPick[] = [];
      for (let offset = 0; ; offset += 500) {
        if (!isCurrent()) return;
        const result = await this.client.from("app_saved_picks").select(PICK_COLUMNS).eq("user_id", userId)
          .order("savedAt", { ascending: false }).order("id").range(offset, offset + 499);
        if (result.error) throw result.error;
        picks.push(...result.data as SavedPick[]);
        if (result.data.length < 500) break;
      }
      if (isCurrent()) this.update({ picks, busy: false, error: "" });
    } catch (error) { if (isCurrent()) { this.update({ picks: [] }); this.fail(error); } }
  }
  refresh = async () => {
    if (!this.client || this.changing) return;
    const current = this.generation;
    try {
      const { data, error } = await this.client.auth.getSession();
      if (error) throw error;
      if (current !== this.generation) return;
      this.identify(data.session?.user ?? null);
      await this.load();
    } catch (error) { if (current === this.generation) { this.identify(null); this.fail(error); } }
  };
  login = async (email: string, password: string) => {
    if (!this.client || this.changing) return false;
    this.changing = true;
    this.update({ busy: true, error: "" });
    try {
      const { data, error } = await this.client.auth.signInWithPassword({ email: email.trim(), password });
      if (error) throw error;
      this.identify(data.user);
      await this.load();
      return true;
    } catch (error) { this.fail(error); return false; }
    finally { this.changing = false; this.update({ busy: false }); }
  };
  signup = async (email: string, password: string): Promise<"confirmation" | "signed-in" | false> => {
    if (!this.client || this.changing || this.user) return false;
    this.changing = true;
    this.update({ busy: true, error: "" });
    try {
      if (password.length < 12) throw Error("Choose a password with at least 12 characters.");
      const { data, error } = await this.client.auth.signUp({
        email: email.trim(), password,
        options: typeof window === "undefined" ? undefined : {
          emailRedirectTo: `${window.location.origin}/#picks`,
        },
      });
      if (error) throw error;
      // A pending or intentionally obscured existing user is NOT a session.
      if (!data.session) return "confirmation";
      this.identify(data.session.user);
      await this.load();
      return "signed-in";
    } catch (error) { this.fail(error); return false; }
    finally { this.changing = false; this.update({ busy: false }); }
  };
  logout = async () => {
    if (!this.client || this.changing) return;
    this.changing = true;
    this.update({ busy: true });
    try {
      const { error } = await this.client.auth.signOut({ scope: "local" });
      if (error) throw error;
      this.identify(null);
    } catch (error) { this.fail(error); }
    finally { this.changing = false; this.update({ busy: false }); }
  };
  private async change(operation: (client: SupabaseClient, userId: string) => PromiseLike<{ error: { code?: string; message: string } | null }>, duplicateOkay = false) {
    if (!this.client || !this.user || this.changing || this.view.busy) return false;
    this.changing = true;
    const userId = this.user.id;
    const current = ++this.generation;
    this.update({ busy: true, error: "" });
    try {
      const result = await operation(this.client, userId);
      if (result.error && !(duplicateOkay && result.error.code === "23505")) throw result.error;
      if (current === this.generation && this.user?.id === userId) await this.load();
      return true;
    } catch (error) { if (current === this.generation) this.fail(error); return false; }
    finally {
      this.changing = false;
      if (this.user?.id === userId) this.update({ busy: false });
      else if (this.user) void this.load();
    }
  }
  save = (pick: SavedPick) => this.change((client, userId) => client.from("app_saved_picks").insert(pickInsert(pick, userId)), true);
  remove = (id: string) => this.change((client, userId) => client.from("app_saved_picks").delete().eq("user_id", userId).eq("id", id));
  grade = (id: string, result: PickResult) => this.change((client, userId) => client.from("app_saved_picks").update({ result }).eq("user_id", userId).eq("id", id));
}
