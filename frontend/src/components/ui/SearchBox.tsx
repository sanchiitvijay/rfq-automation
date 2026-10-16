import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useSuggestions } from "../../api/hooks";
import type { Suggestion } from "../../api/types";
import { useDebounced } from "../../hooks/useDebounced";

interface Props {
  value: string;
  onChange: (text: string) => void;
  /** Enter on free text */
  onSubmit: (text: string) => void;
  /** A suggestion was chosen (filters by that field) */
  onPick: (s: Suggestion) => void;
  placeholder?: string;
  maxLength?: number;
  tone?: "light" | "brand";
  label: string;
  id?: string;
}

function Highlight({ text, term }: { text: string; term: string }) {
  const i = text.toLowerCase().indexOf(term.toLowerCase());
  if (!term || i < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <mark>{text.slice(i, i + term.length)}</mark>
      {text.slice(i + term.length)}
    </>
  );
}

/** Search field with suggestions from the database (subjects, senders, product IDs). */
export function SearchBox({ value, onChange, onSubmit, onPick, placeholder, maxLength = 200, tone = "light", label, id }: Props) {
  const autoId = useId().replace(/:/g, ""); // ":r1:" is not a valid CSS id selector
  const inputId = id ?? `search-${autoId}`;
  const listId = `${inputId}-list`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const debounced = useDebounced(value, 220);
  const suggestions = useSuggestions(open ? debounced : "");
  const items = useMemo(() => suggestions.data ?? [], [suggestions.data]);
  const blurTimer = useRef<number | undefined>(undefined);
  const showList = open && value.trim().length >= 2 && (items.length > 0 || suggestions.isFetching || suggestions.isSuccess);

  const pick = (s: Suggestion) => {
    onPick(s);
    setOpen(false);
    setActive(-1);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => (items.length ? (a + 1) % items.length : -1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (items.length ? (a <= 0 ? items.length - 1 : a - 1) : -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const chosen = active >= 0 ? items[active] : undefined;
      if (chosen) pick(chosen);
      else {
        onSubmit(value.trim());
        setOpen(false);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <div className={`searchbox searchbox--${tone}`}>
      <label htmlFor={inputId} className="visually-hidden">
        {label}
      </label>
      <input
        id={inputId}
        className="input searchbox__input"
        type="search"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        autoComplete="off"
        spellCheck={false}
        value={value}
        maxLength={maxLength}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => (blurTimer.current = window.setTimeout(() => setOpen(false), 150))}
        onKeyDown={onKey}
      />
      {showList && (
        <ul id={listId} role="listbox" className="searchbox__list" onMouseDown={() => window.clearTimeout(blurTimer.current)}>
          {items.length === 0 ? (
            <li className="searchbox__empty" role="presentation">
              {suggestions.isFetching ? "Searching…" : "No matches. Press Enter to search all text."}
            </li>
          ) : (
            items.map((s, i) => (
              <li
                key={`${s.field}-${s.value}`}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                className="searchbox__option"
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(s);
                }}
              >
                <span className="searchbox__field">{s.label}</span>
                <span className="searchbox__value">
                  <Highlight text={s.value} term={debounced.trim()} />
                </span>
                <span className="searchbox__count num">{s.count}</span>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
