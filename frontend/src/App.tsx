import { Link, NavLink, Outlet } from 'react-router-dom'

/**
 * Two nav layouts sharing the same links:
 *   md+ — inline pills in the sticky header. No bottom bar; the pb-20
 *         mobile safety margin is removed so main content isn't
 *         floating above blank space.
 *   <md — bottom tab bar (thumb-reachable on a phone), header keeps
 *         only the title.
 */
export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 pb-20 md:pb-0">
      <header className="sticky top-0 z-10 bg-slate-950/95 backdrop-blur border-b border-slate-800 px-4 py-3">
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
          <Link to="/" className="text-lg font-semibold">funscript-gen</Link>
          <nav className="hidden md:flex gap-1">
            <HeaderTabLink to="/">Videos</HeaderTabLink>
            <HeaderTabLink to="/upload">Upload</HeaderTabLink>
            <HeaderTabLink to="/jobs">Jobs</HeaderTabLink>
          </nav>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
      <nav className="fixed bottom-0 inset-x-0 bg-slate-900 border-t border-slate-800 grid grid-cols-3 text-sm md:hidden">
        <BottomTabLink to="/">Videos</BottomTabLink>
        <BottomTabLink to="/upload">Upload</BottomTabLink>
        <BottomTabLink to="/jobs">Jobs</BottomTabLink>
      </nav>
    </div>
  )
}

function HeaderTabLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `px-3 py-1.5 rounded text-sm transition-colors ${
          isActive
            ? 'bg-indigo-600 text-white'
            : 'text-slate-300 hover:bg-slate-800'
        }`
      }
    >
      {children}
    </NavLink>
  )
}

function BottomTabLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `py-4 text-center touch-manipulation ${
          isActive ? 'text-indigo-400 bg-slate-800/60' : 'text-slate-300'
        }`
      }
    >
      {children}
    </NavLink>
  )
}
