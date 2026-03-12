import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-wheat focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-blackberry text-white shadow",
        secondary: "border-transparent bg-wheat/40 text-blackberry",
        destructive: "border-transparent bg-danger text-white shadow",
        outline: "border-soft-fawn/50 text-blackberry",
        success: "border-transparent bg-muted-teal/20 text-muted-teal",
        warning: "border-transparent bg-wheat/50 text-blackberry",
        muted: "border-transparent bg-grey/15 text-grey",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends
    React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
