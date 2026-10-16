import type { ReactNode } from "react";

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card__head">
          {typeof title === "string" ? <h3>{title}</h3> : title}
          {actions && <div>{actions}</div>}
        </div>
      )}
      <div className="card__body">{children}</div>
    </section>
  );
}
