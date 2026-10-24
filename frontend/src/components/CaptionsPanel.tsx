import { useRef, useState } from 'react'
import { AlertTriangle, Crop, FileText, Plus, RefreshCw, ScanText, Trash2, Upload } from 'lucide-react'
import type { Caption, CaptionTrack, Job } from '../api'
import { fmtTime, parseTime } from '../lib/time'
import { Button, Card, Notice, StageProgress, Toggle } from './ui'

interface Props {
  job: Job
  track: CaptionTrack | null
  draft: Caption[]
  dirty: boolean
  selected: string | null
  videoTime: number
  editingRegion: boolean
  onDraft: (c: Caption[]) => void
  onSave: () => Promise<void>
  onDetect: () => void
  onImportFile: (f: File) => Promise<void>
  onScript: (text: string) => Promise<void>
  onToggleRegion: () => void
  onBurnedChange: (v: boolean) => void
  onSaveRegion: () => Promise<void>
  onSelect: (id: string) => void
  onSeek: (t: number) => void
}

function TimeField({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [text, setText] = useState<string | null>(null)
  return (
    <input
      className="tabular w-[4.6rem] rounded-md border border-line bg-canvas px-1.5 py-1 text-xs text-ink focus:border-accent focus:outline-none"
      value={text ?? fmtTime(value, true)}
      onChange={(e) => setText(e.target.value)}
      onFocus={(e) => e.target.select()}
      onBlur={() => {
        const v = text === null ? null : parseTime(text)
        if (v !== null) onChange(v)
        setText(null)
      }}
      onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
    />
  )
}

export function CaptionsPanel(p: Props) {
  const { job, track, draft } = p
  const stage = job.stages.captions
  const running = stage.status === 'running' || stage.status === 'queued'
  const fileInput = useRef<HTMLInputElement>(null)
  const [scriptOpen, setScriptOpen] = useState(false)
  const [script, setScript] = useState('')
  const [busy, setBusy] = useState(false)
  const hasManual = track?.captions.some((c) => c.source !== 'ocr')
  const flagged = draft.filter((c) => c.flagged).length
  const burned = job.settings.has_burned_captions

  const update = (id: string, patch: Partial<Caption>) => p.onDraft(draft.map((c) => (c.id === id ? { ...c, ...patch } : c)))
  const remove = (id: string) => p.onDraft(draft.filter((c) => c.id !== id))
  const add = () => {
    const t = p.videoTime
    const c: Caption = { id: `new-${Date.now()}`, start: t, end: Math.min(job.info.duration, t + 2.5), text: 'New caption', confidence: 1, flagged: false, flag_reason: null, source: 'edit' }
    p.onDraft([...draft, c].sort((a, b) => a.start - b.start))
    p.onSelect(c.id)
  }
  const wrap = (fn: () => Promise<void>) => async () => {
    setBusy(true)
    try {
      await fn()
    } finally {
      setBusy(false)
    }
  }
  const detect = () => {
    if (hasManual && !confirm('Detecting again replaces the imported or edited captions. Continue?')) return
    p.onDetect()
  }

  return (
    <div className="space-y-4">
      <StageProgress stage={stage} label="Detecting captions" />
      {stage.status === 'error' && <Notice tone="error">Caption detection failed: {stage.error}</Notice>}
      {stage.status === 'stale' && <Notice tone="warn">The caption area or detection settings changed. Detect again to update the captions.</Notice>}

      <Card className="py-3">
        <Toggle
          checked={burned}
          onChange={p.onBurnedChange}
          label="This video already shows captions"
          hint={burned ? 'Captions are read from the video.' : 'No captions on screen. The voice follows your caption file or script.'}
        />
      </Card>

      {!track && !running && burned && (
        <Card className="space-y-3">
          <p className="text-sm text-muted">VoiceCraft reads the captions burned into the video. If you have the exact text, importing it is even more accurate.</p>
          <Button variant="primary" icon={<ScanText className="size-4" />} onClick={p.onDetect} className="w-full">
            Detect captions
          </Button>
        </Card>
      )}

      {!track && !burned && (
        <Card className="space-y-3">
          <p className="text-sm text-muted">Add the words for the voice: a caption file with timings (.srt, .vtt, .json) or a plain script, one line per caption.</p>
          <Button variant="primary" icon={<Upload className="size-4" />} onClick={() => fileInput.current?.click()} className="w-full">
            Choose caption file or script
          </Button>
        </Card>
      )}

      {track && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span>
            <b className="text-ink">{draft.length}</b> captions
          </span>
          {flagged > 0 && (
            <span className="flex items-center gap-1 text-st-overrun">
              <AlertTriangle className="size-3.5" /> {flagged} to review
            </span>
          )}
          {burned && track.region && track.ocr_engine !== 'import' && (
            <span>
              Area: {track.region.auto ? `auto${track.region.boxes?.length > 1 ? `, ${track.region.boxes.length} bands` : ''} (${Math.round(track.region.confidence * 100)}% sure)` : 'manual'}
            </span>
          )}
          {track.stats?.seconds != null && <span>{track.stats.seconds}s · {track.stats.ocr_calls} OCR reads</span>}
          {track.ocr_engine === 'import' && <span>Imported from file</span>}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {track && burned && (
          <Button size="sm" icon={<RefreshCw className="size-3.5" />} onClick={detect} disabled={running}>
            Detect again
          </Button>
        )}
        {burned && (
          <Button size="sm" variant={p.editingRegion ? 'primary' : 'secondary'} icon={<Crop className="size-3.5" />} onClick={p.onToggleRegion} disabled={running}>
            {p.editingRegion ? 'Cancel' : 'Adjust caption area'}
          </Button>
        )}
        <Button size="sm" icon={<Upload className="size-3.5" />} onClick={() => fileInput.current?.click()} disabled={running}>
          {burned ? 'Import SRT / VTT' : 'Replace caption file'}
        </Button>
        <Button size="sm" icon={<FileText className="size-3.5" />} onClick={() => setScriptOpen((o) => !o)} disabled={running}>
          Paste script
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept=".srt,.vtt,.json,.txt"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            e.target.value = ''
            if (f) void wrap(() => p.onImportFile(f))()
          }}
        />
      </div>

      {p.editingRegion && (
        <Card className="space-y-3 border-accent/50">
          <p className="text-xs text-muted">Drag on the video to draw the area where captions appear, or drag the box and its handles. Only text inside it is read. Dashed outlines show the bands found automatically; saving uses just your box.</p>
          <Button variant="primary" size="sm" busy={busy} onClick={wrap(p.onSaveRegion)} className="w-full">
            Use this area and detect again
          </Button>
        </Card>
      )}

      {scriptOpen && (
        <Card className="space-y-3">
          <p className="text-xs text-muted">
            {burned
              ? 'One caption per line. VoiceCraft keeps your exact wording and matches each line to the caption on screen for timing.'
              : 'One caption per line. Lines are spread across the video based on how long each takes to say; adjust the times afterwards if needed.'}
          </p>
          <textarea
            className="h-36 w-full resize-y rounded-lg border border-line bg-canvas p-2 text-sm text-ink focus:border-accent focus:outline-none"
            placeholder={'Meet VoiceCraft.\nTurn silent videos into narrated stories.'}
            value={script}
            onChange={(e) => setScript(e.target.value)}
          />
          <Button
            variant="primary"
            size="sm"
            busy={busy}
            disabled={!script.trim()}
            className="w-full"
            onClick={wrap(async () => {
              await p.onScript(script)
              setScriptOpen(false)
            })}
          >
            Use script
          </Button>
        </Card>
      )}

      {track && (
        <div className="space-y-2">
          {draft.map((c) => (
            <div
              key={c.id}
              onClick={() => {
                p.onSelect(c.id)
                p.onSeek(c.start)
              }}
              className={`group rounded-lg border p-2.5 transition-colors ${p.selected === c.id ? 'border-accent bg-accent-soft' : c.flagged ? 'border-st-overrun/40 bg-st-overrun/5' : 'border-line bg-panel hover:border-line-strong'}`}
            >
              <div className="mb-1.5 flex items-center gap-1.5">
                <TimeField value={c.start} onChange={(v) => update(c.id, { start: v })} />
                <span className="text-faint">→</span>
                <TimeField value={c.end} onChange={(v) => update(c.id, { end: v })} />
                {c.flagged && (
                  <span className="ml-1 flex items-center gap-1 text-[11px] text-st-overrun" title={c.flag_reason ?? ''}>
                    <AlertTriangle className="size-3" /> {c.flag_reason ?? 'Check'}
                  </span>
                )}
                <button
                  className="ml-auto rounded p-1 text-faint opacity-0 transition-opacity group-hover:opacity-100 hover:bg-st-overrun/10 hover:text-st-overrun"
                  onClick={(e) => {
                    e.stopPropagation()
                    remove(c.id)
                  }}
                  aria-label="Delete caption"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
              <textarea
                rows={Math.max(1, Math.ceil(c.text.length / 46))}
                className="w-full resize-none rounded-md border border-transparent bg-transparent px-1 py-0.5 text-sm leading-snug text-ink hover:border-line focus:border-accent focus:bg-canvas focus:outline-none"
                value={c.text}
                onChange={(e) => update(c.id, { text: e.target.value, flagged: false })}
              />
            </div>
          ))}
          <div className="flex gap-2 pt-1">
            <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={add}>
              Add at {fmtTime(p.videoTime, true)}
            </Button>
          </div>
        </div>
      )}

      {p.dirty && (
        <div className="sticky bottom-0 -mx-4 border-t border-line bg-panel/95 px-4 py-3 backdrop-blur">
          <Button variant="primary" busy={busy} onClick={wrap(p.onSave)} className="w-full">
            Save caption changes
          </Button>
        </div>
      )}
    </div>
  )
}
