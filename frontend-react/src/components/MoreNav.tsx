import { SubNav } from "./Section";
import { MORE } from "../lib/nav";
import { useMe, visibleNav } from "../lib/useMe";

/** The "More" sub-navigation, without admin-only entries for non-admins. */
export function MoreNav() {
  const { isAdmin } = useMe();
  return <SubNav items={visibleNav(MORE, isAdmin)} />;
}
