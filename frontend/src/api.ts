export type StageName = 'captions' | 'narrate' | 'render'
export type StageStatus = 'pending' | 'queued' | 'running' | 'done' | 'error' | 'stale'

export interface StageState {
  status: StageStatus
  progress: number
  message: string
  error: string | null
  started: number | null
  finished: number | null
  result: Record<string, unknown>
}

export interface Settings {
  has_burned_captions: boolean
  engine: string
  voice: string
  preset: string
  allow_holds: boolean
  audio_mode: 'duck' | 'replace' | 'mix'
  sample_fps: number
  ocr: string
  music: string
  music_level: 'low' | 'medium' | 'high'
}

export interface VideoInfo {
  duration: number
  width: number
  height: number
  fps: number
  vcodec: string
  has_audio: boolean
  acodec: string | null
}

export interface Job {
  id: string
  name: string
  created: number
  video_file: string
  info: VideoInfo
  settings: Settings
  stages: Record<StageName, StageState>
}

export interface Region {
  x: number
  y: number
  w: number
  h: number
  auto: boolean
  confidence: number
  ignore_texts: string[]
  boxes: { x: number; y: number; w: number; h: number }[]
}

export interface Caption {
  id: string
  start: number
  end: number
  text: string
  confidence: number
  flagged: boolean
  flag_reason: string | null
  source: 'ocr' | 'import' | 'edit' | 'script'
}

export interface CaptionTrack {
  duration: number
  region: Region | null
  sample_fps: number
  ocr_engine: string
  captions: Caption[]
  stats: Record<string, number>
}

export type SegmentStatus = 'fits' | 'borrowed' | 'sped_up' | 'held' | 'overrun'

export interface Segment {
  id: string
  caption_ids: string[]
  text: string
  spoken_text: string
  preset: string
  caption_start: number
  caption_end: number
  start: number
  end: number
  speed: number
  audio_file: string
  audio_duration: number
  status: SegmentStatus
  hold: number
  note: string | null
}

export interface Hold {
  video_time: number
  duration: number
  segment_id: string
}

export interface Timeline {
  engine: string
  voice: string
  preset: string
  video_duration: number
  output_duration: number
  segments: Segment[]
  holds: Hold[]
  stats: Record<string, number>
}

export interface Voice {
  id: string
  name: string
  language: string
  gender: string
  license: string
  engine: string
}

export interface Options {
  engines: { id: string; label: string; license: string; ready: boolean; voices: Voice[] }[]
  presets: { id: string; label: string; description: string; speed: number }[]
  audio_modes: { id: Settings['audio_mode']; label: string }[]
  ocr_engines: string[]
}

export interface MusicTrack {
  id: string
  title: string
  artist: string
  moods: string[]
  mood_labels: string[]
  source: 'library' | 'user'
  license: string
  credit: string
  duration: number
}

export interface MusicLibrary {
  tracks: MusicTrack[]
  library_size: number
  levels: string[]
  preset_moods: Record<string, string[]>
  user_folder: string
}

export interface Health {
  ok: boolean
  models_ready: boolean
  piper_ready: boolean
  ocr_engines: string[]
  ram_available_gb: number
  ram_total_gb: number
  busy_job: string | null
  music_tracks: number
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) {
    let message = res.statusText
    try {
      const body = await res.json()
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => request<Health>('/health'),
  options: () => request<Options>('/options'),
  jobs: () => request<Job[]>('/jobs'),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  deleteJob: (id: string) => request<{ deleted: string }>(`/jobs/${id}`, { method: 'DELETE' }),
  updateSettings: (id: string, changes: Partial<Settings>) => request<Job>(`/jobs/${id}/settings`, json('PATCH', changes)),
  run: (id: string, stages: StageName[]) => request<Job>(`/jobs/${id}/run`, json('POST', { stages })),
  cancel: (id: string) => request<unknown>(`/jobs/${id}/cancel`, { method: 'POST' }),
  captions: (id: string) => request<CaptionTrack>(`/jobs/${id}/captions`),
  saveCaptions: (id: string, captions: Caption[]) => request<CaptionTrack>(`/jobs/${id}/captions`, json('PUT', { captions })),
  importScript: (id: string, script: string) => request<CaptionTrack>(`/jobs/${id}/captions/script`, json('POST', { script })),
  setRegion: (id: string, r: { x: number; y: number; w: number; h: number }) => request<Region>(`/jobs/${id}/region`, json('PUT', r)),
  timeline: (id: string) => request<Timeline>(`/jobs/${id}/timeline`),
  music: () => request<MusicLibrary>('/music'),
  jobMusic: (id: string) => request<{ track: MusicTrack | null }>(`/jobs/${id}/music`),
  shuffleMusic: (id: string) => request<{ track: MusicTrack }>(`/jobs/${id}/music/shuffle`, { method: 'POST' }),
  musicUrl: (trackId: string) => `/api/music/${encodeURIComponent(trackId)}/audio`,
  lexicon: () => request<{ user: Record<string, string>; defaults: Record<string, string> }>('/lexicon'),
  saveLexicon: (entries: Record<string, string>) => request<{ user: Record<string, string> }>('/lexicon', json('PUT', entries)),

  upload(file: File, opts: { hasCaptions: boolean; captionsFile: File | null }, onProgress: (frac: number) => void): Promise<Job> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      const form = new FormData()
      form.append('file', file)
      form.append('has_captions', String(opts.hasCaptions))
      if (opts.captionsFile) form.append('captions', opts.captionsFile)
      xhr.open('POST', '/api/jobs')
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
      xhr.onload = () => {
        let body: { detail?: string } & Partial<Job> = {}
        try {
          body = JSON.parse(xhr.responseText)
        } catch {
          /* non-JSON error */
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as Job)
        else reject(new ApiError(xhr.status, body.detail ?? xhr.statusText))
      }
      xhr.onerror = () => reject(new ApiError(0, 'Upload failed. Is the VoiceCraft server running?'))
      xhr.send(form)
    })
  },

  async importCaptions(id: string, file: File): Promise<CaptionTrack> {
    const form = new FormData()
    form.append('file', file)
    return request<CaptionTrack>(`/jobs/${id}/captions/import`, { method: 'POST', body: form })
  },

  videoUrl: (id: string) => `/api/jobs/${id}/video`,
  outputUrl: (id: string, version: number | null) => `/api/jobs/${id}/output${version ? `?v=${version}` : ''}`,
  downloadUrl: (id: string) => `/api/jobs/${id}/output?download=true`,
  frameUrl: (id: string, t: number) => `/api/jobs/${id}/frame?t=${t.toFixed(2)}`,
  clipUrl: (id: string, name: string) => `/api/jobs/${id}/clips/${name}`,
}
