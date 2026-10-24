import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, Mic, Package, Square, Type } from 'lucide-react'
import { api, type Caption, type CaptionTrack, type Job, type MusicLibrary, type MusicTrack, type Options, type Settings, type StageName, type Timeline } from '../api'
import { fmtTime, outputToVideo, videoToOutput } from '../lib/time'
import { CaptionsPanel } from './CaptionsPanel'
import { ExportPanel } from './ExportPanel'
import { Player, type Box, type PlayerHandle } from './Player'
import { TimelineView } from './TimelineView'
import { Button } from './ui'
import { VoicePanel } from './VoicePanel'

type Tab = 'captions' | 'voice' | 'export'

interface Props {
  jobId: string
  options: Options | null
  autoContinue: boolean
  onAutoHandled: () => void
  onJobChange: (job: Job) => void
  onError: (msg: string) => void
  onOpenLexicon: () => void
}

const active = (job: Job | null) => !!job && Object.values(job.stages).some((s) => s.status === 'running' || s.status === 'queued')

export function Workspace({ jobId, options, autoContinue, onAutoHandled, onJobChange, onError, onOpenLexicon }: Props) {
  const [job, setJob] = useState<Job | null>(null)
  const [track, setTrack] = useState<CaptionTrack | null>(null)
  const [draft, setDraft] = useState<Caption[]>([])
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [tab, setTab] = useState<Tab>('captions')
  const [showOutput, setShowOutput] = useState(false)
  const [time, setTime] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [editingRegion, setEditingRegion] = useState(false)
  const [regionBox, setRegionBox] = useState<Box | null>(null)
  const [musicLibrary, setMusicLibrary] = useState<MusicLibrary | null>(null)
  const [musicTrack, setMusicTrack] = useState<MusicTrack | null>(null)
  const player = useRef<PlayerHandle>(null)
  const prev = useRef<Job | null>(null)

  const fail = useCallback((e: unknown) => onError(e instanceof Error ? e.message : String(e)), [onError])

  const refresh = useCallback(async () => {
    try {
      const j = await api.job(jobId)
      setJob(j)
      onJobChange(j)
    } catch (e) {
      fail(e)
    }
  }, [jobId, onJobChange, fail])

  // Initial load + reset when switching jobs.
  useEffect(() => {
    setJob(null)
    setTrack(null)
    setDraft([])
    setTimeline(null)
    setShowOutput(false)
    setEditingRegion(false)
    setTime(0)
    prev.current = null
    void refresh()
  }, [jobId, refresh])

  // Poll while something is processing.
  useEffect(() => {
    if (!active(job)) return
    const id = setInterval(() => void refresh(), 800)
    return () => clearInterval(id)
  }, [job, refresh])

  const capKey = job?.stages.captions.finished ?? null
  const narrKey = job?.stages.narrate.finished ?? null
  const renderDone = job?.stages.render.status === 'done' || job?.stages.render.status === 'stale'

  useEffect(() => {
    if (!job || !['done', 'stale'].includes(job.stages.captions.status)) return
    api.captions(job.id).then((t) => {
      setTrack(t)
      setDraft(t.captions)
    }, () => setTrack(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, capKey])

  useEffect(() => {
    if (!job || !['done', 'stale'].includes(job.stages.narrate.status)) {
      setTimeline(null)
      return
    }
    api.timeline(job.id).then(setTimeline, () => setTimeline(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, narrKey])

  useEffect(() => {
    api.music().then(setMusicLibrary, () => setMusicLibrary(null))
  }, [])

  const renderKey = job?.stages.render.finished ?? null
  const musicSetting = job ? `${job.settings.music}` : ''
  useEffect(() => {
    if (!job) return
    api.jobMusic(job.id).then((r) => setMusicTrack(r.track), () => setMusicTrack(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, renderKey, musicSetting])

  const shuffleMusic = async () => {
    if (!job) return
    try {
      const r = await api.shuffleMusic(job.id)
      setMusicTrack(r.track)
      const fresh = await api.job(job.id)
      setJob(fresh)
      if (fresh.stages.narrate.status === 'done') await start(['render'], fresh)
    } catch (e) {
      fail(e)
    }
  }

  // Stage transitions: pick the right tab, auto-continue, show the result.
  useEffect(() => {
    if (!job) return
    const before = prev.current
    prev.current = job
    if (!before) {
      setTab(job.stages.render.status === 'done' ? 'export' : job.stages.captions.status === 'done' ? 'voice' : 'captions')
      setShowOutput(job.stages.render.status === 'done')
      if (autoContinue && job.stages.captions.status === 'pending' && job.settings.has_burned_captions) {
        void start(['captions'], job)
      } else if (autoContinue && job.stages.captions.status === 'done' && job.stages.narrate.status === 'pending') {
        // Captions came with the upload: go straight to the voice-over.
        onAutoHandled()
        setTab('voice')
        void start(['narrate', 'render'], job)
      }
      return
    }
    const justDone = (s: StageName) => before.stages[s].status !== 'done' && job.stages[s].status === 'done'
    if (justDone('captions') && autoContinue) {
      const res = job.stages.captions.result as { captions?: number; flagged?: number }
      onAutoHandled()
      if ((res.captions ?? 0) > 0 && (res.flagged ?? 0) === 0) {
        setTab('voice')
        void start(['narrate', 'render'], job)
      }
    }
    if (justDone('render')) {
      setTab('export')
      setShowOutput(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job])

  const start = async (stages: StageName[], j: Job | null = job) => {
    if (!j) return
    try {
      setJob(await api.run(j.id, stages))
    } catch (e) {
      fail(e)
    }
  }

  const dirty = useMemo(() => !!track && JSON.stringify(track.captions) !== JSON.stringify(draft), [track, draft])

  const onSettings = async (s: Partial<Settings>) => {
    if (!job) return
    try {
      setJob(await api.updateSettings(job.id, s))
    } catch (e) {
      fail(e)
    }
  }

  const saveCaptions = async () => {
    if (!job) return
    try {
      const t = await api.saveCaptions(job.id, draft)
      setTrack(t)
      setDraft(t.captions)
      await refresh()
    } catch (e) {
      fail(e)
    }
  }

  const toggleRegion = () => {
    if (editingRegion) {
      setEditingRegion(false)
      return
    }
    const r = track?.region
    const first = r?.boxes?.[0]
    setRegionBox(first ?? (r ? { x: r.x, y: r.y, w: r.w, h: r.h } : { x: 0, y: 0.72, w: 1, h: 0.22 }))
    setShowOutput(false)
    setEditingRegion(true)
  }

  const saveRegion = async () => {
    if (!job || !regionBox) return
    try {
      await api.setRegion(job.id, regionBox)
      setEditingRegion(false)
      await start(['captions'])
    } catch (e) {
      fail(e)
    }
  }

  if (!job) return <div className="flex h-full items-center justify-center text-sm text-muted">Loading…</div>

  const holds = timeline?.holds ?? []
  const outputAvailable = renderDone && showOutput
  const videoTime = outputAvailable ? outputToVideo(time, holds) : time
  const seekVideo = (v: number) => player.current?.seek(outputAvailable ? videoToOutput(v, holds) : v)
  const seekOutput = (t: number) => {
    if (!outputAvailable && renderDone) setShowOutput(true)
    setTimeout(() => player.current?.seek(renderDone ? t : outputToVideo(t, holds)), 50)
  }
  const captionsReady = job.stages.captions.status === 'done' && draft.length > 0 && !dirty
  const busy = active(job)

  const tabs: { id: Tab; label: string; icon: typeof Type; done: boolean }[] = [
    { id: 'captions', label: 'Captions', icon: Type, done: job.stages.captions.status === 'done' },
    { id: 'voice', label: 'Voice', icon: Mic, done: job.stages.narrate.status === 'done' },
    { id: 'export', label: 'Export', icon: Package, done: job.stages.render.status === 'done' },
  ]

  return (
    <div className="h-full overflow-y-auto lg:flex lg:min-h-0 lg:flex-row lg:overflow-hidden">
      <section className="flex min-w-0 flex-col gap-3 p-4 lg:flex-1 lg:overflow-y-auto">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-ink">{job.name}</h1>
            <p className="tabular text-xs text-muted">
              {job.info.width}×{job.info.height} · {fmtTime(job.info.duration, true)} · {job.info.fps.toFixed(0)} fps · {job.info.vcodec}
              {job.info.has_audio ? ' · has audio' : ' · silent'}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {renderDone && (
              <div className="flex rounded-lg border border-line bg-panel p-0.5 text-xs">
                {(['Original', 'Narrated'] as const).map((label, i) => (
                  <button
                    key={label}
                    onClick={() => {
                      setShowOutput(i === 1)
                      setEditingRegion(false)
                    }}
                    className={`rounded-md px-3 py-1 ${showOutput === (i === 1) ? 'bg-raised text-ink' : 'text-muted hover:text-ink'}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
            {busy && (
              <Button size="sm" variant="danger" icon={<Square className="size-3" />} onClick={() => api.cancel(job.id).then(refresh, fail)}>
                Stop
              </Button>
            )}
          </div>
        </div>

        <Player
          ref={player}
          src={outputAvailable ? api.outputUrl(job.id, job.stages.render.finished) : api.videoUrl(job.id)}
          aspect={job.info.width / job.info.height}
          region={editingRegion ? regionBox : null}
          guides={editingRegion ? (track?.region?.boxes ?? []) : []}
          editingRegion={editingRegion}
          onRegionChange={setRegionBox}
          onTime={setTime}
        />

        <TimelineView
          duration={job.info.duration}
          captions={draft}
          timeline={timeline}
          videoTime={videoTime}
          selectedCaption={selected}
          onSeek={seekVideo}
          onSelectCaption={(id) => {
            setSelected(id)
            setTab('captions')
          }}
        />
      </section>

      <aside className="w-full shrink-0 border-t border-line bg-canvas lg:flex lg:min-h-0 lg:w-[420px] lg:flex-col lg:border-t-0 lg:border-l">
        <nav className="sticky top-0 z-10 flex border-b border-line bg-canvas px-2">
          {tabs.map((t, i) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`relative flex flex-1 items-center justify-center gap-2 py-3 text-sm transition-colors ${tab === t.id ? 'text-ink' : 'text-muted hover:text-ink'}`}
            >
              <span className={`flex size-5 items-center justify-center rounded-full text-[10px] ${t.done ? 'bg-st-fits/20 text-st-fits' : 'bg-raised text-muted'}`}>
                {t.done ? <Check className="size-3" /> : i + 1}
              </span>
              {t.label}
              {tab === t.id && <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent" />}
            </button>
          ))}
        </nav>
        <div className="p-4 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          {tab === 'captions' && (
            <CaptionsPanel
              job={job}
              track={track}
              draft={draft}
              dirty={dirty}
              selected={selected}
              videoTime={videoTime}
              editingRegion={editingRegion}
              onDraft={setDraft}
              onSave={saveCaptions}
              onDetect={() => void start(['captions'])}
              onImportFile={async (f) => {
                try {
                  const t = await api.importCaptions(job.id, f)
                  setTrack(t)
                  setDraft(t.captions)
                  await refresh()
                } catch (e) {
                  fail(e)
                }
              }}
              onScript={async (text) => {
                try {
                  const t = await api.importScript(job.id, text)
                  setTrack(t)
                  setDraft(t.captions)
                  await refresh()
                } catch (e) {
                  fail(e)
                }
              }}
              onToggleRegion={toggleRegion}
              onBurnedChange={(v) => {
                setEditingRegion(false)
                void onSettings({ has_burned_captions: v })
              }}
              onSaveRegion={saveRegion}
              onSelect={setSelected}
              onSeek={seekVideo}
            />
          )}
          {tab === 'voice' && (
            <VoicePanel
              job={job}
              options={options}
              timeline={timeline}
              captionsReady={captionsReady}
              onSettings={onSettings}
              onGenerate={() => void start(job.stages.narrate.status === 'done' ? ['render'] : ['narrate', 'render'])}
              onOpenLexicon={onOpenLexicon}
              onSeekOutput={seekOutput}
              musicLibrary={musicLibrary}
              musicTrack={musicTrack}
              onShuffleMusic={() => void shuffleMusic()}
            />
          )}
          {tab === 'export' && <ExportPanel job={job} timeline={timeline} showingOutput={showOutput} onShowOutput={setShowOutput} />}
        </div>
      </aside>
    </div>
  )
}
