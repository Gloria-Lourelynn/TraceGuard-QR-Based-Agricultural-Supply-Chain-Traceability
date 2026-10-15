import { Component, useEffect, useState } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, AppUser } from "./api/client";
import Dashboard from "./pages/Dashboard";
import Register from "./pages/Register";
import Scan from "./pages/Scan";
import Shipment from "./pages/Shipment";
import Reports from "./pages/Reports";
import Login from "./pages/Login";
import Admin from "./pages/Admin";
import { Icon, Logo } from "./components/ui";

type BoundaryState = { error: Error | null };

/** Prevent one broken route from blanking the entire app; show the actual runtime error. */
class PageErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("TraceGuard page render failed:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <section className="card mx-auto max-w-3xl space-y-3 p-6" role="alert">
          <h1 className="text-xl font-semibold">This page failed to render</h1>
          <p className="text-sm text-mute">TraceGuard caught a frontend error instead of showing a blank screen. Copy the message below when reporting the issue.</p>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-raised p-3 text-xs text-bad">{this.state.error.message || String(this.state.error)}</pre>
          <button className="btn-ghost" onClick={() => window.location.reload()}>Reload page</button>
        </section>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const location = useLocation();
  const [user, setUser] = useState<AppUser | null>(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    const token = sessionStorage.getItem("traceguard_token");
    if (!token) { setChecking(false); return; }
    api.me().then(setUser).catch(() => { sessionStorage.removeItem("traceguard_token"); setUser(null); }).finally(() => setChecking(false));
  }, []);

  if (checking) return <div className="grid min-h-screen place-items-center text-sm text-mute">Checking session…</div>;
  if (!user) return <main className="min-h-screen"><Login onLogin={(next, token) => { sessionStorage.setItem("traceguard_token", token); setUser(next); }} /></main>;

  const nav = [
    { to: "/", label: "Dashboard", icon: "dashboard" as const, show: true, end: true },
    { to: "/register", label: "Register produce", icon: "box" as const, show: user.role === "seller" || user.role === "admin" },
    { to: "/scan", label: "Scan / handover", icon: "scan" as const, show: user.role !== "seller" },
    { to: "/shipments", label: "Farm-to-market trail", icon: "route" as const, show: true },
    { to: "/admin", label: "Admin", icon: "settings" as const, show: user.role === "admin" },
  ].filter(n => n.show);

  const signOut = () => { void api.logout().catch(() => {}).finally(() => { sessionStorage.removeItem("traceguard_token"); setUser(null); }); };
  const brand = <NavLink to="/" className="flex items-center gap-2.5 font-semibold tracking-tight"><Logo /><span>TraceGuard <span className="ml-1 rounded border border-line px-1.5 py-0.5 font-mono text-[10px] font-medium text-mute">V2</span></span></NavLink>;

  return <div className="min-h-screen lg:flex">
    {/* Desktop sidebar */}
    <aside className="no-print sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-line bg-panel px-4 py-5 lg:flex">
      <div className="px-2">{brand}</div>
      <nav className="mt-8 flex flex-1 flex-col gap-1 text-sm">
        {nav.map(n => <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2.5 font-medium transition ${isActive ? "bg-brand/10 text-brand-dark" : "text-mute hover:bg-raised hover:text-ink"}`}><Icon name={n.icon} className="h-[18px] w-[18px]" />{n.label}</NavLink>)}
      </nav>
      <div className="rounded-xl border border-line bg-raised/60 p-3">
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand text-sm font-semibold text-white">{user.display_name.slice(0, 1).toUpperCase()}</span>
          <div className="min-w-0"><p className="truncate text-sm font-medium">{user.display_name}</p><p className="text-xs capitalize text-mute">{user.role}</p></div>
        </div>
        <button className="btn-ghost mt-3 w-full !py-1.5 text-xs" onClick={signOut}><Icon name="logout" className="h-4 w-4" />Sign out</button>
      </div>
    </aside>

    {/* Mobile / tablet top bar */}
    <header className="no-print sticky top-0 z-10 border-b border-line bg-panel/95 backdrop-blur lg:hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        {brand}
        <div className="flex items-center gap-2 text-xs"><span className="hidden text-mute sm:inline">{user.display_name} · <span className="capitalize">{user.role}</span></span><button className="btn-ghost !px-2.5 !py-1" onClick={signOut} aria-label="Sign out"><Icon name="logout" className="h-4 w-4" /></button></div>
      </div>
      <nav className="flex gap-1 overflow-x-auto px-3 pb-2 text-sm">
        {nav.map(n => <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 font-medium transition ${isActive ? "bg-brand/10 text-brand-dark" : "text-mute hover:text-ink"}`}><Icon name={n.icon} className="h-4 w-4" />{n.label}</NavLink>)}
      </nav>
    </header>

    <main className="min-w-0 flex-1 px-4 py-8 sm:px-8">
      <div className="mx-auto max-w-6xl">
        <PageErrorBoundary key={location.pathname}>
          <Routes>
            <Route path="/" element={<Dashboard role={user.role} />} />
            <Route path="/register" element={user.role === "seller" || user.role === "admin" ? <Register /> : <Denied />} />
            <Route path="/scan" element={user.role !== "seller" ? <Scan role={user.role} /> : <Denied />} />
            <Route path="/shipments" element={<Reports />} />
            <Route path="/shipments/:id" element={<Shipment role={user.role} />} />
            <Route path="/shipments/:id/report" element={<Reports />} />
            <Route path="/admin" element={user.role === "admin" ? <Admin /> : <Denied />} />
            <Route path="*" element={<p className="py-20 text-center text-mute">Page not found.</p>} />
          </Routes>
        </PageErrorBoundary>
      </div>
    </main>
  </div>;
}

function Denied() { return <div className="card p-6"><h1 className="font-semibold">Not available for this role</h1><p className="mt-2 text-sm text-mute">Your account does not have permission to open this page.</p></div>; }
