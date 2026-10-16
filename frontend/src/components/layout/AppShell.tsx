import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getUser, setUser } from "../../api/client";
import { useHealth } from "../../api/hooks";
import logo from "../../assets/ferguson-logo-light.svg";
import { SearchBox } from "../ui";
import "./layout.css";

function HealthDot({ label, ok, title }: { label: string; ok: boolean | undefined; title?: string }) {
  return (
    <span className="health__item" title={title ?? `${label}: ${ok === undefined ? "checking" : ok ? "ok" : "down"}`}>
      <span className={`dot ${ok === undefined ? "" : ok ? "dot--ok" : "dot--down"}`} /> {label}
    </span>
  );
}

/** Same structure as ferguson.com: a dark utility bar, then the navy header with the white logo. */
export function AppShell({ children }: { children: ReactNode }) {
  const health = useHealth();
  const h = health.data;
  const [name, setName] = useState(getUser());
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  useEffect(() => {
    if (location.pathname === "/") setSearch(params.get("q") ?? ""); // keep in step with the list's filters
  }, [location.pathname, params]);
  // not configured is a choice, not a failure: grey dot, labelled "off"
  const serpOk = !h || h.serpapi === "not configured" ? undefined : h.serpapi === "ok";
  return (
    <div className="shell">
      <header className="masthead">
        <div className="utility">
          <div className="utility__inner">
            <label className="whoami">
              <span>Your name</span>
              <input
                className="input whoami__input"
                placeholder="shown in the edit log"
                maxLength={80}
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setUser(e.target.value.trim());
                }}
              />
            </label>
            <div className="health" aria-label="Service status">
              <HealthDot label="API" ok={health.isError ? false : h ? h.api === "ok" : undefined} />
              <HealthDot label="Queue" ok={h ? h.queue === "ok" && h.redis === "ok" : health.isError ? false : undefined} />
              <HealthDot label={h?.serpapi === "not configured" ? "SerpApi off" : "SerpApi"} ok={serpOk}
                         title={h ? `SerpApi: ${h.serpapi}${h.serpapi === "ok" ? "" : " (products are read from ferguson.com directly)"}` : undefined} />
              <HealthDot label="ferguson.com" ok={h ? h.chrome === "ok" : undefined}
                         title={h ? `Product pages via Chrome: ${h.chrome}; max ${h.ferguson_rate_per_minute} page loads per minute` : undefined} />
              {h && <span>{h.mode === "offline" ? "offline mode" : `live · ${h.ferguson_rate_per_minute}/min`}</span>}
            </div>
          </div>
        </div>
        <div className="topbar">
          <div className="topbar__inner">
            <Link to="/" className="brand" aria-label="Ferguson RFQ Agent, home">
              <img src={logo} alt="Ferguson" className="brand__logo" width={170} height={22} />
              <span className="brand__divider" aria-hidden="true" />
              <span className="brand__product">RFQ Agent</span>
            </Link>
            <nav className="topnav">
              <NavLink to="/" end>
                Requests
              </NavLink>
            </nav>
            <div className="topbar__search">
              <SearchBox
                tone="brand"
                label="Search RFQ requests"
                value={search}
                onChange={setSearch}
                placeholder="Search requests: subject, sender, product ID…"
                onSubmit={(text) => navigate(text ? `/?q=${encodeURIComponent(text)}` : "/")}
                onPick={(s) => {
                  setSearch("");
                  navigate(`/?${s.field}=${encodeURIComponent(s.value)}`);
                }}
              />
            </div>
          </div>
        </div>
      </header>
      <main className="page">{children}</main>
    </div>
  );
}
