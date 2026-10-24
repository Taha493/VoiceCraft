import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import type { SegmentStatus, StageState } from '../api'
import { segmentStatus } from '../lib/status'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

const variants: Record<Variant, string> = {
  primary: 'bg-accent-strong text-white hover:bg-accent disabled:bg-accent-strong/40 shadow-sm shadow-black/40',
  secondary: 'bg-raised text-ink border border-line-strong hover:border-faint disabled:opacity-50',
  ghost: 'text-muted hover:text-ink hover:bg-raised disabled:opacity-40',
  danger: 'text-st-overrun hover:bg-st-overrun/10 disabled:opacity-40',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  busy,
  icon,
  children,
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md'; busy?: boolean; icon?: ReactNode }) {
  const sz = size === 'sm' ? 'h-7 px-2.5 text-xs gap-1.5' : 'h-9 px-3.5 text-sm gap-2'
  return (
    <button
      className={`inline-flex items-center justify-center rounded-lg font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed ${sz} ${variants[variant]} ${className}`}
      disabled={busy || rest.disabled}
      {...rest}
    >
      {busy ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  )
}

export function ProgressBar({ value, active }: { value: number; active?: boolean }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line">
      <div
        className={`h-full rounded-full bg-accent transition-[width] duration-300 ${active ? 'animate-pulse-bar' : ''}`}
        style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
      />
    </div>
  )
}

export function StageProgress({ stage, label }: { stage: StageState; label: string }) {
  if (stage.status !== 'running' && stage.status !== 'queued') return null
  return (
    <div className="space-y-2 rounded-xl border border-line bg-raised/60 p-3">
      <div className="flex items-center justify-between text-xs">
        <span className="flex items-center gap-2 text-ink">
          <Loader2 className="size-3.5 animate-spin text-accent" />
          {stage.status === 'queued' ? `${label}: waiting for another job…` : stage.message || label}
        </span>
        <span className="tabular text-muted">{Math.round(stage.progress * 100)}%</span>
      </div>
      <ProgressBar value={stage.progress} active />
    </div>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-line bg-panel p-4 ${className}`}>{children}</div>
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${checked ? 'bg-accent-strong' : 'bg-line-strong'}`}
      >
        <span className={`absolute top-0.5 left-0 size-4 rounded-full bg-white transition-transform ${checked ? 'translate-x-4.5' : 'translate-x-0.5'}`} />
      </button>
      <span className="text-sm">
        <span className="text-ink">{label}</span>
        {hint && <span className="mt-0.5 block text-xs text-muted">{hint}</span>}
      </span>
    </label>
  )
}


export function StatusChip({ status }: { status: SegmentStatus }) {
  const s = segmentStatus[status]
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border border-current/25 px-2 py-0.5 text-[11px] font-medium ${s.color}`} title={s.hint}>
      <span className={`size-1.5 rounded-full ${s.bg}`} />
      {s.label}
    </span>
  )
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'warn' | 'error'; children: ReactNode }) {
  const tones = {
    info: 'border-line bg-raised/50 text-muted',
    warn: 'border-st-sped/30 bg-st-sped/10 text-st-sped',
    error: 'border-st-overrun/30 bg-st-overrun/10 text-st-overrun',
  }
  return <div className={`rounded-lg border px-3 py-2 text-xs leading-relaxed ${tones[tone]}`}>{children}</div>
}
