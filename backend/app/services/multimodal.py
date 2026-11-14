"""Media upload validation and lightweight probing (no heavy dependencies).

Magic-byte sniffing decides the real content type — extensions are never
trusted. Dimensions are parsed for PNG/JPEG/GIF; duration for WAV. Video and
compressed-audio metadata are accepted from the client as *reported* values
and stored as such (documented limitation; probe libs can be added later).
"""
import hashlib
import struct

from fastapi import HTTPException

from app.models.annotation import ALLOWED_MEDIA, MEDIA_TYPES
from app.services import file_storage

MAX_MEDIA_MB = 200


def sniff_media_type(data: bytes) -> tuple[str, str] | None:
    """Returns (media_type, mime) from magic bytes, or None if unknown."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image", "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if data.startswith(b"OggS"):
        return "audio", "audio/ogg"
    if data.startswith(b"ID3") or (len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "audio", "audio/mpeg"
    if data.startswith(b"\x1aE\xdf\xa3"):
        # EBML (Matroska/WebM): could be video or audio; use extension hint later
        return "video", "video/webm"
    if len(data) > 11 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"M4A ", b"M4B "):
            return "audio", "audio/mp4"
        return "video", "video/mp4"
    return None


def probe_dimensions(data: bytes, mime: str) -> dict:
    """Best-effort intrinsic dimensions/duration from headers."""
    out: dict = {}
    try:
        if mime == "image/png":
            w, h = struct.unpack(">II", data[16:24])
            out["width"], out["height"] = int(w), int(h)
        elif mime == "image/gif":
            w, h = struct.unpack("<HH", data[6:10])
            out["width"], out["height"] = int(w), int(h)
        elif mime == "image/jpeg":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    out["width"], out["height"] = int(w), int(h)
                    break
                seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + seg_len
        elif mime == "audio/wav":
            # find fmt + data chunks
            i = 12
            while i + 8 <= len(data):
                cid = data[i:i + 4]
                size = struct.unpack("<I", data[i + 4:i + 8])[0]
                if cid == b"fmt ":
                    fmt = struct.unpack("<H", data[i + 8:i + 10])[0]
                    ch = struct.unpack("<H", data[i + 10:i + 12])[0]
                    rate = struct.unpack("<I", data[i + 12:i + 16])[0]
                    bits = struct.unpack("<H", data[i + 22:i + 24])[0]
                    out["_wav"] = (fmt, ch, rate, bits)
                elif cid == b"data" and "_wav" in out:
                    fmt, ch, rate, bits = out.pop("_wav")
                    bytes_per_frame = max(1, ch * bits // 8)
                    out["duration_ms"] = int(size / bytes_per_frame / rate * 1000)
                    break
                i += 8 + size + (size % 2)
            out.pop("_wav", None)
    except Exception:
        pass
    return out


def validate_and_store_media(data: bytes, filename: str, claimed_mime: str | None) -> dict:
    """Validate content and store it. Returns {media_type, mime, key, size, sha256, probe}."""
    if len(data) == 0:
        raise HTTPException(status_code=422, detail="Empty file.")
    if len(data) > MAX_MEDIA_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_MEDIA_MB} MB limit.")
    sniffed = sniff_media_type(data)
    if sniffed is None:
        raise HTTPException(status_code=415, detail="Unrecognized media content. Upload PNG/JPEG/GIF/WebP images, MP4/WebM video, or WAV/MP3/OGG audio.")
    media_type, mime = sniffed
    if mime not in ALLOWED_MEDIA[media_type]:
        raise HTTPException(status_code=415, detail=f"Content type {mime} is not accepted.")
    ext = ALLOWED_MEDIA[media_type][mime]
    key = file_storage.save_bytes("media", data, ext)
    probe = probe_dimensions(data, mime)
    return {
        "media_type": media_type,
        "mime": mime,
        "key": key,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": probe.get("width"),
        "height": probe.get("height"),
        "duration_ms": probe.get("duration_ms"),
    }


# ---------------------------------------------------------------------------
# Annotation validation (normalized coordinates)
# ---------------------------------------------------------------------------

class AnnotationValidationError(ValueError):
    pass


def _check_norm(v, what: str) -> None:
    if not isinstance(v, (int, float)) or not 0.0 <= float(v) <= 1.0:
        raise AnnotationValidationError(f"{what} must be a number in [0, 1] (normalized).")


def validate_image_shapes(shapes) -> list:
    if not isinstance(shapes, list):
        raise AnnotationValidationError("shapes must be a list.")
    out = []
    for i, s in enumerate(shapes):
        if not isinstance(s, dict):
            raise AnnotationValidationError(f"shape #{i} must be an object.")
        stype = s.get("type")
        if stype not in ("bbox", "polygon", "point"):
            raise AnnotationValidationError(f"shape #{i}: type must be bbox|polygon|point.")
        pts = s.get("points")
        if not isinstance(pts, list) or not pts:
            raise AnnotationValidationError(f"shape #{i}: points required.")
        for p in pts:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                raise AnnotationValidationError(f"shape #{i}: each point is [x, y].")
            _check_norm(p[0], f"shape #{i} x")
            _check_norm(p[1], f"shape #{i} y")
        if stype == "polygon" and len(pts) < 3:
            raise AnnotationValidationError(f"shape #{i}: polygons need >= 3 points.")
        if stype == "bbox" and len(pts) != 2:
            raise AnnotationValidationError(f"shape #{i}: bboxes need exactly 2 corner points.")
        if not str(s.get("label") or "").strip():
            raise AnnotationValidationError(f"shape #{i}: label is required.")
        out.append({
            "type": stype, "label": str(s["label"]).strip(),
            "points": [[float(p[0]), float(p[1])] for p in pts],
        })
    return out


def validate_video_events(events) -> list:
    if not isinstance(events, list):
        raise AnnotationValidationError("events must be a list.")
    out = []
    for i, e in enumerate(events):
        if not isinstance(e, dict):
            raise AnnotationValidationError(f"event #{i} must be an object.")
        start, end = e.get("start_ms"), e.get("end_ms")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            raise AnnotationValidationError(f"event #{i}: 0 <= start_ms < end_ms required.")
        if not str(e.get("label") or "").strip():
            raise AnnotationValidationError(f"event #{i}: label required.")
        frames = []
        for f in (e.get("frames") or []):
            t = f.get("time_ms")
            if not isinstance(t, int) or t < 0:
                raise AnnotationValidationError(f"event #{i}: frame time_ms must be >= 0.")
            frames.append({"time_ms": t,
                           "shapes": validate_image_shapes(f.get("shapes") or [])})
        out.append({"label": str(e["label"]).strip(), "start_ms": start,
                    "end_ms": end, "frames": frames})
    return out


def validate_audio_segments(segments) -> list:
    if not isinstance(segments, list):
        raise AnnotationValidationError("segments must be a list.")
    out = []
    for i, s in enumerate(segments):
        if not isinstance(s, dict):
            raise AnnotationValidationError(f"segment #{i} must be an object.")
        start, end = s.get("start_ms"), s.get("end_ms")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            raise AnnotationValidationError(f"segment #{i}: 0 <= start_ms < end_ms required.")
        transcript = str(s.get("transcript") or "").strip()
        if not transcript:
            raise AnnotationValidationError(f"segment #{i}: transcript required.")
        out.append({
            "start_ms": start, "end_ms": end, "transcript": transcript,
            "speaker": (str(s.get("speaker")).strip() if s.get("speaker") else None),
            "language": (str(s.get("language")).strip() if s.get("language") else None),
            "emotion": (str(s.get("emotion")).strip() if s.get("emotion") else None),
            "labels": [str(x) for x in (s.get("labels") or [])],
        })
    return out


# ---------------------------------------------------------------------------
# Export converters
# ---------------------------------------------------------------------------

def image_to_coco(rows, media_by_id) -> dict:
    """rows: iterable of (ImageAnnotation, MediaAsset). Produces COCO JSON."""
    images, annotations, ann_id = [], [], 1
    for ann, media in rows:
        w = media.width or ann.image_width or 0
        h = media.height or ann.image_height or 0
        images.append({
            "id": media.id, "file_name": media.filename, "width": w, "height": h,
        })
        for shape in ann.shapes or []:
            if shape["type"] == "bbox" and len(shape["points"]) == 2:
                (x1, y1), (x2, y2) = shape["points"]
                bx, by, bw, bh = min(x1, x2) * w, min(y1, y2) * h, abs(x2 - x1) * w, abs(y2 - y1) * h
                segmentation = [[bx, by, bx + bw, by, bx + bw, by + bh, bx, by + bh]]
                area = bw * bh
            elif shape["type"] == "polygon":
                segmentation = [[c for p in shape["points"] for c in (p[0] * w, p[1] * h)]]
                xs = [p[0] * w for p in shape["points"]]
                ys = [p[1] * h for p in shape["points"]]
                area = (max(xs) - min(xs)) * (max(ys) - min(ys))
                bx, by, bw, bh = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
            else:  # point
                px, py = shape["points"][0][0] * w, shape["points"][0][1] * h
                segmentation = [[px, py, 1, 1]]
                area, bx, by, bw, bh = 1.0, px, py, 1, 1
            annotations.append({
                "id": ann_id, "image_id": media.id, "category": shape["label"],
                "segmentation": segmentation, "area": area,
                "bbox": [bx, by, bw, bh], "iscrowd": 0,
            })
            ann_id += 1
    categories = sorted({a["category"] for a in annotations})
    return {
        "images": images,
        "annotations": annotations,
        "categories": [{"id": i + 1, "name": c} for i, c in enumerate(categories)],
    }


def image_to_yolo_rows(rows, media_by_id) -> list[str]:
    """YOLO txt lines: class x_center y_center w h (normalized)."""
    classes: dict[str, int] = {}
    lines: list[str] = []

    def cls_id(name: str) -> int:
        if name not in classes:
            classes[name] = len(classes)
        return classes[name]

    for ann, media in rows:
        w = media.width or ann.image_width or 1
        h = media.height or ann.image_height or 1
        stem = media.filename.rsplit(".", 1)[0]
        for shape in ann.shapes or []:
            if shape["type"] == "bbox" and len(shape["points"]) == 2:
                (x1, y1), (x2, y2) = shape["points"]
                xc = (min(x1, x2) + abs(x2 - x1) / 2)
                yc = (min(y1, y2) + abs(y2 - y1) / 2)
                bw, bh = abs(x2 - x1), abs(y2 - y1)
                lines.append(f"{stem}.txt|{cls_id(shape['label'])} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
    return lines
