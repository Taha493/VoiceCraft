import { Music, Pause, Play, Shuffle } from 'lucide-react'
import type { Job, MusicLibrary, MusicTrack, Settings } from '../api'
import { fmtTime } from '../lib/time'
import { Button, Notice } from './ui'

interface Props {
  job: Job
  library: MusicLibrary | null
  current: MusicTrack | null
  disabled: boolean
  playing: string | null
  onSettings: (s: Partial<Settings>) => void
  onShuffle: () => void
  onPreview: (track: MusicTrack) => void
}

const LEVELS: { id: Settings['music_level']; label: string }[] = [
  { id: 'low', label: 'Low' },
  { id: 'medium', label: 'Medium' },
  { id: 'high', label: 'High' },
]

export function MusicSection({ job, library, current, disabled, playing, onSettings, onShuffle, onPreview }: Props) {
  const s = job.settings
  const tracks = library?.tracks ?? []
  const libraryTracks = tracks.filter((t) => t.source === 'library')
  const userTracks = tracks.filter((t) => t.source === 'user')
  const moods = library?.preset_moods[s.preset] ?? []

  if (library && !tracks.length) {
    return (
      <section className="space-y-2">
        <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Background music</h3>
        <Notice>
          No music installed. Run <code>voicecraft setup</code> to download the music library, or add your own tracks to <code>{library.user_folder}</code>.
        </Notice>
      </section>
    )
  }

  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Background music</h3>
      <select
        className="h-9 w-full rounded-lg border border-line-strong bg-raised px-2 text-sm text-ink focus:border-accent focus:outline-none"
        value={s.music}
        disabled={disabled}
        onChange={(e) => onSettings({ music: e.target.value })}
      >
        <option value="auto">Automatic (new track each video)</option>
        <option value="none">No music</option>
        {libraryTracks.length > 0 && (
          <optgroup label="Library">
            {libraryTracks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title} · {t.mood_labels.join(', ')}
              </option>
            ))}
          </optgroup>
        )}
        {userTracks.length > 0 && (
          <optgroup label="Your tracks">
            {userTracks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </optgroup>
        )}
      </select>

      {s.music !== 'none' && (
        <>
          <div className="flex items-center gap-2 rounded-lg border border-line bg-panel p-2.5">
            <Music className="size-4 shrink-0 text-accent" />
            <div className="min-w-0 flex-1">
              {current ? (
                <>
                  <p className="truncate text-sm text-ink">{current.title}</p>
                  <p className="text-[11px] text-muted">
                    {current.mood_labels.join(', ')} · {fmtTime(current.duration)}
                    {current.artist && ` · ${current.artist}`}
                  </p>
                </>
              ) : (
                <p className="text-xs text-muted">
                  {s.music === 'auto' ? `Picked when the video renders${moods.length ? ` (${moods.join(' / ')} mood)` : ''}.` : 'Selected track'}
                </p>
              )}
            </div>
            {current && (
              <button
                className="flex size-7 shrink-0 items-center justify-center rounded-full bg-raised text-ink hover:bg-accent-strong"
                onClick={() => onPreview(current)}
                aria-label={playing === current.id ? 'Stop preview' : 'Preview track'}
              >
                {playing === current.id ? <Pause className="size-3.5" /> : <Play className="ml-0.5 size-3.5" />}
              </button>
            )}
            {s.music === 'auto' && (
              <Button size="sm" variant="ghost" icon={<Shuffle className="size-3.5" />} onClick={onShuffle} disabled={disabled} title="Pick a different track">
                Shuffle
              </Button>
            )}
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs text-muted">Level</span>
            <div className="flex rounded-lg border border-line bg-panel p-0.5 text-xs">
              {LEVELS.map((l) => (
                <button
                  key={l.id}
                  disabled={disabled}
                  onClick={() => onSettings({ music_level: l.id })}
                  className={`rounded-md px-3 py-1 ${s.music_level === l.id ? 'bg-raised text-ink' : 'text-muted hover:text-ink'}`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>
          <p className="text-[11px] leading-relaxed text-faint">
            Music sits well below the voice and dips further while it speaks. Library tracks are CC BY 4.0; the credit line is included with your export.
          </p>
        </>
      )}
    </section>
  )
}
