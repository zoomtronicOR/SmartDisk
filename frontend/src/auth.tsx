import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { api, ApiError } from "./api";
import type { User } from "./types";

type AuthState = { user: User | null; loading: boolean; refresh: () => Promise<void>; logout: () => Promise<void> };

const AuthContext = createContext<AuthState | null>(null);

async function fetchMe(): Promise<User | null> {
  try {
    return await api<User>("/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe, retry: false, staleTime: 60_000 });

  useEffect(() => {
    const onUnauthorized = () => {
      queryClient.setQueryData(["me"], null);
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    };
    window.addEventListener("sd:unauthorized", onUnauthorized);
    return () => window.removeEventListener("sd:unauthorized", onUnauthorized);
  }, [queryClient]);

  const state: AuthState = {
    user: me.data ?? null,
    loading: me.isLoading,
    refresh: async () => {
      await queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    logout: async () => {
      try {
        await api("/auth/logout", { method: "POST" });
      } finally {
        queryClient.clear();
        queryClient.setQueryData(["me"], null);
      }
    },
  };
  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("AuthProvider nedostaje");
  return ctx;
}
