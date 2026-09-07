import { createContext, useContext } from "react";
import type { SavedPick, PickResult } from "./personal-picks";

export interface PersonalState {
  mode?: "demo" | "account";
  enabled?: boolean;
  busy?: boolean;
  username?: string;
  signedIn: boolean;
  picks: SavedPick[];
  error: string;
  login: (username: string, password: string) => boolean | Promise<boolean>;
  logout: () => void | Promise<void>;
  save: (pick: SavedPick) => boolean | Promise<boolean>;
  remove: (id: string) => void;
  grade: (id: string, result: PickResult) => void;
  refresh?: () => void;
}
export const PersonalContext = createContext<PersonalState | null>(null);
export const usePersonalPicks = () => useContext(PersonalContext);
