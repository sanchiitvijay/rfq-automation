import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

export interface MenuItem {
  key: string;
  label: ReactNode;
  description?: ReactNode;
  onSelect?: () => void;
  /** a link (e.g. a download) instead of an action */
  href?: string;
  download?: boolean;
  danger?: boolean;
  disabled?: boolean;
  title?: string;
}

export interface MenuSection {
  title?: string;
  items: MenuItem[];
}

interface Props {
  /** text (or icon) of the trigger button */
  label: ReactNode;
  sections: MenuSection[];
  /** accessible name when the label is only an icon */
  ariaLabel?: string;
  variant?: "secondary" | "ghost" | "icon";
  size?: "md" | "sm";
  align?: "left" | "right";
  disabled?: boolean;
  width?: number;
  /** shown instead of the items (e.g. "Loading…") */
  placeholder?: ReactNode;
}

/**
 * A dropdown menu. The panel is rendered into <body> with fixed positioning, so it is never cut off by a
 * scrolling container (grid cells, cards). Keyboard: Enter/Space/↓ opens, ↑/↓ moves, Esc closes.
 */
export function Menu({ label, sections, ariaLabel, variant = "secondary", size = "md", align = "right", disabled, width = 260, placeholder }: Props) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; up: boolean } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = `menu-${useId().replace(/:/g, "")}`;

  const place = useCallback(() => {
    const r = trigger.current?.getBoundingClientRect();
    if (!r) return;
    const height = panel.current?.offsetHeight ?? 0;
    const up = r.bottom + 4 + height > window.innerHeight && r.top - 4 - height > 0;
    const left = align === "right" ? r.right - width : r.left;
    setPos({ top: up ? r.top - 4 - height : r.bottom + 4, left: Math.max(8, Math.min(left, window.innerWidth - width - 8)), up });
  }, [align, width]);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: globalThis.MouseEvent) => {
      const t = e.target as Node;
      if (!panel.current?.contains(t) && !trigger.current?.contains(t)) setOpen(false);
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    const onMove = () => setOpen(false); // the trigger moved (page or grid scrolled): close instead of floating away
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    panel.current?.querySelector<HTMLElement>("[role=menuitem]:not([aria-disabled=true])")?.focus({ preventScroll: true });
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
  }, [open]);

  const onPanelKey = (e: KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = [...(panel.current?.querySelectorAll<HTMLElement>("[role=menuitem]:not([aria-disabled=true])") ?? [])];
    const i = items.indexOf(document.activeElement as HTMLElement);
    items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus({ preventScroll: true });
  };

  const choose = (item: MenuItem) => {
    if (item.disabled) return;
    setOpen(false);
    item.onSelect?.();
  };

  const cls = variant === "icon" ? "menu-trigger--icon" : `btn btn--${variant} ${size === "sm" ? "btn--sm" : ""}`;
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={`menu-trigger ${cls}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={ariaLabel}
        title={ariaLabel}
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation(); // inside a clickable row/grid cell: don't also select the row
          setOpen((o) => !o);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        {label}
        {variant !== "icon" && <Chevron />}
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            id={id}
            role="menu"
            className="menu"
            style={{ width, top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}
            onKeyDown={onPanelKey}
            onMouseDown={(e) => e.stopPropagation()}
          >
            {placeholder ? (
              <div className="menu__placeholder">{placeholder}</div>
            ) : (
              sections.map((s, si) => (
                <div key={s.title ?? si} className="menu__section" role="group" aria-label={s.title}>
                  {s.title && <div className="menu__title">{s.title}</div>}
                  {s.items.map((item) =>
                    item.href && !item.disabled ? (
                      <a key={item.key} role="menuitem" tabIndex={-1} className={`menu__item ${item.danger ? "menu__item--danger" : ""}`}
                         href={item.href} download={item.download || undefined} title={item.title} onClick={() => choose(item)}>
                        <span className="menu__label">{item.label}</span>
                        {item.description && <span className="menu__desc">{item.description}</span>}
                      </a>
                    ) : (
                      <button key={item.key} type="button" role="menuitem" tabIndex={-1} aria-disabled={item.disabled || undefined}
                              className={`menu__item ${item.danger ? "menu__item--danger" : ""}`} title={item.title} onClick={() => choose(item)}>
                        <span className="menu__label">{item.label}</span>
                        {item.description && <span className="menu__desc">{item.description}</span>}
                      </button>
                    ),
                  )}
                </div>
              ))
            )}
          </div>,
          document.body,
        )}
    </>
  );
}

function Chevron() {
  return (
    <svg className="menu-trigger__chevron" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
      <path d="M1.5 3.5 5 7l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}
