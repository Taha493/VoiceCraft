import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { AlertTriangle, AudioLines, BookA, Cpu, Lock, Menu, Mic, Package, Plus, ScanText, Trash2, UploadCloud, X } from 'lucide-react'
import { api, type Health, type Job, type Options } from './api'
import { LexiconDialog } from './components/LexiconDialog'
import { UploadDialog } from './components/UploadDialog'
import { Button, ProgressBar } from './components/ui'
import { Workspace } from './components/Workspace'
import { fmtTime } from './lib/time'

function jobState(job: Job): { label: string; tone: string } {
  const st = job.stages
  if (Object.values(st).some((s) => s.status === 'running' || s.status === 'queued')) return { label: 'Working', tone: 'text-accent' }
  if (Object.values(st).some((s) => s.status === 'error')) return { label: 'Needs attention', tone: 'text-st-overrun' }
  if (st.render.status === 'done') return { label: 'Ready', tone: 'text-st-fits' }
  if (st.captions.status === 'done') return { label: 'Captions ready', tone: 'text-muted' }
  return { label: 'New', tone: 'text-faint' }
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [options, setOptions] = useState<Options | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [auto, setAuto] = useState<Set<string>>(new Set())
  const [upload, setUpload] = useState<{ name: string; progress: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lexicon, setLexicon] = useState(false)
  const [sidebar, setSidebar] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [pending, setPending] = useState<File | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const loadJobs = useCallback(() => api.jobs().then(setJobs, (e) => setError(String(e.message ?? e))), [])

  useEffect(() => {
    api.health().then(setHealth, () => setError('Cannot reach the VoiceCraft server. Start it with `voicecraft serve`.'))
    api.options().then(setOptions, () => undefined)
    void loadJobs()
    const id = setInterval(() => api.health().then(setHealth, () => undefined), 15000)
    return () => clearInterval(id)
  }, [loadJobs])

  const onFile = (file: File) => {
    setError(null)
    setPending(file)
  }

  const startUpload = async (file: File, opts: { hasCaptions: boolean; captionsFile: File | null }) => {
    setPending(null)
    setUpload({ name: file.name, progress: 0 })
    try {
      const job = await api.upload(file, opts, (p) => setUpload({ name: file.name, progress: p }))
      setAuto((s) => new Set(s).add(job.id))
      setJobs((j) => [job, ...j])
      setSelected(job.id)
      setSidebar(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUpload(null)
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files?.[0]
    if (f) onFile(f)
  }

  const onJobChange = useCallback((job: Job) => setJobs((js) => js.map((j) => (j.id === job.id ? job : j))), [])
  const onError = useCallback((m: string) => setError(m), [])

  const remove = async (id: string) => {
    if (!confirm('Delete this project and its generated files? Your original video file is not affected.')) return
    try {
      await api.deleteJob(id)
      setJobs((js) => js.filter((j) => j.id !== id))
      if (selected === id) setSelected(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const picker = (
    <input
      ref={fileInput}
      type="file"
      accept="video/*,.mp4,.mov,.webm,.mkv,.m4v"
      className="hidden"
      onChange={(e) => {
        const f = e.target.files?.[0]
        e.target.value = ''
        if (f) onFile(f)
      }}
    />
  )

  return (
    <div className="flex h-full flex-col" onDragOver={(e) => (e.preventDefault(), setDragging(true))} onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)} onDrop={onDrop}>
      {picker}
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-4">
        <button className="rounded-lg p-1.5 text-muted hover:bg-raised md:hidden" onClick={() => setSidebar((s) => !s)} aria-label="Projects">
          <Menu className="size-5" />
        </button>
        <div className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-lg bg-accent-strong">
            <AudioLines className="size-4 text-white" />
          </span>
          <span className="font-semibold tracking-tight">VoiceCraft</span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-muted">
          {health && !health.models_ready && (
            <span className="flex items-center gap-1.5 text-st-sped">
              <AlertTriangle className="size-3.5" /> Voice model missing. Run <code className="rounded bg-raised px-1">voicecraft setup</code>
            </span>
          )}
          {health && (
            <span className="hidden items-center gap-1.5 sm:flex" title="All processing happens on this computer">
              <Lock className="size-3.5 text-st-fits" /> Local · <Cpu className="size-3.5" /> {health.ram_available_gb.toFixed(1)} / {health.ram_total_gb.toFixed(1)} GB free
            </span>
          )}
          <Button size="sm" variant="ghost" icon={<BookA className="size-3.5" />} onClick={() => setLexicon(true)}>
            <span className="hidden sm:inline">Pronunciations</span>
          </Button>
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-2 border-b border-st-overrun/30 bg-st-overrun/10 px-4 py-2 text-sm text-st-overrun">
          <AlertTriangle className="size-4 shrink-0" />
          <span className="min-w-0 flex-1">{error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss">
            <X className="size-4" />
          </button>
        </div>
      )}

      <div className="relative flex min-h-0 flex-1">
        <aside
          className={`${sidebar ? 'flex' : 'hidden'} absolute inset-y-0 left-0 z-30 w-72 flex-col border-r border-line bg-canvas md:static md:flex md:w-64`}
        >
          <div className="p-3">
            <Button variant="primary" className="w-full" icon={<Plus className="size-4" />} onClick={() => fileInput.current?.click()} disabled={!!upload}>
              New video
            </Button>
            {upload && (
              <div className="mt-3 space-y-1.5">
                <p className="truncate text-xs text-muted">Uploading {upload.name}</p>
                <ProgressBar value={upload.progress} active />
              </div>
            )}
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-3">
            {jobs.map((j) => {
              const s = jobState(j)
              return (
                <div
                  key={j.id}
                  onClick={() => {
                    setSelected(j.id)
                    setSidebar(false)
                  }}
                  className={`group flex cursor-pointer items-center gap-2.5 rounded-lg p-2 transition-colors ${selected === j.id ? 'bg-raised' : 'hover:bg-panel'}`}
                >
                  <img src={api.frameUrl(j.id, Math.min(1, j.info.duration / 2))} alt="" className="h-9 w-14 shrink-0 rounded object-cover ring-1 ring-line" loading="lazy" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-ink">{j.name}</p>
                    <p className="text-[11px]">
                      <span className="tabular text-faint">{fmtTime(j.info.duration)}</span> · <span className={s.tone}>{s.label}</span>
                    </p>
                  </div>
                  <button
                    className="rounded p-1 text-faint opacity-0 group-hover:opacity-100 hover:text-st-overrun"
                    onClick={(e) => {
                      e.stopPropagation()
                      void remove(j.id)
                    }}
                    aria-label="Delete project"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              )
            })}
            {!jobs.length && <p className="px-2 py-4 text-xs text-faint">No projects yet.</p>}
          </div>
        </aside>

        <main className="min-w-0 flex-1">
          {selected ? (
            <Workspace
              key={selected}
              jobId={selected}
              options={options}
              autoContinue={auto.has(selected)}
              onAutoHandled={() =>
                setAuto((s) => {
                  const n = new Set(s)
                  n.delete(selected)
                  return n
                })
              }
              onJobChange={onJobChange}
              onError={onError}
              onOpenLexicon={() => setLexicon(true)}
            />
          ) : (
            <Welcome onPick={() => fileInput.current?.click()} uploading={!!upload} />
          )}
        </main>

        {dragging && (
          <div className="pointer-events-none absolute inset-3 z-40 flex items-center justify-center rounded-2xl border-2 border-dashed border-accent bg-accent/10 backdrop-blur-sm">
            <p className="text-lg font-medium text-ink">Drop your video to start</p>
          </div>
        )}
      </div>

      <LexiconDialog open={lexicon} onClose={() => setLexicon(false)} onError={onError} />
      {pending && <UploadDialog video={pending} onCancel={() => setPending(null)} onStart={(opts) => void startUpload(pending, opts)} />}
    </div>
  )
}

function Welcome({ onPick, uploading }: { onPick: () => void; uploading: boolean }) {
  const steps = [
    { icon: ScanText, title: 'Reads your captions', text: 'Finds the captions burned into the video and their timing. No subtitle file needed.' },
    { icon: Mic, title: 'Speaks them naturally', text: 'Generates a natural local voice, timed to start as each caption appears.' },
    { icon: Package, title: 'Exports a finished MP4', text: 'Your visuals stay exactly as they are, now with narration.' },
  ]
  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-6">
      <div className="w-full max-w-2xl space-y-8 text-center">
        <div className="space-y-3">
          <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">Give your silent video a voice.</h1>
          <p className="mx-auto max-w-lg text-muted">
            Drop in a captioned video, for example one made with Claude Code or Claude Design, and VoiceCraft adds a voice-over that follows the captions.
          </p>
        </div>
        <button
          onClick={onPick}
          disabled={uploading}
          className="group mx-auto flex w-full max-w-md flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-line-strong bg-panel px-6 py-10 transition-colors hover:border-accent hover:bg-accent-soft"
        >
          <UploadCloud className="size-9 text-accent transition-transform group-hover:-translate-y-0.5" />
          <span className="font-medium text-ink">Choose a video or drop it here</span>
          <span className="text-xs text-muted">MP4, MOV, WebM or MKV</span>
        </button>
        <div className="grid gap-3 text-left sm:grid-cols-3">
          {steps.map((s) => (
            <div key={s.title} className="rounded-xl border border-line bg-panel/60 p-4">
              <s.icon className="mb-2 size-5 text-accent" />
              <p className="text-sm font-medium text-ink">{s.title}</p>
              <p className="mt-1 text-xs leading-relaxed text-muted">{s.text}</p>
            </div>
          ))}
        </div>
        <p className="flex items-center justify-center gap-1.5 text-xs text-faint">
          <Lock className="size-3.5" /> Runs entirely on this computer. No uploads, accounts or API keys.
        </p>
      </div>
    </div>
  )
}
