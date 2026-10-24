import { useMemo, useState } from 'react'
import { Minus, Plus } from 'lucide-react'
import type { Caption, Timeline } from '../api'
import { fmtTime, outputToVideo } from '../lib/time'
import { segmentStatus } from '../lib/status'

interface Props {
  duration: number
  captions: Caption[]
  timeline: Timeline | null
  videoTime: number
  selectedCaption: string | null
  onSeek: (videoTime: number) => void
  onSelectCaption: (id: string) => void
}

const LANE = 'relative h-9 rounded-md bg-raised/60'

/** Captions and narration on one ruler, in source-video time. Frame holds are shown as markers. */
export function TimelineView({ duration, captions, timeline, videoTime, selectedCaption, onSeek, onSelectCaption }: Props) {
  const [zoom, setZoom] = useState(1)
  const pct = (t: number) => `${(Math.max(0, Math.min(duration, t)) / duration) * 100}%`

  const ticks = useMemo(() => {
    const target = 12 * zoom
    const steps = [0.5, 1, 2, 5, 10, 15, 30, 60]
    const step = steps.find((s) => duration / s <= target) ?? 120
    return Array.from({ length: Math.floor(duration / step) + 1 }, (_, i) => i * step)
  }, [duration, zoom])

  const segments = useMemo(
    () =>
      (timeline?.segments ?? []).map((s) => ({
        ...s,
        vStart: outputToVideo(s.start, timeline!.holds),
        vEnd: outputToVideo(s.end, timeline!.holds),
      })),
    [timeline],
  )

  const seekFromEvent = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    onSeek(((e.clientX - r.left) / r.width) * duration)
  }

  return (
    <div className="rounded-xl border border-line bg-panel p-3">
      <div className="mb-2 flex items-center justify-between text-xs text-muted">
        <span className="tabular">
          {fmtTime(videoTime, true)} / {fmtTime(duration, true)}
          {timeline && timeline.output_duration > duration + 0.01 && (
            <span className="ml-2 text-st-held">+{(timeline.output_duration - duration).toFixed(2)}s held</span>
          )}
        </span>
        <span className="flex items-center gap-1">
          <button className="rounded p-1 hover:bg-raised hover:text-ink" onClick={() => setZoom((z) => Math.max(1, z / 2))} aria-label="Zoom out">
            <Minus className="size-3.5" />
          </button>
          <span className="tabular w-8 text-center">{zoom}×</span>
          <button className="rounded p-1 hover:bg-raised hover:text-ink" onClick={() => setZoom((z) => Math.min(16, z * 2))} aria-label="Zoom in">
            <Plus className="size-3.5" />
          </button>
        </span>
      </div>
      <div className="overflow-x-auto pb-1">
        <div className="relative space-y-1.5" style={{ width: `${zoom * 100}%`, minWidth: '100%' }}>
          <div className="relative h-5 cursor-pointer text-[10px] text-faint" onClick={seekFromEvent}>
            {ticks.map((t) => (
              <span key={t} className={`tabular absolute top-0 border-l border-line pl-1 ${t > 0 ? '-translate-x-px' : ''}`} style={{ left: pct(t) }}>
                {fmtTime(t)}
              </span>
            ))}
          </div>

          <div className={LANE} onClick={seekFromEvent}>
            {captions.map((c) => (
              <button
                key={c.id}
                title={c.text}
                onClick={(e) => {
                  e.stopPropagation()
                  onSelectCaption(c.id)
                  onSeek(c.start)
                }}
                className={`absolute top-1 bottom-1 truncate rounded px-1.5 text-left text-[11px] leading-7 transition-colors ${
                  selectedCaption === c.id ? 'bg-accent-strong text-white' : c.flagged ? 'bg-st-overrun/20 text-st-overrun ring-1 ring-st-overrun/50' : 'bg-line-strong text-ink hover:bg-faint/60'
                }`}
                style={{ left: pct(c.start), width: `calc(${pct(c.end)} - ${pct(c.start)})` }}
              >
                {c.text}
              </button>
            ))}
            {!captions.length && <span className="absolute inset-0 flex items-center px-3 text-[11px] text-faint">Captions appear here</span>}
          </div>

          <div className={LANE} onClick={seekFromEvent}>
            {segments.map((s) => (
              <div
                key={s.id}
                title={`${s.spoken_text}\n${segmentStatus[s.status].label}${s.note ? ` — ${s.note}` : ''}`}
                className={`absolute top-2 bottom-2 rounded-sm opacity-85 ${segmentStatus[s.status].bg}`}
                style={{ left: pct(s.vStart), width: `calc(${pct(s.vEnd)} - ${pct(s.vStart)})`, minWidth: 3 }}
              />
            ))}
            {timeline?.holds.map((h) => (
              <div key={h.segment_id} className="absolute top-0 bottom-0 w-0.5 bg-st-held" style={{ left: pct(h.video_time) }} title={`Frame held ${h.duration.toFixed(2)}s`}>
                <span className="tabular absolute -top-0.5 left-1 rounded bg-st-held/20 px-1 text-[9px] text-st-held">‖{h.duration.toFixed(1)}s</span>
              </div>
            ))}
            {!segments.length && <span className="absolute inset-0 flex items-center px-3 text-[11px] text-faint">Narration appears here</span>}
          </div>

          <div className="pointer-events-none absolute top-5 bottom-0 w-px bg-white/90" style={{ left: pct(videoTime) }}>
            <span className="absolute -top-1 -left-1 size-2 rounded-full bg-white" />
          </div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm bg-line-strong" /> Caption on screen
        </span>
        {Object.entries(segmentStatus).map(([k, v]) => (
          <span key={k} className="flex items-center gap-1.5" title={v.hint}>
            <span className={`h-2 w-4 rounded-sm ${v.bg}`} /> {v.label}
          </span>
        ))}
      </div>
    </div>
  )
}
