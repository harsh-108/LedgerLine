import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Me, NavItem } from "./types";

/** The signed-in user, with role. Cached under the same key RequireAuth uses. */
export function useMe() {
  const q = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/auth/me"), retry: false });
  const isAdmin = q.data?.role === "admin";
  return { ...q, me: q.data, isAdmin };
}

/** Drop admin-only entries from a nav list for non-admins. */
export function visibleNav(items: NavItem[], isAdmin: boolean) {
  return isAdmin ? items : items.filter((i) => !i.adminOnly);
}
