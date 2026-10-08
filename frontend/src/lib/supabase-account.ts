import type { SupabaseClient, User } from "@supabase/supabase-js";
import type { SavedPick, PickResult } from "./personal-picks";
import { decodePicks } from "./personal-picks";

export const LEGACY_PICK_COLUMNS = "id,player,opponent,date,projection,direction,line,odds,bookmaker,savedAt,result,demo";
export const PICK_COLUMNS = LEGACY_PICK_COLUMNS + ",version,kind,fingerprint,sport,event_id,home,away,market,selection,team,quote_updated_at,quote_fetched_at,source,model_version,profile,assumptions,analysis,model_generated_at,notes";
const v2Fields = ['version','kind','fingerprint','sport','event_id','home','away','market','selection','team','quote_updated_at','quote_fetched_at','source','model_version','profile','assumptions','analysis','model_generated_at'] as const;
const missingSchema = (error: {code?: string; message?: string} | null) => !!error && (error.code === '42703' || error.code === 'PGRST204');
export function pickInsert(pick: SavedPick, userId: string) {
  // Pin the request to the initiating user; RLS validates it against the JWT.
  const { id, player, opponent, date, projection, direction, line, odds, bookmaker, demo } = pick;
  const payload: Record<string, unknown> = { user_id: userId, id, player, opponent, date, projection, direction, line, odds, bookmaker, demo };
  if (pick.version === 2) for (const key of v2Fields) payload[key] = pick[key] ?? null;
  return payload;
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
  private identityGeneration = 0;
  private changing = false;
  private legacySchema = false;
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
    if (user?.id !== this.user?.id) { ++this.generation; ++this.identityGeneration; this.update({ picks: [], error: "" }); }
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
      let skipped = 0;
      for (let offset = 0; ; offset += 500) {
        if (!isCurrent()) return;
        let result: {data: unknown; error: {code?: string; message: string} | null} = await this.client.from("app_saved_picks").select(this.legacySchema ? LEGACY_PICK_COLUMNS : PICK_COLUMNS).eq("user_id", userId)
          .order("savedAt", { ascending: false }).order("id").range(offset, offset + 499);
        if (!this.legacySchema && missingSchema(result.error)) {
          this.legacySchema = true;
          result = await this.client.from("app_saved_picks").select(LEGACY_PICK_COLUMNS).eq("user_id", userId)
            .order("savedAt", { ascending: false }).order("id").range(offset, offset + 499);
        }
        if (result.error) throw result.error;
        if (!Array.isArray(result.data)) {
          throw Error('Saved-pick data has an unexpected format. Refresh to retry; no records have been deleted.');
        }
        const decoded = decodePicks(result.data);
        picks.push(...decoded.picks); skipped += decoded.skipped;
        if (result.data.length < 500) break;
      }
      if (isCurrent()) this.update({ picks, busy: false, error: [this.legacySchema ? "New selection saving is unavailable until the saved-picks database upgrade is applied. Existing picks remain available." : "", skipped ? `${skipped} saved record(s) have an unexpected format and were skipped. No records have been deleted.` : ""].filter(Boolean).join(" ") });
    } catch (error) { if (isCurrent()) { this.update({ picks: [] }); this.fail(error); } }
  }
  refresh = async () => {
    if (!this.client || this.changing) return;
    const current = this.generation;
    this.legacySchema = false;
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
    const identity = this.identityGeneration;
    try {
      const result = await operation(this.client, userId);
      if (result.error && !(duplicateOkay && result.error.code === "23505")) throw result.error;
      if (current !== this.generation || this.user?.id !== userId) return false;
      await this.load();
      // A write can succeed for its original owner while the visible account
      // changes during the reload. Do not report it as the new user's save.
      return this.user?.id === userId && identity === this.identityGeneration;
    } catch (error) { if (current === this.generation) this.fail(error); return false; }
    finally {
      this.changing = false;
      if (this.user?.id === userId) this.update({ busy: false });
      else if (this.user) void this.load();
    }
  }
  save = (pick: SavedPick) => {
    if (pick.version === 2 && this.legacySchema) {
      this.update({ error: "New selection saving is unavailable until the saved-picks database upgrade is applied." });
      return Promise.resolve(false);
    }
    if (this.user && !this.view.busy && this.view.picks.some(p => p.id === pick.id || pick.fingerprint && p.fingerprint === pick.fingerprint)) return Promise.resolve(true);
    return this.change((client, userId) => client.from("app_saved_picks").insert(pickInsert(pick, userId)), true)
      .then(ok => ok && this.view.picks.some(p => p.id === pick.id || !!pick.fingerprint && p.fingerprint === pick.fingerprint));
  };
  remove = (id: string) => this.change((client, userId) => client.from("app_saved_picks").delete().eq("user_id", userId).eq("id", id));
  grade = (id: string, result: PickResult) => this.change((client, userId) => client.from("app_saved_picks").update({ result }).eq("user_id", userId).eq("id", id));
  notes = (id: string, notes: string) => this.change((client, userId) => client.from("app_saved_picks").update({ notes: notes.slice(0, 5000) }).eq("user_id", userId).eq("id", id));
}
