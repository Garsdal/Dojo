import { NavLink } from "react-router-dom";
import { LayoutGrid } from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [{ to: "/", label: "Domains", icon: LayoutGrid }];

export function Sidebar() {
  return (
    <aside className="hidden md:flex w-56 border-r border-soft-fawn/20 bg-surface flex-col py-4">
      <nav className="flex flex-col gap-1 px-3">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-xl px-4 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-wheat/40 text-blackberry font-semibold"
                  : "text-grey hover:bg-wheat/20 hover:text-blackberry",
              )
            }
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
