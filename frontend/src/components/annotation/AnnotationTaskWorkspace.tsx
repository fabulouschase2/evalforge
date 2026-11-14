// Multimodal annotation workspaces (image / video / audio) with a shared shell.
// Coordinates are normalized 0..1 so they stay accurate at any display size.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MousePointer2, Square, Lasso, Circle, Undo2, Redo2, Save, Send, Plus, Trash2, Play, Pause } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, NativeSelect } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/states";

type ShapeType = "bbox" | "polygon" | "point";
interface Shape { type: ShapeType; label: string; points: [number, number][] }
interface VEvent { label: string; start_ms: number; end_ms: number; frames: { time_ms: number; shapes: Shape[] }[] }
interface Segment { start_ms: number; end_ms: number; transcript: string; speaker: string | null; language: string | null; emotion: string | null }

interface AnnResponse {
  media: {
    id: number; filename: string; media_type: "image" | "video" | "audio";
    mime_type: string; width: number | null; height: number | null;
    duration_ms: number | null; annotation_config: { labels?: string[] };
  };
  annotation: {
    id: number; version: number; is_final: boolean;
    shapes?: Shape[]; labels?: string[];
    events?: VEvent[]; frame_labels?: unknown[]; duration_ms?: number | null;
    segments?: Segment[]; global_labels?: string[];
  } | null;
  task_status: string;
}

export default function AnnotationTaskWorkspace({ taskId }: { taskId: number }) {
  const toast = useToast();
  const qc = useQueryClient();
  const ann = useQuery({
    queryKey: ["annotation", taskId],
    queryFn: () => api.get<AnnResponse>(`/annotation-tasks/${taskId}/annotation`),
  });

  // <img>/<video>/<audio> cannot send the Authorization header — fetch the
  // media as an authenticated blob and serve it via a short-lived object URL.
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    if (ann.data?.media.id) {
      api.getRawBlob(`/media/${ann.data.media.id}/stream`).then(({ blob }) => {
        url = URL.createObjectURL(blob);
        setObjectUrl(url);
      }).catch(() => setObjectUrl(null));
    }
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [ann.data?.media.id]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.put<{ version: number }>(`/annotation-tasks/${taskId}/annotation`, body),
    onSuccess: (data: { version: number }) => {
      qc.invalidateQueries({ queryKey: ["annotation", taskId] });
      toast("success", `Saved (version ${data.version})`);
    },
    onError: (e) => toast("error", "Save failed", (e as Error).message),
  });

  const submit = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/annotation-tasks/${taskId}/submit`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["annotation", taskId] });
      qc.invalidateQueries({ queryKey: ["task-workspace", taskId] });
      toast("success", "Annotation submitted", "It is now awaiting review.");
    },
    onError: (e) => toast("error", "Submit failed", (e as Error).message),
  });

  if (ann.isLoading) return <div className="py-16 text-center text-sm text-fg-muted">Loading media…</div>;
  if (ann.isError) return <ErrorState message={(ann.error as Error)?.message} retry={ann.refetch} />;
  const data = ann.data!;
  const media = data.media;
  const streamUrl = objectUrl ?? "";

  if (media.media_type === "image") {
    return (
      <ImageWorkspace
        taskId={taskId} streamUrl={streamUrl} media={media} data={data}
        onSave={(b) => save.mutate(b)} onFinal={(b) => submit.mutate(b)}
        saving={save.isPending} submitting={submit.isPending}
      />
    );
  }
  if (media.media_type === "video") {
    return (
      <VideoWorkspace
        taskId={taskId} streamUrl={streamUrl} media={media} data={data}
        onSave={(b) => save.mutate(b)} onFinal={(b) => submit.mutate(b)}
        saving={save.isPending} submitting={submit.isPending}
      />
    );
  }
  return (
    <AudioWorkspace
      taskId={taskId} streamUrl={streamUrl} media={media} data={data}
      onSave={(b) => save.mutate(b)} onFinal={(b) => submit.mutate(b)}
      saving={save.isPending} submitting={submit.isPending}
    />
  );
}

interface WorkspaceProps {
  taskId: number;
  streamUrl: string;
  media: AnnResponse["media"];
  data: AnnResponse;
  onSave: (body: Record<string, unknown>) => void;
  onFinal: (body: Record<string, unknown>) => void;
  saving: boolean;
  submitting: boolean;
}

const fmtMs = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}.${String(Math.floor((ms % 1000) / 10)).padStart(2, "0")}`;

// ---------------------------------------------------------------------------
// Image workspace: zoom/pan + bbox/polygon/point + undo/redo + label palette
// ---------------------------------------------------------------------------

function ImageWorkspace({ streamUrl, media, data, onSave, onFinal, saving, submitting }: WorkspaceProps) {
  const labels = media.annotation_config?.labels ?? ["object"];
  const [shapes, setShapes] = useState<Shape[]>(data.annotation?.shapes ?? []);
  const [undoStack, setUndo] = useState<Shape[][]>([]);
  const [redoStack, setRedo] = useState<Shape[][]>([]);
  const [tool, setTool] = useState<ShapeType>("bbox");
  const [activeLabel, setActiveLabel] = useState(labels[0]);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const draft = useRef<[number, number][]>([]);
  const boxRef = useRef<HTMLDivElement>(null);
  const [draftTick, setDraftTick] = useState(0);

  const pushHistory = useCallback((prev: Shape[]) => {
    setUndo((u) => [...u.slice(-49), prev]);
    setRedo([]);
  }, []);

  const toNorm = (e: React.MouseEvent): [number, number] => {
    const rect = boxRef.current!.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, ((e.clientX - rect.left) / rect.width)));
    const y = Math.min(1, Math.max(0, ((e.clientY - rect.top) / rect.height)));
    return [Number(x.toFixed(4)), Number(y.toFixed(4))];
  };

  const onCanvasClick = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const p = toNorm(e);
    if (tool === "point") {
      pushHistory(shapes);
      setShapes((s) => [...s, { type: "point", label: activeLabel, points: [p] }]);
      return;
    }
    draft.current = [...draft.current, p];
    setDraftTick((t) => t + 1);
    if (tool === "bbox" && draft.current.length === 2) {
      // capture synchronously — the updater must not read mutable refs later
      const a = draft.current[0];
      const b = draft.current[1];
      pushHistory(shapes);
      setShapes((s) => [...s, { type: "bbox", label: activeLabel, points: [a, b] }]);
      draft.current = [];
    }
    if (tool === "polygon" && draft.current.length >= 3) {
      const [x0, y0] = draft.current[0];
      if (Math.hypot(p[0] - x0, p[1] - y0) < 0.01) {
        const pts = draft.current.slice(0, -1) as [number, number][];
        pushHistory(shapes);
        setShapes((s) => [...s, { type: "polygon", label: activeLabel, points: pts }]);
        draft.current = [];
      }
    }
  };

  const undo = () => {
    setUndo((u) => {
      if (!u.length) return u;
      setRedo((r) => [...r, shapes]);
      setShapes(u[u.length - 1]);
      return u.slice(0, -1);
    });
  };
  const redo = () => {
    setRedo((r) => {
      if (!r.length) return r;
      setUndo((u) => [...u, shapes]);
      setShapes(r[r.length - 1]);
      return r.slice(0, -1);
    });
  };

  const svgShapes = [...shapes, ...(draft.current.length ? [{
    type: tool, label: activeLabel, points: [...draft.current] as [number, number][],
  } as Shape] : [])];

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <Card>
        <CardHeader className="gap-2">
          <CardTitle className="flex flex-wrap items-center gap-2">
            <span className="truncate">{media.filename}</span>
            <Badge variant="info">{media.width}×{media.height}</Badge>
            {data.annotation?.is_final && <Badge variant="success">submitted</Badge>}
          </CardTitle>
          <div className="flex flex-wrap items-center gap-1.5">
            {([["select", MousePointer2], ["bbox", Square], ["polygon", Lasso], ["point", Circle]] as const).map(([t, Icon]) => (
              <Button key={t} variant={tool === t ? "default" : "secondary"} size="sm"
                onClick={() => { setTool(t as ShapeType); draft.current = []; }}>
                <Icon className="h-3.5 w-3.5" /> {t}
              </Button>
            ))}
            <span className="mx-1 h-5 w-px bg-line" />
            <Button variant="secondary" size="sm" onClick={undo} disabled={!undoStack.length}><Undo2 className="h-3.5 w-3.5" /> Undo</Button>
            <Button variant="secondary" size="sm" onClick={redo} disabled={!redoStack.length}><Redo2 className="h-3.5 w-3.5" /> Redo</Button>
            <span className="mx-1 h-5 w-px bg-line" />
            <Button variant="secondary" size="sm" onClick={() => setZoom((z) => Math.min(4, z + 0.25))}>+</Button>
            <Button variant="secondary" size="sm" onClick={() => setZoom((z) => Math.max(1, z - 0.25))}>−</Button>
            <Button variant="secondary" size="sm" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>Reset</Button>
          </div>
        </CardHeader>
        <CardContent>
          <div
            ref={boxRef}
            className="relative mx-auto w-full cursor-crosshair select-none overflow-hidden rounded-md border border-line bg-[repeating-conic-gradient(#1a2430_0%_25%,#141c26_0%_50%)] bg-[length:20px_20px]"
            style={{ aspectRatio: `${media.width || 4} / ${media.height || 3}` }}
            onClick={onCanvasClick}
            onMouseMove={(e) => { if (tool === "polygon" && draft.current.length) setDraftTick((t) => t + 1); }}
          >
            <div style={{ transform: `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)`, transformOrigin: "center", width: "100%", height: "100%" }}>
              <img src={streamUrl} alt={media.filename} className="h-full w-full object-contain" draggable={false} />
              <svg viewBox="0 0 1 1" className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
                {svgShapes.map((s, i) => (
                  s.type === "bbox" && s.points.length === 2 ? (
                    <rect key={i}
                      x={Math.min(s.points[0][0], s.points[1][0])} y={Math.min(s.points[0][1], s.points[1][1])}
                      width={Math.abs(s.points[1][0] - s.points[0][0])} height={Math.abs(s.points[1][1] - s.points[0][1])}
                      fill="rgba(22,184,166,0.15)" stroke="#16B8A6" strokeWidth={0.004} vectorEffect="non-scaling-stroke" />
                  ) : s.type === "polygon" && s.points.length >= 3 ? (
                    <polygon key={i} points={s.points.map((p) => `${p[0]},${p[1]}`).join(" ")}
                      fill="rgba(22,184,166,0.15)" stroke="#16B8A6" strokeWidth={0.004} vectorEffect="non-scaling-stroke" />
                  ) : s.type === "point" && s.points.length === 1 ? (
                    <circle key={i} cx={s.points[0][0]} cy={s.points[0][1]} r={0.008} fill="#f59e0b" stroke="#fff" strokeWidth={0.002} />
                  ) : null
                ))}
              </svg>
            </div>
            <span className="pointer-events-none absolute right-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">
              {tool === "polygon" && draft.current.length >= 1 ? `polygon: ${draft.current.length} pts — click near start to close` : `tool: ${tool}`}
              <span hidden>{draftTick}</span>
            </span>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardHeader><CardTitle className="text-sm">Label</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-1.5">
            {labels.map((l) => (
              <button key={l} onClick={() => setActiveLabel(l)}
                className={`rounded-full border px-2.5 py-1 text-xs ${activeLabel === l ? "border-teal-500 bg-teal-500/15 text-teal" : "border-line text-fg-muted hover:text-fg"}`}>
                {l}
              </button>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-sm">Shapes ({shapes.length})</CardTitle></CardHeader>
          <CardContent className="max-h-52 space-y-1 overflow-y-auto">
            {shapes.length === 0 ? (
              <p className="text-xs text-fg-muted">Draw with the tools above — click two corners for a box, then close polygons.</p>
            ) : shapes.map((s, i) => (
              <div key={i} className="flex items-center gap-2 rounded border border-line px-2 py-1 text-xs">
                <Badge variant="info">{s.type}</Badge>
                <span className="text-fg">{s.label}</span>
                <button className="ml-auto text-danger hover:text-danger" aria-label={`Delete shape ${i + 1}`}
                  onClick={() => { pushHistory(shapes); setShapes((x) => x.filter((_, j) => j !== i)); }}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </CardContent>
        </Card>

        <div className="flex gap-2">
          <Button variant="secondary" className="flex-1" onClick={() => onSave({ shapes, labels: labels.filter((l) => shapes.some((s) => s.label === l)) })}
            disabled={saving || data.annotation?.is_final}>
            <Save className="h-4 w-4" /> {saving ? "Saving…" : "Save draft"}
          </Button>
          <Button className="flex-1" onClick={() => onFinal({ time_spent_seconds: undefined })}
            disabled={submitting || !shapes.length || data.annotation?.is_final}>
            <Send className="h-4 w-4" /> {submitting ? "…" : "Submit"}
          </Button>
        </div>
        <p className="text-xs text-fg-muted">
          Save a draft before submitting. Coordinates are stored normalized and export correctly at any size.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Video workspace: player + timeline + event spans + per-frame boxes
// ---------------------------------------------------------------------------

function VideoWorkspace({ streamUrl, media, data, onSave, onFinal, saving, submitting }: WorkspaceProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const labels = media.annotation_config?.labels ?? ["event"];
  const durationMs = data.annotation?.duration_ms ?? media.duration_ms ?? 0;
  const [events, setEvents] = useState<VEvent[]>(data.annotation?.events ?? []);
  const [currentMs, setCurrentMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [activeLabel, setActiveLabel] = useState(labels[0]);
  const [markStart, setMarkStart] = useState<number | null>(null);

  const tick = () => {
    const v = videoRef.current;
    if (v) setCurrentMs(Math.round(v.currentTime * 1000));
  };

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { v.play(); setPlaying(true); } else { v.pause(); setPlaying(false); }
  };

  const step = (deltaMs: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.pause(); setPlaying(false);
    v.currentTime = Math.max(0, Math.min(v.duration || 0, v.currentTime + deltaMs / 1000));
    setCurrentMs(Math.round(v.currentTime * 1000));
  };

  const addEvent = () => {
    const start = markStart ?? currentMs;
    const end = Math.max(start + 200, currentMs);
    setEvents((e) => [...e, { label: activeLabel, start_ms: Math.min(start, end), end_ms: end, frames: [] }]);
    setMarkStart(null);
  };

  const captureBoxAtCurrentFrame = (eventIdx: number) => {
    // record the current timestamp into the event's frames (bbox drawing happens on the image workspace flow)
    setEvents((es) => es.map((e, i) => i === eventIdx ? {
      ...e, frames: [...e.frames, { time_ms: currentMs, shapes: [] }],
    } : e));
  };

  const duration = durationMs || 1;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="gap-2">
          <CardTitle className="flex flex-wrap items-center gap-2">
            <span className="truncate">{media.filename}</span>
            {durationMs > 0 && <Badge variant="info">{fmtMs(durationMs)}</Badge>}
            {data.annotation?.is_final && <Badge variant="success">submitted</Badge>}
          </CardTitle>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button variant="secondary" size="sm" onClick={togglePlay}>
              {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />} {playing ? "Pause" : "Play"}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => step(-1000)}>−1s</Button>
            <Button variant="secondary" size="sm" onClick={() => step(-200)}>−200ms</Button>
            <Button variant="secondary" size="sm" onClick={() => step(200)}>+200ms</Button>
            <Button variant="secondary" size="sm" onClick={() => step(1000)}>+1s</Button>
            <Badge variant="neutral">{fmtMs(currentMs)}</Badge>
            <NativeSelect aria-label="Event label" className="w-40" value={activeLabel} onChange={(e) => setActiveLabel(e.target.value)}>
              {labels.map((l) => <option key={l} value={l}>{l}</option>)}
            </NativeSelect>
            <Button variant="secondary" size="sm" onClick={() => setMarkStart(currentMs)}>Mark start</Button>
            <Button size="sm" onClick={addEvent} disabled={data.annotation?.is_final}>
              <Plus className="h-3.5 w-3.5" /> Add event
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <video ref={videoRef} src={streamUrl} controls={false} className="max-h-[46vh] w-full rounded-md bg-black"
            onTimeUpdate={tick} onEnded={() => setPlaying(false)} onClick={togglePlay} preload="metadata" />
          {/* timeline */}
          <div className="relative mt-3 h-12 rounded-md border border-line bg-surface-raised">
            {events.map((e, i) => (
              <div key={i} className="absolute top-0 h-full rounded bg-teal/25 border border-teal-500/50"
                style={{ left: `${(e.start_ms / duration) * 100}%`, width: `${Math.max(0.5, ((e.end_ms - e.start_ms) / duration) * 100)}%` }}
                title={`${e.label}: ${fmtMs(e.start_ms)} → ${fmtMs(e.end_ms)}`}>
                <span className="absolute -top-0.5 left-1 truncate text-[10px] text-teal">{e.label}</span>
              </div>
            ))}
            <div className="absolute top-0 h-full w-0.5 bg-danger" style={{ left: `${(currentMs / duration) * 100}%` }} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Events ({events.length})</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {events.length === 0 ? (
            <p className="text-xs text-fg-muted">Mark a start point, move the playhead to the end, then “Add event”.</p>
          ) : events.map((e, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded border border-line px-2.5 py-1.5 text-xs">
              <Badge variant="info">{e.label}</Badge>
              <span className="font-mono text-fg-muted">{fmtMs(e.start_ms)} → {fmtMs(e.end_ms)}</span>
              <Badge variant="neutral">{e.frames.length} frame{e.frames.length === 1 ? "" : "s"}</Badge>
              <Button variant="ghost" size="sm" onClick={() => captureBoxAtCurrentFrame(i)} disabled={data.annotation?.is_final}>
                + frame at playhead
              </Button>
              <button className="ml-auto text-danger hover:text-danger" aria-label={`Delete event ${i + 1}`}
                onClick={() => setEvents((es) => es.filter((_, j) => j !== i))}>
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="flex gap-2">
        <Button variant="secondary" className="flex-1" onClick={() => onSave({ events, duration_ms: durationMs })}
          disabled={saving || data.annotation?.is_final}>
          <Save className="h-4 w-4" /> {saving ? "Saving…" : "Save draft"}
        </Button>
        <Button className="flex-1" onClick={() => onFinal({})}
          disabled={submitting || !events.length || data.annotation?.is_final}>
          <Send className="h-4 w-4" /> {submitting ? "…" : "Submit"}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audio workspace: waveform + segments + transcript editing
// ---------------------------------------------------------------------------

function AudioWorkspace({ streamUrl, media, data, onSave, onFinal, saving, submitting }: WorkspaceProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const durationMs = data.annotation?.duration_ms ?? media.duration_ms ?? 0;
  const [segments, setSegments] = useState<Segment[]>(data.annotation?.segments ?? []);
  const [currentMs, setCurrentMs] = useState(0);
  const [markStart, setMarkStart] = useState<number | null>(null);
  const [globalLabels, setGlobalLabels] = useState<string[]>(data.annotation?.global_labels ?? []);
  const [playing, setPlaying] = useState(false);

  // waveform via decodeAudioData (peaks cache)
  const peaksRef = useRef<number[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(streamUrl);
        const buf = await res.arrayBuffer();
        const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const ctx = new Ctx();
        const audio = await ctx.decodeAudioData(buf);
        if (cancelled) return;
        const raw = audio.getChannelData(0);
        const buckets = 800;
        const peaks: number[] = [];
        for (let i = 0; i < buckets; i++) {
          let max = 0;
          const s = Math.floor((i * raw.length) / buckets);
          const e = Math.floor(((i + 1) * raw.length) / buckets);
          for (let j = s; j < e; j += 16) max = Math.max(max, Math.abs(raw[j]));
          peaks.push(max);
        }
        peaksRef.current = peaks;
        draw();
        void ctx.close();
      } catch {
        // waveform is best-effort; player still works
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streamUrl]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const peaks = peaksRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const { width, height } = canvas;
    ctx.clearRect(0, 0, width, height);
    if (peaks) {
      ctx.fillStyle = "#16B8A6";
      for (let x = 0; x < width; x++) {
        const p = peaks[Math.floor((x / width) * peaks.length)] ?? 0;
        const h = Math.max(1, p * height * 0.9);
        ctx.fillRect(x, (height - h) / 2, 1, h);
      }
    }
    // segments overlay
    const dur = durationMs || 1;
    for (const s of segments) {
      const x1 = (s.start_ms / dur) * width;
      const x2 = (s.end_ms / dur) * width;
      ctx.fillStyle = "rgba(59,130,246,0.18)";
      ctx.fillRect(x1, 0, Math.max(2, x2 - x1), height);
      ctx.strokeStyle = "#3b82f6";
      ctx.strokeRect(x1, 0.5, Math.max(2, x2 - x1), height - 1);
    }
    ctx.fillStyle = "#ef4444";
    ctx.fillRect((currentMs / dur) * width, 0, 2, height);
  }, [segments, currentMs, durationMs]);

  useEffect(() => { draw(); }, [draw]);

  const tick = () => {
    const a = audioRef.current;
    if (a) setCurrentMs(Math.round(a.currentTime * 1000));
  };

  const togglePlay = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) { void a.play(); setPlaying(true); } else { a.pause(); setPlaying(false); }
  };

  const seek = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - rect.left) / rect.width;
    const a = audioRef.current;
    if (a && durationMs) {
      a.currentTime = (frac * durationMs) / 1000;
      setCurrentMs(Math.round(frac * durationMs));
    }
  };

  const addSegment = () => {
    const start = markStart ?? 0;
    const end = Math.max(start + 200, currentMs);
    setSegments((s) => [...s, {
      start_ms: Math.min(start, end), end_ms: end, transcript: "",
      speaker: null, language: null, emotion: null,
    }]);
    setMarkStart(null);
  };

  const updateSegment = (i: number, patch: Partial<Segment>) =>
    setSegments((ss) => ss.map((s, j) => j === i ? { ...s, ...patch } : s));

  const canSubmit = useMemo(() => segments.every((s) => s.transcript.trim()), [segments]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="gap-2">
          <CardTitle className="flex flex-wrap items-center gap-2">
            <span className="truncate">{media.filename}</span>
            {durationMs > 0 && <Badge variant="info">{fmtMs(durationMs)}</Badge>}
            {data.annotation?.is_final && <Badge variant="success">submitted</Badge>}
          </CardTitle>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button variant="secondary" size="sm" onClick={togglePlay}>
              {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />} {playing ? "Pause" : "Play"}
            </Button>
            {[0.5, 1, 1.5, 2].map((r) => (
              <Button key={r} variant="secondary" size="sm"
                onClick={() => { if (audioRef.current) audioRef.current.playbackRate = r; }}>
                {r}×
              </Button>
            ))}
            <Badge variant="neutral">{fmtMs(currentMs)}</Badge>
            <Button variant="secondary" size="sm" onClick={() => setMarkStart(currentMs)}>Mark start</Button>
            <Button size="sm" onClick={addSegment} disabled={data.annotation?.is_final}>
              <Plus className="h-3.5 w-3.5" /> Add segment
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <canvas ref={canvasRef} width={1000} height={140} onClick={seek}
            className="w-full cursor-pointer rounded-md border border-line bg-surface-raised" />
          <audio ref={audioRef} src={streamUrl} onTimeUpdate={tick} onEnded={() => setPlaying(false)}
            preload="metadata" className="hidden" />
          <p className="mt-2 text-xs text-fg-muted">Click the waveform to seek. Mark start → move playhead → Add segment.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Segments ({segments.length})</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {segments.length === 0 ? (
            <p className="text-xs text-fg-muted">No segments yet — every segment needs a transcript before submit.</p>
          ) : segments.map((s, i) => (
            <div key={i} className="rounded-md border border-line p-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
                <Badge variant="info">{fmtMs(s.start_ms)} → {fmtMs(s.end_ms)}</Badge>
                <Input className="w-24" placeholder="Speaker" value={s.speaker ?? ""}
                  onChange={(e) => updateSegment(i, { speaker: e.target.value || null })} />
                <Input className="w-24" placeholder="Language" value={s.language ?? ""}
                  onChange={(e) => updateSegment(i, { language: e.target.value || null })} />
                <Input className="w-28" placeholder="Emotion" value={s.emotion ?? ""}
                  onChange={(e) => updateSegment(i, { emotion: e.target.value || null })} />
                <button className="ml-auto text-danger hover:text-danger" aria-label={`Delete segment ${i + 1}`}
                  onClick={() => setSegments((ss) => ss.filter((_, j) => j !== i))}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              <textarea rows={2} className="mt-2 w-full rounded-md border border-line bg-surface p-2 text-sm text-fg"
                placeholder="Transcript…" value={s.transcript}
                onChange={(e) => updateSegment(i, { transcript: e.target.value })} />
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="flex gap-2">
        <Button variant="secondary" className="flex-1" onClick={() => onSave({ segments, global_labels: globalLabels, duration_ms: durationMs })}
          disabled={saving || data.annotation?.is_final}>
          <Save className="h-4 w-4" /> {saving ? "Saving…" : "Save draft"}
        </Button>
        <Button className="flex-1" onClick={() => onFinal({})}
          disabled={submitting || !segments.length || !canSubmit || data.annotation?.is_final}>
          <Send className="h-4 w-4" /> {submitting ? "…" : "Submit"}
        </Button>
      </div>
      {!canSubmit && segments.length > 0 && (
        <p className="text-xs text-danger">Every segment needs a transcript before submission.</p>
      )}
    </div>
  );
}
