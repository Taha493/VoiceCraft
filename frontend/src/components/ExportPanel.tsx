import { useState } from 'react'
import { Check, CheckCircle2, Copy, Download, Film } from 'lucide-react'
import type { Job, Timeline } from '../api'
import { api } from '../api'
import { fmtTime } from '../lib/time'
import { Button, Card, Notice } from './ui'

interface Props {
  job: Job
  timeline: Timeline | null
  showingOutput: boolean
  onShowOutput: (v: boolean) => void
}

export function ExportPanel({ job, timeline, showingOutput, onShowOutput }: Props) {
  const render = job.stages.render
  const r = render.result as Record<string, string | number>
  const [copied, setCopied] = useState(false)
  const credit = String(r.music_credit ?? '')
  if (render.status !== 'done' && render.status !== 'stale') {
    return (
      <Card>
        <p className="text-sm text-muted">Generate the voice-over first. The finished video appears here, ready to preview and download.</p>
      </Card>
    )
  }
  const flagged = timeline?.segments.filter((s) => s.status === 'overrun').length ?? 0
  return (
    <div className="space-y-4">
      {render.status === 'stale' && <Notice tone="warn">Settings or captions changed since this render. Regenerate on the Voice tab to update it.</Notice>}
      <Card className="space-y-3">
        <div className="flex items-center gap-2 text-sm text-ink">
          <CheckCircle2 className="size-4 text-st-fits" /> Narrated video ready
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
          <dt className="text-muted">Length</dt>
          <dd className="tabular text-ink">
            {fmtTime(Number(r.output_duration ?? job.info.duration), true)}
            {timeline && timeline.output_duration > job.info.duration + 0.01 && (
              <span className="text-st-held"> (+{(timeline.output_duration - job.info.duration).toFixed(2)}s from frame holds)</span>
            )}
          </dd>
          <dt className="text-muted">Video</dt>
          <dd className="text-ink">{String(r.video ?? '')}</dd>
          <dt className="text-muted">Loudness</dt>
          <dd className="text-ink">{String(r.final_loudness ?? r.narration_loudness ?? '')}</dd>
          <dt className="text-muted">Music</dt>
          <dd className="text-ink">{String(r.music ?? 'none')}</dd>
          <dt className="text-muted">Original audio</dt>
          <dd className="text-ink">{String(r.original_audio ?? '')}</dd>
          <dt className="text-muted">Voice</dt>
          <dd className="text-ink">
            {timeline?.voice} · {timeline?.preset}
          </dd>
        </dl>
        {credit && (
          <div className="space-y-1.5 rounded-lg border border-line bg-raised/50 p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-ink">Music credit (required)</span>
              <button
                className="flex items-center gap-1 text-[11px] text-muted hover:text-ink"
                onClick={() => {
                  void navigator.clipboard?.writeText(credit)
                  setCopied(true)
                  setTimeout(() => setCopied(false), 1500)
                }}
              >
                {copied ? <Check className="size-3" /> : <Copy className="size-3" />} {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <p className="text-[11px] leading-relaxed whitespace-pre-line text-muted">{credit}</p>
            <p className="text-[11px] text-faint">Paste this in the video description or end credits wherever you publish.</p>
          </div>
        )}
        {flagged > 0 && <Notice tone="warn">{flagged} segment(s) run long. Check them on the Voice tab before sharing.</Notice>}
        <div className="flex gap-2">
          <Button variant="primary" icon={<Download className="size-4" />} className="flex-1" onClick={() => (window.location.href = api.downloadUrl(job.id))}>
            Download MP4
          </Button>
          <Button icon={<Film className="size-4" />} onClick={() => onShowOutput(!showingOutput)}>
            {showingOutput ? 'Show original' : 'Preview'}
          </Button>
        </div>
      </Card>
      <p className="text-[11px] leading-relaxed text-faint">Your original video is never modified. Everything ran on this computer.</p>
    </div>
  )
}
