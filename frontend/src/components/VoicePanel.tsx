import { useRef, useState } from 'react'
import { BookA, Pause, Play, Wand2 } from 'lucide-react'
import type { Job, MusicLibrary, MusicTrack, Options, Settings, Timeline } from '../api'
import { api } from '../api'
import { fmtTime } from '../lib/time'
import { MusicSection } from './MusicSection'
import { Button, Notice, StageProgress, StatusChip, Toggle } from './ui'

interface Props {
  job: Job
  options: Options | null
  timeline: Timeline | null
  captionsReady: boolean
  onSettings: (s: Partial<Settings>) => Promise<void>
  onGenerate: () => void
  onOpenLexicon: () => void
  onSeekOutput: (t: number) => void
  musicLibrary: MusicLibrary | null
  musicTrack: MusicTrack | null
  onShuffleMusic: () => void
}

export function VoicePanel({ job, options, timeline, captionsReady, onSettings, onGenerate, onOpenLexicon, onSeekOutput, musicLibrary, musicTrack, onShuffleMusic }: Props) {
  const s = job.settings
  const narrate = job.stages.narrate
  const render = job.stages.render
  const running = [narrate, render].some((st) => st.status === 'running' || st.status === 'queued')
  const engine = options?.engines.find((e) => e.id === s.engine)
  const audio = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState<string | null>(null)

  const play = (key: string, url: string) => {
    const a = audio.current!
    if (playing === key) {
      a.pause()
      setPlaying(null)
      return
    }
    a.src = url
    void a.play()
    setPlaying(key)
  }
  const playClip = (file: string) => play(file, api.clipUrl(job.id, file))

  const needsRun = narrate.status !== 'done' || render.status !== 'done'
  const label = narrate.status === 'done' && render.status !== 'done' ? 'Render video' : timeline ? 'Regenerate voice-over' : 'Generate voice-over'

  return (
    <div className="space-y-4">
      <audio ref={audio} onEnded={() => setPlaying(null)} className="hidden" />

      <section className="space-y-2">
        <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Engine</h3>
        <div className="grid grid-cols-2 gap-2">
          {options?.engines.map((e) => (
            <button
              key={e.id}
              disabled={!e.ready || running}
              onClick={() => onSettings({ engine: e.id })}
              className={`rounded-lg border p-2.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${s.engine === e.id ? 'border-accent bg-accent-soft' : 'border-line bg-panel hover:border-line-strong'}`}
            >
              <span className="block text-sm font-medium text-ink">{e.label}</span>
              <span className="block text-[11px] text-muted">{e.ready ? e.license : 'Not installed'}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Voice</h3>
        <select
          className="h-9 w-full rounded-lg border border-line-strong bg-raised px-2 text-sm text-ink focus:border-accent focus:outline-none"
          value={s.voice}
          disabled={running}
          onChange={(e) => onSettings({ voice: e.target.value })}
        >
          {engine?.voices.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name} · {v.language === 'en-gb' ? 'British' : 'American'} · {v.gender}
            </option>
          ))}
        </select>
        <p className="text-[11px] text-faint">Voice license: {engine?.voices.find((v) => v.id === s.voice)?.license ?? '—'}</p>
      </section>

      <section className="space-y-2">
        <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Delivery</h3>
        <div className="grid grid-cols-2 gap-2">
          {options?.presets.map((p) => (
            <button
              key={p.id}
              disabled={running}
              onClick={() => onSettings({ preset: p.id })}
              className={`rounded-lg border p-2.5 text-left transition-colors ${s.preset === p.id ? 'border-accent bg-accent-soft' : 'border-line bg-panel hover:border-line-strong'}`}
            >
              <span className="block text-sm font-medium text-ink">{p.label}</span>
              <span className="block text-[11px] leading-snug text-muted">{p.description}</span>
            </button>
          ))}
        </div>
        <p className="text-[11px] leading-relaxed text-faint">
          Local voices have no emotion controls. Delivery sets the pace, the pauses, and when the voice comes in after each caption.
        </p>
      </section>

      <section className="space-y-3">
        <Toggle
          checked={s.allow_holds}
          onChange={(v) => onSettings({ allow_holds: v })}
          label="Hold the frame when a line needs more time"
          hint="If speeding up slightly is not enough, the video pauses on that caption instead of cutting words."
        />
        {job.info.has_audio && (
          <div className="space-y-1.5">
            <span className="text-sm text-ink">Original audio</span>
            <select
              className="h-9 w-full rounded-lg border border-line-strong bg-raised px-2 text-sm text-ink focus:border-accent focus:outline-none"
              value={s.audio_mode}
              disabled={running}
              onChange={(e) => onSettings({ audio_mode: e.target.value as Settings['audio_mode'] })}
            >
              {options?.audio_modes.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </section>

      <MusicSection
        job={job}
        library={musicLibrary}
        current={musicTrack}
        disabled={running}
        playing={playing}
        onSettings={(v) => void onSettings(v)}
        onShuffle={onShuffleMusic}
        onPreview={(t) => play(t.id, api.musicUrl(t.id))}
      />

      <section>
        <Button size="sm" variant="ghost" icon={<BookA className="size-3.5" />} onClick={onOpenLexicon}>
          Pronunciations
        </Button>
      </section>

      <StageProgress stage={narrate} label="Generating narration" />
      <StageProgress stage={render} label="Rendering" />
      {narrate.status === 'error' && <Notice tone="error">Narration failed: {narrate.error}</Notice>}
      {render.status === 'error' && <Notice tone="error">Rendering failed: {render.error}</Notice>}

      <Button
        variant="primary"
        icon={<Wand2 className="size-4" />}
        className="w-full"
        disabled={!captionsReady || running || !needsRun}
        onClick={onGenerate}
        title={!captionsReady ? 'Detect or import captions first' : undefined}
      >
        {needsRun ? label : 'Up to date'}
      </Button>

      {timeline && (
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Segments</h3>
            <span className="text-[11px] text-faint">
              {timeline.stats.generated ?? 0} generated · {timeline.stats.reused ?? 0} from cache
            </span>
          </div>
          {timeline.segments.map((seg) => (
            <div key={seg.id} className="rounded-lg border border-line bg-panel p-2.5">
              <div className="mb-1 flex items-center gap-2">
                <button
                  className="flex size-7 shrink-0 items-center justify-center rounded-full bg-raised text-ink hover:bg-accent-strong"
                  onClick={() => playClip(seg.audio_file)}
                  aria-label={playing === seg.audio_file ? 'Pause' : 'Play segment'}
                >
                  {playing === seg.audio_file ? <Pause className="size-3.5" /> : <Play className="ml-0.5 size-3.5" />}
                </button>
                <button className="tabular text-xs text-muted hover:text-ink" onClick={() => onSeekOutput(seg.start)}>
                  {fmtTime(seg.start, true)} · {seg.audio_duration.toFixed(1)}s{seg.speed !== 1 ? ` · ${seg.speed.toFixed(2)}×` : ''}
                </button>
                <span className="ml-auto">
                  <StatusChip status={seg.status} />
                </span>
              </div>
              <p className="text-sm leading-snug text-ink">{seg.text}</p>
              {seg.spoken_text.replace(/[.!?]$/, '') !== seg.text.replace(/[.!?]$/, '') && (
                <p className="mt-1 text-[11px] text-faint">Spoken as: {seg.spoken_text}</p>
              )}
              {seg.note && <p className="mt-1 text-[11px] text-muted">{seg.note}</p>}
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
