import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-all duration-150 active:scale-95 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 cursor-pointer select-none',
  {
    variants: {
      variant: {
        default: 'bg-[var(--alist-main)] text-white shadow-xs hover:opacity-90',
        subtle:
          'bg-[var(--alist-main-subtle)] text-[var(--alist-main)] hover:bg-[var(--alist-main-subtle-hover)]',
        destructive:
          'bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/20 hover:bg-rose-500/25',
        outline:
          'border border-border bg-card/80 hover:bg-[var(--alist-hover)] text-foreground',
        secondary:
          'bg-secondary text-secondary-foreground hover:bg-[var(--alist-hover)]',
        ghost: 'hover:bg-[var(--alist-hover)] text-foreground',
        link: 'text-[var(--alist-main)] underline-offset-4 hover:underline',
        success:
          'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/25',
        warning:
          'bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/20 hover:bg-amber-500/25',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 rounded-lg px-3 text-xs',
        lg: 'h-10 rounded-lg px-8',
        icon: 'h-9 w-9 rounded-lg',
        iconSm: 'h-7 w-7 rounded-md text-xs',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  },
);
Button.displayName = 'Button';

export { Button, buttonVariants };
