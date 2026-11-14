// Multimodal projects: media library, annotation task generation, exports.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Film, Image as ImageIcon, ListPlus, Music, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { queries as v1queries } from "@/api/hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";
import type { ProjectDetail } from "@/lib/types";

interface MediaItem {
  id: number; filename: string; media_type: "image" | "video" | "audio";
  mime_type: string; size_bytes: number; width: number | null; height: number | null;
  duration_ms: number | null; status: string; created_at: string | null;
}

const fmtSize = (b: number) => {
  if (!b) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
  return `${(b / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
};

const ICONS = { image: ImageIcon, video: Film, audio: Music };

export default function MultimodalPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [projectId, setProjectId] = useState("");
  const [mediaType, setMediaType] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [labels, setLabels] = useState("");

  const projects = useQuery(v1queries.projects());
  const projectList = (projects.data ?? []) as unknown as ProjectDetail[];
  const adminProjects = projectList.filter((p) => p.is_admin);
  const activeProject = projectId || (adminProjects[0]?.id ? String(adminProjects[0].id) : "");

  const media = useQuery({
    queryKey: ["media", activeProject, mediaType],
    queryFn: () => api.get<MediaItem[]>(`/media/projects/${activeProject}${mediaType ? `?media_type=${mediaType}` : ""}`),
    enabled: !!activeProject,
  });

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("file", file!);
      if (labels.trim()) {
        fd.append("annotation_config", JSON.stringify({ labels: labels.split(",").map((s) => s.trim()).filter(Boolean) }));
      }
      return api.upload(`/media/projects/${activeProject}/upload`, fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["media"] });
      setFile(null);
      toast("success", "Media uploaded");
    },
    onError: (e) => toast("error", "Upload failed", (e as Error).message),
  });

  const generateTasks = useMutation({
    mutationFn: () => api.post<{ created: number; skipped_existing: number }>(
      `/media/projects/${activeProject}/generate-tasks`,
      mediaType ? { media_type: mediaType } : {}),
    onSuccess: (d) => {
      toast("success", `${d.created} annotation tasks created`,
        d.skipped_existing ? `${d.skipped_existing} already had tasks.` : undefined);
    },
    onError: (e) => toast("error", "Generation failed", (e as Error).message),
  });

  const download = async (format: string) => {
    try {
      const { blob, disposition } = await api.getRawBlob(
        `/exports/annotations?project_id=${activeProject}&media_type=${mediaType || "image"}&format=${format}`);
      const match = /filename="?([^";]+)"?/.exec(disposition ?? "");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = match?.[1] ?? `annotations.${format}`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast("success", "Export downloaded");
    } catch (e) {
      toast("error", "Export failed", (e as Error).message);
    }
  };

  const list = media.data ?? [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Multimodal annotation</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Upload images, video and audio; generate annotation tasks; export approved annotations.
        </p>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Media library</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect aria-label="Project" className="w-52" value={activeProject} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">— Select project —</option>
              {adminProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </NativeSelect>
            <NativeSelect aria-label="Media type" className="w-36" value={mediaType} onChange={(e) => setMediaType(e.target.value)}>
              <option value="">All types</option>
              <option value="image">Images</option>
              <option value="video">Video</option>
              <option value="audio">Audio</option>
            </NativeSelect>
            <Button variant="secondary" size="sm" onClick={() => generateTasks.mutate()}
              disabled={!activeProject || generateTasks.isPending}>
              <ListPlus className="h-4 w-4" /> Generate tasks
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {!activeProject ? (
            <EmptyState title="Select a project" />
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-end gap-2 rounded-md border border-line bg-surface-raised p-3">
                <div>
                  <Label htmlFor="mm-file">Upload media (PNG/JPEG/GIF/WebP, MP4/WebM, WAV/MP3/OGG — 200 MB max)</Label>
                  <Input id="mm-file" type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.mp4,.webm,.mov,.wav,.mp3,.ogg,.m4a"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                </div>
                <div>
                  <Label htmlFor="mm-labels">Annotation labels (comma-separated)</Label>
                  <Input id="mm-labels" className="w-64" placeholder="car, person, traffic light"
                    value={labels} onChange={(e) => setLabels(e.target.value)} />
                </div>
                <Button onClick={() => upload.mutate()} disabled={!file || upload.isPending}>
                  <Upload className="h-4 w-4" /> {upload.isPending ? "Uploading…" : "Upload"}
                </Button>
                <div className="ml-auto flex gap-1.5">
                  {["coco", "csv", "json"].map((f) => (
                    <Button key={f} variant="secondary" size="sm" onClick={() => download(f)}>
                      <Download className="h-3.5 w-3.5" /> {f.toUpperCase()}
                    </Button>
                  ))}
                </div>
              </div>

              {media.isLoading ? (
                <TableSkeleton rows={4} cols={5} />
              ) : media.isError ? (
                <ErrorState message={(media.error as Error)?.message} retry={media.refetch} />
              ) : list.length === 0 ? (
                <EmptyState title="No media yet" description="Upload the first asset above." />
              ) : (
                <Table>
                  <THead><TR><TH>File</TH><TH>Type</TH><TH>Dimensions / Duration</TH><TH>Size</TH><TH>Uploaded</TH></TR></THead>
                  <TBody>
                    {list.map((m) => {
                      const Icon = ICONS[m.media_type] ?? ImageIcon;
                      return (
                        <TR key={m.id}>
                          <TD>
                            <div className="flex items-center gap-2 text-sm font-medium text-fg">
                              <Icon className="h-4 w-4 text-teal" /> {m.filename}
                            </div>
                            <div className="text-xs text-fg-muted">{m.mime_type}</div>
                          </TD>
                          <TD><Badge variant="info">{m.media_type}</Badge></TD>
                          <TD className="text-xs text-fg-muted">
                            {m.width && m.height ? `${m.width}×${m.height}` : ""}
                            {m.duration_ms ? ` ${fmtDateTime(null) === "" ? "" : "· "}${Math.round(m.duration_ms / 100) / 10}s` : ""}
                            {!m.width && !m.duration_ms ? "—" : ""}
                          </TD>
                          <TD className="text-xs text-fg-muted">{fmtSize(m.size_bytes)}</TD>
                          <TD className="text-xs text-fg-muted">{fmtDateTime(m.created_at)}</TD>
                        </TR>
                      );
                    })}
                  </TBody>
                </Table>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
