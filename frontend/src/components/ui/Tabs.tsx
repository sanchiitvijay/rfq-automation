interface Props<T extends string> {
  value: T;
  onChange: (v: T) => void;
  items: { id: T; label: string; count?: number }[];
}

export function Tabs<T extends string>({ value, onChange, items }: Props<T>) {
  return (
    <div className="tabs" role="tablist">
      {items.map((it) => (
        <button key={it.id} role="tab" type="button" className="tab" aria-selected={value === it.id} onClick={() => onChange(it.id)}>
          {it.label}
          {it.count !== undefined && <span className="subtle num"> {it.count}</span>}
        </button>
      ))}
    </div>
  );
}
