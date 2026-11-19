"""Hermetic tests for tools/logo_sync.py (CDN downloads + manifest cache)."""

import json
import sys

sys.path.insert(0, "tools")

import logo_sync  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-pixels"
JPG = b"\xff\xd8\xff\xe0" + b"fake-jpeg"


def logos(url="https://cdn.example/logo.png", tid="7"):
    return {"Team Seven": {"id": tid, "url": url}}


def test_sync_downloads_and_writes_manifest(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return PNG

    manifest = logo_sync.sync_logos(
        logos(), fetch=fetch, delay=0,
        manifest_path=tmp_path / "logos.json", logo_dir=tmp_path / "logos")

    assert calls == ["https://cdn.example/logo.png"]
    assert (tmp_path / "logos" / "7.png").read_bytes() == PNG
    entry = manifest["Team Seven"]
    assert entry["file"] == "7.png" and entry["url"].endswith("logo.png")
    assert entry["fetched_at"]
    persisted = json.loads((tmp_path / "logos.json").read_text())
    assert persisted == manifest
    assert not (tmp_path / "logos.json.tmp").exists()


def test_unchanged_url_is_cached(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return PNG

    kwargs = dict(fetch=fetch, delay=0,
                  manifest_path=tmp_path / "logos.json", logo_dir=tmp_path / "logos")
    logo_sync.sync_logos(logos(), **kwargs)
    logo_sync.sync_logos(logos(), **kwargs)
    assert len(calls) == 1  # second run never re-downloads

    # a changed URL does re-download
    logo_sync.sync_logos(logos(url="https://cdn.example/new.png"), **kwargs)
    assert len(calls) == 2


def test_missing_file_forces_refetch(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return PNG

    kwargs = dict(fetch=fetch, delay=0,
                  manifest_path=tmp_path / "logos.json", logo_dir=tmp_path / "logos")
    logo_sync.sync_logos(logos(), **kwargs)
    (tmp_path / "logos" / "7.png").unlink()
    logo_sync.sync_logos(logos(), **kwargs)
    assert len(calls) == 2


def test_jpeg_magic_gets_jpg_extension(tmp_path):
    manifest = logo_sync.sync_logos(
        logos(), fetch=lambda url: JPG, delay=0,
        manifest_path=tmp_path / "logos.json", logo_dir=tmp_path / "logos")
    assert manifest["Team Seven"]["file"] == "7.jpg"


def test_non_image_and_fetch_errors_are_fail_soft(tmp_path):
    def junk(url):
        return b"<html>not an image</html>"

    def boom(url):
        raise OSError("cdn down")

    kwargs = dict(delay=0, manifest_path=tmp_path / "logos.json",
                  logo_dir=tmp_path / "logos")
    m1 = logo_sync.sync_logos(logos(), fetch=junk, **kwargs)
    assert m1 == {}  # nothing persisted for a non-image
    m2 = logo_sync.sync_logos(logos(), fetch=boom, **kwargs)
    assert m2 == {}  # and a fetch error never raises


def test_corrupt_manifest_tolerated_and_bad_ids_skipped(tmp_path):
    (tmp_path / "logos.json").write_text("{corrupt", encoding="utf-8")
    manifest = logo_sync.sync_logos(
        {"Bad": {"id": "../evil", "url": "https://cdn.example/x.png"},
         "Good": {"id": "3", "url": "https://cdn.example/y.png"}},
        fetch=lambda url: PNG, delay=0,
        manifest_path=tmp_path / "logos.json", logo_dir=tmp_path / "logos")
    assert "Bad" not in manifest  # path-ish id never becomes a filename
    assert manifest["Good"]["file"] == "3.png"
