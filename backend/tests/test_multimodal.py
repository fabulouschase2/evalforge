"""V3 Phases 5-7: multimodal — media validation, annotation saving, review, exports."""
import io
import json
import struct

import pytest


def _register(client, email, name, password="TestPass!23"):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _png_bytes(width=400, height=200) -> bytes:
    """Minimal valid PNG header (IHDR only) — enough for header sniffing/probing."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    crc = b"\x00\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + crc
            + struct.pack(">I", 0) + b"IEND")


def _wav_bytes(seconds=2, rate=8000, channels=1, bits=16) -> bytes:
    n = seconds * rate * channels * bits // 8
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * bits // 8, channels * bits // 8, bits)
    data = b"\x00" * n
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture()
def media_world(client, db):
    ah = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {ah['access_token']}"}
    project = client.post("/api/projects", headers=ah, json={"name": "Multimodal Proj"}).json()
    tester = _register(client, "worker.m@test.dev", "Worker M")
    client.post(f"/api/projects/{project['id']}/members", headers=ah,
                json={"email": "worker.m@test.dev", "role": "tester"})
    th = _login(client, "worker.m@test.dev")
    # image + audio media
    img = client.post(f"/api/media/projects/{project['id']}/upload", headers=ah,
                      files={"file": ("scene.png", _png_bytes(), "image/png")},
                      data={"annotation_config": json.dumps({"labels": ["car", "person"]})})
    assert img.status_code == 201, img.text
    aud = client.post(f"/api/media/projects/{project['id']}/upload", headers=ah,
                      files={"file": ("interview.wav", _wav_bytes(), "audio/wav")})
    assert aud.status_code == 201, aud.text
    # generate annotation tasks for both assets up front
    gen = client.post(f"/api/media/projects/{project['id']}/generate-tasks", headers=ah, json={})
    assert gen.status_code == 201 and gen.json()["created"] == 2
    return {"client": client, "ah": ah, "th": th, "project": project,
            "image": img.json(), "audio": aud.json(), "tester_id": tester["user"]["id"]}


def _login(client, email, password="TestPass!23"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_media_upload_probes_metadata(media_world):
    image, audio = media_world["image"], media_world["audio"]
    assert image["media_type"] == "image" and image["width"] == 400 and image["height"] == 200
    assert audio["media_type"] == "audio"
    assert audio["duration_ms"] is not None and abs(audio["duration_ms"] - 2000) <= 50

    # rejected content
    c = media_world["client"]
    r = c.post(f"/api/media/projects/{media_world['project']['id']}/upload",
               headers=media_world["ah"], files={"file": ("x.png", b"not a png", "image/png")})
    assert r.status_code == 415


def test_annotation_task_generation_and_media_stream(media_world):
    c, ah, th = media_world["client"], media_world["ah"], media_world["th"]
    pid = media_world["project"]["id"]
    # fixture already generated; verify idempotency now
    r = c.post(f"/api/media/projects/{pid}/generate-tasks", headers=ah, json={})
    assert r.status_code == 201 and r.json()["created"] == 0 and r.json()["skipped_existing"] == 2

    # tester sees annotation tasks and can stream the media (Range request)
    items = c.get("/api/tasks/available", headers=th).json()["items"]
    assert len(items) == 2
    media_id = media_world["image"]["id"]
    r = c.get(f"/api/media/{media_id}/stream", headers=th)
    assert r.status_code == 200
    r = c.get(f"/api/media/{media_id}/stream", headers={**th, "Range": "bytes=0-15"})
    assert r.status_code == 206
    assert len(r.content) == 16

    # outsider tester cannot stream
    outsider = _register(c, "outsider.m@test.dev", "Outsider")
    oh = {"Authorization": f"Bearer {outsider['access_token']}"}
    assert c.get(f"/api/media/{media_id}/stream", headers=oh).status_code == 403


def test_image_annotation_save_validate_submit_review(media_world):
    c, ah, th = media_world["client"], media_world["ah"], media_world["th"]
    pid = media_world["project"]["id"]
    task = [t for t in c.get("/api/tasks/available", headers=th).json()["items"]
            if t["title"].startswith("Annotate image")][0]
    tid = task["id"]
    assert c.post(f"/api/tasks/{tid}/claim", headers=th).status_code == 200
    assert c.post(f"/api/tasks/{tid}/start", headers=th).status_code == 200

    # invalid coordinates rejected (2.0 out of range)
    bad = c.put(f"/api/annotation-tasks/{tid}/annotation", headers=th, json={
        "shapes": [{"type": "bbox", "label": "car", "points": [[2.0, 0.1], [0.5, 0.6]]}]})
    assert bad.status_code == 422

    # valid save (normalized coords)
    r = c.put(f"/api/annotation-tasks/{tid}/annotation", headers=th, json={
        "shapes": [{"type": "bbox", "label": "car", "points": [[0.1, 0.2], [0.5, 0.6]]},
                   {"type": "point", "label": "person", "points": [[0.8, 0.3]]}],
        "labels": ["car", "person"]})
    assert r.status_code == 200, r.text
    v1 = r.json()
    assert v1["version"] == 1 and len(v1["shapes"]) == 2

    # second save bumps the version
    r = c.put(f"/api/annotation-tasks/{tid}/annotation", headers=th, json={
        "shapes": [{"type": "bbox", "label": "car", "points": [[0.1, 0.2], [0.55, 0.65]]}]})
    assert r.json()["version"] == 2

    # polygon needs 3 points
    poly_bad = c.put(f"/api/annotation-tasks/{tid}/annotation", headers=th, json={
        "shapes": [{"type": "polygon", "label": "car", "points": [[0.1, 0.1], [0.2, 0.2]]}]})
    assert poly_bad.status_code == 422

    # submit -> submission created; reviewer approves via the standard flow
    sub = c.post(f"/api/annotation-tasks/{tid}/submit", headers=th, json={})
    assert sub.status_code == 200, sub.text
    submission_id = sub.json()["submission_id"]

    queue = c.get("/api/submissions/review-queue", headers=ah).json()["items"]
    match = [s for s in queue if s["id"] == submission_id]
    assert match, "annotation submission should be reviewable"
    assert c.post(f"/api/submissions/{submission_id}/claim-review", headers=ah).status_code == 200
    ok = c.post(f"/api/submissions/{submission_id}/review", headers=ah,
                json={"decision": "approved", "comments": "Boxes look accurate."})
    assert ok.status_code == 200, ok.text

    # get_annotation shows the final annotation
    got = c.get(f"/api/annotation-tasks/{tid}/annotation", headers=ah).json()
    assert got["annotation"]["is_final"] is True


def test_video_annotation_timestamps(media_world):
    c, ah, th = media_world["client"], media_world["ah"], media_world["th"]
    # upload a tiny mp4 (ftyp header only — header sniffing)
    mp4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    vid = c.post(f"/api/media/projects/{media_world['project']['id']}/upload", headers=ah,
                 files={"file": ("clip.mp4", mp4, "video/mp4")})
    assert vid.status_code == 201
    c.post(f"/api/media/projects/{media_world['project']['id']}/generate-tasks",
           headers=ah, json={"media_type": "video"})
    task = [t for t in c.get("/api/tasks/available", headers=th).json()["items"]
            if t["title"].startswith("Annotate video")][0]
    tid = task["id"]
    c.post(f"/api/tasks/{tid}/claim", headers=th)
    c.post(f"/api/tasks/{tid}/start", headers=th)

    # invalid time range rejected
    bad = c.put(f"/api/annotation-tasks/{tid}/annotation", headers=th, json={
        "events": [{"label": "goal", "start_ms": 5000, "end_ms": 4000}]})
    assert bad.status_code == 422

    r = c.put(f"/api/annotation-tasks/{tid}/annotation", headers=th, json={
        "events": [{"label": "goal", "start_ms": 1000, "end_ms": 4000,
                    "frames": [{"time_ms": 1000, "shapes": [{"type": "bbox", "label": "player",
                                                             "points": [[0.2, 0.3], [0.4, 0.6]]}]}]},
                   {"label": "celebration", "start_ms": 4000, "end_ms": 9000}],
        "duration_ms": 120000})
    assert r.status_code == 200, r.text
    events = r.json()["events"]
    assert events[0]["start_ms"] == 1000 and events[0]["end_ms"] == 4000
    assert events[1]["end_ms"] == 9000
    sub = c.post(f"/api/annotation-tasks/{tid}/submit", headers=th, json={})
    assert sub.status_code == 200


def test_audio_annotation_segments(media_world):
    c, ah, th = media_world["client"], media_world["ah"], media_world["th"]
    task = [t for t in c.get("/api/tasks/available", headers=th).json()["items"]
            if t["title"].startswith("Annotate audio")][0]
    tid = task["id"]
    c.post(f"/api/tasks/{tid}/claim", headers=th)
    c.post(f"/api/tasks/{tid}/start", headers=th)

    bad = c.put(f"/api/annotation-tasks/{tid}/annotation", headers=th, json={
        "segments": [{"start_ms": 0, "end_ms": 100, "transcript": ""}]})
    assert bad.status_code == 422

    r = c.put(f"/api/annotation-tasks/{tid}/annotation", headers=th, json={
        "segments": [
            {"start_ms": 0, "end_ms": 1800, "transcript": "Hello and welcome.",
             "speaker": "S1", "language": "en", "emotion": "neutral"},
            {"start_ms": 1800, "end_ms": 2000, "transcript": "Bye.", "speaker": "S2"},
        ]})
    assert r.status_code == 200, r.text
    segments = r.json()["segments"]
    assert len(segments) == 2 and segments[0]["speaker"] == "S1"
    sub = c.post(f"/api/annotation-tasks/{tid}/submit", headers=th, json={})
    assert sub.status_code == 200


def test_exports_coco_csv_json(media_world):
    c, ah, th = media_world["client"], media_world["ah"], media_world["th"]
    # annotate + approve one image first
    task = [t for t in c.get("/api/tasks/available", headers=th).json()["items"]
            if t["title"].startswith("Annotate image")][0]
    c.post(f"/api/tasks/{task['id']}/claim", headers=th)
    c.post(f"/api/tasks/{task['id']}/start", headers=th)
    c.put(f"/api/annotation-tasks/{task['id']}/annotation", headers=th, json={
        "shapes": [{"type": "bbox", "label": "car", "points": [[0.1, 0.2], [0.5, 0.6]]}]})
    sub = c.post(f"/api/annotation-tasks/{task['id']}/submit", headers=th, json={})
    sid = sub.json()["submission_id"]
    c.post(f"/api/submissions/{sid}/claim-review", headers=ah)
    c.post(f"/api/submissions/{sid}/review", headers=ah, json={"decision": "approved"})

    pid = media_world["project"]["id"]
    # COCO
    r = c.get(f"/api/exports/annotations?project_id={pid}&media_type=image&format=coco", headers=ah)
    assert r.status_code == 200, r.text
    coco = json.loads(r.content)
    assert coco["images"] and coco["annotations"]
    ann = coco["annotations"][0]
    # pixel-space bbox: x=0.1*400=40, y=0.2*200=40, w=0.4*400=160, h=0.4*200=80
    assert [round(v) for v in ann["bbox"]] == [40, 40, 160, 80]
    # CSV
    r = c.get(f"/api/exports/annotations?project_id={pid}&media_type=image&format=csv", headers=ah)
    assert r.status_code == 200 and b"car" in r.content
    # native JSON + audio
    r = c.get(f"/api/exports/annotations?project_id={pid}&media_type=audio&format=json", headers=ah)
    assert r.status_code == 200
    # tester cannot export
    r = c.get(f"/api/exports/annotations?project_id={pid}&media_type=image&format=coco", headers=th)
    assert r.status_code == 403
