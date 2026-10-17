from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import config
from conftest import jpeg_with_metadata, noise_image, png_bytes
from main import app, queue


@pytest.fixture
def client():
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c
    queue.wait_idle()
    queue.clear()


def jpeg_bytes(size=(320, 240)) -> bytes:
    buf = io.BytesIO()
    noise_image(size).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def upload(client, *files):
    payload = [("files", (name, data, "application/octet-stream")) for name, data in files]
    r = client.post("/api/queue/upload", files=payload)
    assert r.status_code == 200, r.text
    return r.json()


def wait_for_batch(client, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get("/api/process/status").json()
        if not status["running"]:
            return status
        time.sleep(0.05)
    raise AssertionError("batch did not finish")


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["version"] == config.VERSION
    assert ".jpg" in body["supported_extensions"]


def test_rejects_foreign_host_and_cross_site_writes(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    r = client.post("/api/queue/paths", json={"paths": ["/"]}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.delete("/api/queue", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    ok = client.post("/api/settings/validate", json={"settings": {}}, headers={"origin": "http://localhost:5173"})
    assert ok.status_code == 200


def test_upload_sanitises_names_and_rejects_bad_files(client):
    body = upload(
        client,
        ("../../escape.jpg", jpeg_bytes()),
        ("notes.txt", b"hello"),
        ("fake.jpg", b"not an image at all"),
        ("empty.png", b""),
    )
    assert len(body["added"]) == 1
    item = body["added"][0]
    assert item["filename"] == "escape.jpg"
    assert Path(item["path"]).is_relative_to(config.UPLOAD_DIR.resolve())
    reasons = {r["name"]: r["reason"] for r in body["rejected"]}
    assert reasons["notes.txt"] == "Unsupported file type"
    assert reasons["fake.jpg"] == "Not a readable image"
    assert reasons["empty.png"] == "File is empty"
    # Rejected uploads leave nothing behind.
    assert len(list(config.UPLOAD_DIR.iterdir())) == 1


def test_same_name_uploads_do_not_overwrite_each_other(client):
    body = upload(client, ("same.jpg", jpeg_bytes((100, 100))), ("same.jpg", jpeg_bytes((200, 100))))
    widths = sorted(i["width"] for i in body["added"])
    assert widths == [100, 200]


def test_full_flow_upload_preview_process_export(client):
    body = upload(client, ("photo.jpg", jpeg_bytes()), ("logo.png", png_bytes(noise_image((64, 64), "RGBA"))))
    ids = [i["id"] for i in body["added"]]

    assert client.get(f"/api/items/{ids[0]}/thumbnail").headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/items/{ids[0]}/source").status_code == 200

    settings = {"compress_mode": "quality", "quality": 70, "output_format": "WEBP"}
    preview = client.post("/api/preview", json={"item_id": ids[0], "settings": settings}).json()
    assert preview["format"] == "WEBP" and preview["new_size"] > 0
    assert client.get(preview["after_url"]).headers["content-type"] == "image/webp"

    r = client.post("/api/process", json={"settings": settings})
    assert r.status_code == 200, r.text
    status = wait_for_batch(client)
    assert status["done"] == 2 and status["failed"] == 0

    items = client.get("/api/queue").json()["items"]
    outputs = [Path(i["result"]["output_path"]) for i in items]
    assert all(p.parent == config.DEFAULT_OUTPUT_DIR for p in outputs)
    assert all(p.suffix == ".webp" and p.is_file() for p in outputs)
    assert client.get(f"/api/items/{ids[0]}/output?download=1").headers["content-disposition"]

    z = client.get("/api/export/zip")
    assert z.status_code == 200
    with zipfile.ZipFile(io.BytesIO(z.content)) as archive:
        assert sorted(archive.namelist()) == sorted(p.name for p in outputs)

    csv_text = client.get("/api/report?format=csv").text
    assert csv_text.splitlines()[0].startswith("filename,status")
    assert len(csv_text.strip().splitlines()) == 3

    assert client.delete("/api/queue").json()["removed"] == 2
    assert list(config.UPLOAD_DIR.iterdir()) == []


def test_batch_plans_unique_names_for_colliding_outputs(client, tmp_path):
    folder = tmp_path / "shots"
    folder.mkdir()
    noise_image((40, 40)).save(folder / "a.png")
    noise_image((40, 40)).save(folder / "a.jpg")
    r = client.post("/api/queue/paths", json={"paths": [str(folder)]})
    assert len(r.json()["added"]) == 2

    client.post("/api/process", json={"settings": {"output_format": "JPEG", "compress_mode": "quality"}})
    wait_for_batch(client)
    outs = sorted(p.name for p in (folder / "processed").iterdir())
    assert outs == ["a_processed-1.jpg", "a_processed.jpg"]


def test_adding_the_same_folder_twice_reports_duplicates(client, tmp_path):
    jpeg_with_metadata(tmp_path / "x.jpg")
    first = client.post("/api/queue/paths", json={"paths": [str(tmp_path)]}).json()
    second = client.post("/api/queue/paths", json={"paths": [str(tmp_path), str(tmp_path / "missing")]}).json()
    assert len(first["added"]) == 1
    assert second["added"] == [] and second["duplicates"] == 1
    assert second["rejected"][0]["reason"] == "Not found"


def test_cancel_stops_the_batch(client, tmp_path):
    for i in range(40):
        noise_image((900, 700)).save(tmp_path / f"img{i:02}.png")
    client.post("/api/queue/paths", json={"paths": [str(tmp_path)]})
    client.post("/api/process", json={"settings": {"output_format": "AVIF", "compress_mode": "quality"}})
    client.post("/api/process/cancel")
    status = wait_for_batch(client)
    assert status["cancelled"] > 0
    assert status["completed"] == status["total"] == 40
    statuses = {i["status"] for i in client.get("/api/queue").json()["items"]}
    assert statuses <= {"done", "cancelled", "failed"}
    # A new batch can start straight away.
    assert client.post("/api/process", json={"settings": {"compress_mode": "lossless"}}).status_code == 200
    wait_for_batch(client)


def test_settings_errors_are_422_with_field(client):
    upload(client, ("a.jpg", jpeg_bytes()))
    r = client.post("/api/process", json={"settings": {"quality": 500}})
    assert r.status_code == 422
    assert r.json()["field"] == "quality"


def test_process_empty_queue_is_400(client):
    assert client.post("/api/process", json={"settings": {}}).status_code == 400


def test_preset_crud(client):
    builtin = client.get("/api/presets").json()["presets"]
    assert any(p["builtin"] for p in builtin)

    saved = client.post("/api/presets", json={"name": "My Web", "settings": {"quality": 77}}).json()["preset"]
    assert saved["id"] == "custom-my-web" and saved["settings"]["quality"] == 77

    bad = client.post("/api/presets", json={"name": "x", "id": builtin[0]["id"], "settings": {}})
    assert bad.status_code == 409

    assert client.delete(f"/api/presets/{saved['id']}").status_code == 200
    assert client.delete(f"/api/presets/{saved['id']}").status_code == 404


def test_reveal_only_known_paths(client):
    assert client.post("/api/system/reveal", json={"path": "/etc/passwd"}).status_code == 403


def test_zip_without_results_is_404(client):
    assert client.get("/api/export/zip").status_code == 404


def test_frontend_missing_message(client):
    r = client.get("/")
    assert r.status_code == 503 and "isn't built" in r.text


def test_preview_of_huge_output_is_downscaled_for_display(client):
    item = upload(client, ("tall.png", png_bytes(noise_image((760, 1600)))))["added"][0]
    r = client.post(
        "/api/preview",
        json={"item_id": item["id"], "settings": {"upscale_enabled": True, "upscale_factor": 4, "compress_mode": "lossless"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_dimensions"] == [3040, 6400]
    dw, dh = body["display_dimensions"]
    assert dw * dh <= 16_000_000 and max(dw, dh) <= 6000
    assert body["display_scale"] < 1
    shown = client.get(body["after_url"])
    with Image.open(io.BytesIO(shown.content)) as img:
        assert img.size == (dw, dh)
    src = client.get(f"/api/items/{item['id']}/source")
    assert src.status_code == 200
