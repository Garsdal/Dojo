import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
  className?: string;
}

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  return (
    <nav className={cn("flex items-center gap-1 text-sm", className)} aria-label="Breadcrumb">
      {items.map((item, index) => (
        <span key={index} className="flex items-center gap-1">
          {index > 0 && <ChevronRight className="h-3.5 w-3.5 text-grey/50" />}
          {item.href && index < items.length - 1 ? (
            <Link
              to={item.href}
              className="text-grey hover:text-blackberry transition-colors"
            >
              {item.label}
            </Link>
          ) : (
            <span className="text-blackberry font-medium">{item.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
