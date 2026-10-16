import type { CustomCellEditorProps } from "ag-grid-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

export interface ChoiceEditorParams {
  /** the only values allowed (picked from the list, no typing) */
  choices?: string[];
  /** values already in use; the user may still type a new one */
  suggestions?: string[];
  unit?: string;
}

/**
 * Dropdown cell editor. With `choices` it is a strict pick-list (e.g. UL Listed: Yes / No); with
 * `suggestions` it is a text box with a filtered list of the values already used in this RFQ and the
 * catalog. The options come from the server (GET /sheet → options), never from the UI.
 */
export function ChoiceEditor(props: CustomCellEditorProps & ChoiceEditorParams) {
  const { value, onValueChange, stopEditing, choices, suggestions, unit, eventKey } = props;
  const strict = !!choices?.length;
  const all = useMemo(() => (strict ? choices! : suggestions ?? []), [strict, choices, suggestions]);
  // typing a character to start editing replaces the value, like any spreadsheet
  const [text, setText] = useState(() => (!strict && eventKey && eventKey.length === 1 ? eventKey : String(value ?? "")));
  const [active, setActive] = useState(0);
  // until the user types, the list shows every option (the cell's current value must not filter it)
  const [typed, setTyped] = useState(() => !strict && !!eventKey && eventKey.length === 1);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  const shown = useMemo(() => {
    if (strict) return all;
    const t = typed ? text.trim().toLowerCase() : "";
    return all.filter((v) => !t || (v.toLowerCase().includes(t) && v.toLowerCase() !== t)).slice(0, 50);
  }, [all, strict, text, typed]);

  useEffect(() => {
    if (!strict) onValueChange(text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  useEffect(() => {
    if (strict) {
      const i = all.indexOf(String(value ?? ""));
      setActive(i >= 0 ? i : 0);
      list.current?.focus();
    } else {
      input.current?.focus();
      if (!eventKey || eventKey.length !== 1) input.current?.select();
      setActive(-1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const pick = (v: string) => {
    onValueChange(v);
    setText(v);
    // let the grid read the new value before it closes the editor
    window.setTimeout(() => stopEditing(), 0);
  };

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      e.stopPropagation(); // the grid would move to the next row
      if (!shown.length) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((a) => (a + step + shown.length) % shown.length);
    } else if (e.key === "Enter" && active >= 0 && shown[active] !== undefined) {
      e.preventDefault();
      e.stopPropagation();
      pick(shown[active]!);
    }
  };

  return (
    <div className="choice-editor" onKeyDown={onKey}>
      {!strict && (
        <input
          ref={input}
          className="choice-editor__input"
          value={text}
          maxLength={2000}
          placeholder={unit ? `e.g. 12 ${unit}` : "Type or pick a value"}
          onChange={(e) => {
            setText(e.target.value);
            setTyped(true);
            setActive(-1);
          }}
        />
      )}
      {shown.length > 0 ? (
        <ul ref={list} className="choice-editor__list" role="listbox" tabIndex={strict ? 0 : -1} aria-label="Values">
          {shown.map((v, i) => (
            <li
              key={v}
              data-i={i}
              role="option"
              aria-selected={i === active}
              className={v === String(value ?? "") ? "is-current" : undefined}
              onMouseDown={(e) => e.preventDefault()} // keep focus in the editor
              onClick={() => pick(v)}
              onMouseEnter={() => setActive(i)}
            >
              {v}
            </li>
          ))}
        </ul>
      ) : (
        !strict && <div className="choice-editor__hint">{all.length ? "No used value matches; Enter keeps what you typed." : "Type a value; Enter saves it."}</div>
      )}
      {strict && (
        <div className="choice-editor__hint">
          <button type="button" className="linkish" onMouseDown={(e) => e.preventDefault()} onClick={() => pick("")}>
            Clear the cell
          </button>
        </div>
      )}
    </div>
  );
}
