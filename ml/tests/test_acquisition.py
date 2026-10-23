"""Downloader tests use fabricated ZIP bytes, never an external network."""

import hashlib
import http.client
import io
import json
import urllib.error
import zipfile

import pytest

from ml.data import acquisition


class Response(io.BytesIO):
    def __init__(self, content, headers=None):
        super().__init__(content)
        self.headers = headers or {"Content-Length": str(len(content))}


def archive_bytes(name="Online Retail.xlsx", content=b"synthetic workbook"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return stream.getvalue()


def mock_response(monkeypatch, content, headers=None):
    monkeypatch.setattr(
        acquisition.urllib.request,
        "urlopen",
        lambda *a, **kw: Response(content, headers),
    )


def test_official_source_atomic_publication_and_verified_cache(tmp_path, monkeypatch):
    archive = archive_bytes()
    mock_response(monkeypatch, archive)
    digest = hashlib.sha256(archive).hexdigest()
    result = acquisition.download_official(tmp_path, expected_archive_sha256=digest)
    assert result.workbook_path.read_bytes() == b"synthetic workbook"
    assert result.provenance["archive_sha256"] == digest
    assert result.provenance["url"] == acquisition.OFFICIAL_URL
    assert (
        json.loads((result.workbook_path.parent / "source.json").read_text())
        == result.provenance
    )
    monkeypatch.setattr(
        acquisition.urllib.request,
        "urlopen",
        lambda *a, **kw: pytest.fail("cache must avoid network"),
    )
    assert acquisition.download_official(tmp_path) == result
    result.workbook_path.write_bytes(b"corrupt")
    with pytest.raises(acquisition.DownloadError, match="corrupt"):
        acquisition.download_official(tmp_path)


@pytest.mark.parametrize(
    "content",
    [b"not zip", archive_bytes("../Online Retail.xlsx"), archive_bytes(content=b"")],
)
def test_bad_archive_never_published(tmp_path, monkeypatch, content):
    mock_response(monkeypatch, content)
    with pytest.raises(acquisition.DownloadError):
        acquisition.download_official(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_multiple_archive_members_refused(tmp_path, monkeypatch):
    stream = io.BytesIO(archive_bytes())
    with zipfile.ZipFile(stream, "a") as archive:
        archive.writestr("extra.txt", "untrusted")
    mock_response(monkeypatch, stream.getvalue())
    with pytest.raises(acquisition.DownloadError, match="only"):
        acquisition.download_official(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_expected_digest_mismatch_and_invalid_argument(tmp_path, monkeypatch):
    mock_response(monkeypatch, archive_bytes())
    with pytest.raises(acquisition.DownloadError, match="checksum"):
        acquisition.download_official(tmp_path, expected_archive_sha256="0" * 64)
    assert list(tmp_path.iterdir()) == []
    for value in ("bad", "g" * 64):
        with pytest.raises(acquisition.DownloadError, match="64 hex"):
            acquisition.download_official(tmp_path, expected_archive_sha256=value)
    for attempts in (0, 6):
        with pytest.raises(acquisition.DownloadError, match="attempts"):
            acquisition.download_official(tmp_path, attempts=attempts)


def test_bounded_retry_and_http_error(tmp_path, monkeypatch):
    calls = []
    waits = []
    content = archive_bytes()

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.URLError("temporary")
        return Response(content)

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(acquisition.time, "sleep", waits.append)
    acquisition.download_official(tmp_path)
    assert len(calls) == 3
    assert waits == [1, 2]

    def missing(*args, **kwargs):
        raise urllib.error.HTTPError(acquisition.OFFICIAL_URL, 404, "missing", {}, None)

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", missing)
    with pytest.raises(acquisition.DownloadError, match="1 attempt"):
        acquisition.download_official(tmp_path / "other")


def test_retry_exhaustion_has_no_partial_cache(tmp_path, monkeypatch):
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("temporary")

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", unavailable)
    monkeypatch.setattr(acquisition.time, "sleep", lambda _: None)
    with pytest.raises(acquisition.DownloadError, match="3 attempt"):
        acquisition.download_official(tmp_path)
    assert len(calls) == 3
    assert list(tmp_path.iterdir()) == []


def test_partial_stream_is_retried_then_safely_fails(tmp_path, monkeypatch):
    attempts = []

    class BrokenResponse(Response):
        def read(self, *args):
            raise http.client.IncompleteRead(b"partial")

    def broken(*args, **kwargs):
        attempts.append(1)
        return BrokenResponse(b"data")

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", broken)
    monkeypatch.setattr(acquisition.time, "sleep", lambda _: None)
    with pytest.raises(acquisition.DownloadError, match="3 attempt"):
        acquisition.download_official(tmp_path)
    assert len(attempts) == 3
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "headers", [{"Content-Length": "9999999999"}, {"Content-Length": "9999"}]
)
def test_size_limits_and_truncation(tmp_path, monkeypatch, headers):
    mock_response(monkeypatch, archive_bytes(), headers)
    with pytest.raises(acquisition.DownloadError):
        acquisition.download_official(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_streaming_and_extraction_limits(tmp_path, monkeypatch):
    mock_response(monkeypatch, archive_bytes(), {"Transfer-Encoding": "chunked"})
    monkeypatch.setattr(acquisition, "MAX_ARCHIVE_BYTES", 5)
    with pytest.raises(acquisition.DownloadError, match="download size"):
        acquisition.download_official(tmp_path)
    monkeypatch.setattr(acquisition, "MAX_ARCHIVE_BYTES", 10000)
    monkeypatch.setattr(acquisition, "MAX_WORKBOOK_BYTES", 3)
    with pytest.raises(acquisition.DownloadError, match="extraction size"):
        acquisition.download_official(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_incomplete_and_checksum_pinned_cache(tmp_path, monkeypatch):
    mock_response(monkeypatch, archive_bytes())
    result = acquisition.download_official(tmp_path)
    with pytest.raises(acquisition.DownloadError, match="checksum"):
        acquisition.download_official(tmp_path, expected_archive_sha256="0" * 64)
    (result.workbook_path.parent / "source.json").unlink()
    with pytest.raises(acquisition.DownloadError, match="Incomplete"):
        acquisition.download_official(tmp_path)
