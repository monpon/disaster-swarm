import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cn } from "@swarm/ui/lib/utils";
import { cva, type VariantProps } from "class-variance-authority";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap font-medium outline-none select-none transition-[transform,box-shadow] focus-visible:ring-2 focus-visible:ring-orange/40 active:translate-y-px disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "btn-primary font-semibold active:shadow-[inset_0_1px_0_rgb(255_255_255/0.35),0_1px_0_var(--color-orange-deep)]",
        secondary: "btn-secondary hover:brightness-[1.02] active:shadow-[0_0_0_1px_var(--color-line-strong),0_1px_0_var(--color-line-strong)]",
        dark: "btn-dark font-semibold",
        ghost: "text-muted hover:bg-ink/5 hover:text-ink",
      },
      size: {
        sm: "h-8 rounded-[7px] px-2.5 text-[13px] [&_svg]:size-3.5",
        md: "h-9 rounded-lg px-3 text-sm [&_svg]:size-3.5",
        lg: "h-[42px] rounded-[9px] px-4 text-[15px] [&_svg]:size-4",
        xl: "h-[50px] rounded-[11px] px-5 text-base [&_svg]:size-4",
        icon: "size-8 rounded-[7px] [&_svg]:size-3.5",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "md",
    },
  },
);

function Button({
  className,
  variant,
  size,
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return <ButtonPrimitive data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export { Button, buttonVariants };
