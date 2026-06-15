import { useState } from 'react';

export default function AuthScreen({
  onLogin,
  onRegister,
}: {
  onLogin: (email: string, password: string) => Promise<void>;
  onRegister: (email: string, password: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await (mode === 'login' ? onLogin(email, password) : onRegister(email, password));
    } catch {
      setError(mode === 'login' ? 'Invalid email or password.' : 'Could not register (email may be taken).');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-[#0b0d12] text-neutral-100">
      <form onSubmit={submit} className="w-80 rounded-2xl border border-white/10 bg-[#11141b] p-6">
        <div className="mb-4 flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-sm bg-green-500" />
          <span className="text-lg font-semibold">FinSight</span>
        </div>
        {error && <div role="alert" className="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>}
        <input className="mb-2 w-full rounded-lg border border-white/10 bg-neutral-900 px-3 py-2 text-sm"
               type="email" placeholder="Email" value={email} required
               onChange={(e) => setEmail(e.target.value)} />
        <input className="mb-4 w-full rounded-lg border border-white/10 bg-neutral-900 px-3 py-2 text-sm"
               type="password" placeholder="Password" value={password} required minLength={6}
               onChange={(e) => setPassword(e.target.value)} />
        <button type="submit" disabled={busy}
                className="w-full rounded-lg bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-500 disabled:opacity-50">
          {mode === 'login' ? 'Log in' : 'Create account'}
        </button>
        <button type="button" className="mt-3 w-full text-center text-xs text-neutral-400 hover:text-neutral-200"
                onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null); }}>
          {mode === 'login' ? "No account? Sign up" : 'Have an account? Log in'}
        </button>
      </form>
    </div>
  );
}
