import { FormEvent, useState } from "react";
import { api, AppUser } from "../api/client";
import { errMsg } from "../hooks";
import { Icon, Logo } from "../components/ui";

export default function Login({ onLogin }: { onLogin: (user: AppUser, token: string) => void }) {
  const [username, setUsername] = useState("seller");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(undefined);
    try {
      const result = await api.login(username.trim(), password);
      sessionStorage.setItem("traceguard_token", result.access_token);
      onLogin(result.user, result.access_token);
    } catch (err) { setError(errMsg(err)); }
    finally { setBusy(false); }
  }

  return <div className="grid min-h-screen lg:grid-cols-2">
    <div className="relative hidden flex-col justify-between overflow-hidden bg-brand-dark p-12 text-white lg:flex">
      <div className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-white/5" />
      <div className="pointer-events-none absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-white/5" />
      <div className="relative flex items-center gap-3 font-semibold"><span className="grid h-10 w-10 place-items-center rounded-xl bg-white/15"><Icon name="shield" /></span>TraceGuard <span className="rounded border border-white/30 px-1.5 py-0.5 font-mono text-[10px]">V2</span></div>
      <div className="relative">
        <h1 className="text-4xl font-semibold leading-tight tracking-tight">A clearer chain of custody.</h1>
        <p className="mt-4 max-w-md leading-7 text-white/75">Sellers issue signed shipment labels. Authorised transporters scan at checkpoints. TraceGuard preserves the journey, flags conflicting evidence, and leaves the final judgement to a human reviewer.</p>
      </div>
      <ul className="relative grid gap-3 sm:grid-cols-3">
        {[["box", "Signed labels"], ["route", "Recorded handovers"], ["flag", "Explainable alerts"]].map(([ic, label]) => <li key={label} className="rounded-xl border border-white/15 bg-white/10 p-4"><Icon name={ic as "box"} className="h-5 w-5 text-white/80" /><p className="mt-3 text-sm font-medium">{label}</p></li>)}
      </ul>
    </div>
    <div className="grid place-items-center px-4 py-10">
      <form onSubmit={submit} className="card w-full max-w-md space-y-4 p-7">
        <div className="lg:hidden"><Logo /></div>
        <div><h2 className="text-xl font-semibold">Sign in</h2><p className="mt-1 text-sm text-mute">Use the account assigned to your role.</p></div>
        <label className="block"><span className="label">Username</span><input className="input" required autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} /></label>
        <label className="block"><span className="label">Password</span><input className="input" type="password" required autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
        {error && <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">{error}</p>}
        <button className="btn-primary w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in securely"}</button>
        <p className="text-xs leading-5 text-mute">Local demo accounts use the development password shown in the README. Change or remove these credentials before any shared or production deployment.</p>
      </form>
    </div>
  </div>;
}
