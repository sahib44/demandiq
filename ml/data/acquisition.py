"""Bounded, integrity-checked acquisition of the official UCI workbook."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OFFICIAL_URL = "https://archive.ics.uci.edu/static/public/352/online%2Bretail.zip"
WORKBOOK_NAME = "Online Retail.xlsx"
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_WORKBOOK_BYTES = 100 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


class DownloadError(ValueError):
    """Acquisition failed without publishing a completed source directory."""


@dataclass(frozen=True)
class DownloadResult:
    workbook_path: Path
    provenance: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    """Stable UTF-8 JSON; never serialize NaN/Infinity into reports."""
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _check_expected(actual: str, expected: str | None) -> None:
    if expected is not None and actual != expected.lower():
        raise DownloadError("Official archive checksum does not match expected SHA-256")


def _read_cache(directory: Path, expected: str | None) -> DownloadResult:
    try:
        provenance = json.loads((directory / "source.json").read_text())
        if provenance["url"] != OFFICIAL_URL:
            raise DownloadError("Cached source URL is not the official URL")
        archive_digest = sha256_file(directory / "online-retail.zip")
        workbook = directory / WORKBOOK_NAME
        if archive_digest != provenance["archive_sha256"] or (
            sha256_file(workbook) != provenance["workbook_sha256"]
        ):
            raise DownloadError("Cached source is corrupt; use a new --raw-dir")
        _check_expected(archive_digest, expected)
        return DownloadResult(workbook, provenance)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DownloadError("Incomplete source cache; use a new --raw-dir") from exc


def _fetch_archive(path: Path, *, attempts: int, timeout: float) -> None:
    request = urllib.request.Request(
        OFFICIAL_URL, headers={"User-Agent": "DemandIQ/0.1 (UCI dataset reproduction)"}
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                size_header = response.headers.get("Content-Length")
                if size_header and int(size_header) > MAX_ARCHIVE_BYTES:
                    raise DownloadError("Official archive exceeds download size limit")
                total = 0
                with path.open("wb") as output:
                    while chunk := response.read(CHUNK_BYTES):
                        total += len(chunk)
                        if total > MAX_ARCHIVE_BYTES:
                            raise DownloadError(
                                "Official archive exceeds download size limit"
                            )
                        output.write(chunk)
                if size_header and total != int(size_header):
                    raise DownloadError("Official archive response was truncated")
                if total == 0:
                    raise DownloadError("Official archive response was empty")
            return
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
        ) as exc:
            retryable = not isinstance(exc, urllib.error.HTTPError) or (
                exc.code in {408, 429} or 500 <= exc.code < 600
            )
            if not retryable or attempt + 1 == attempts:
                raise DownloadError(
                    f"Official download failed after {attempt + 1} attempt(s)"
                ) from exc
            time.sleep(min(2**attempt, 4))


def _extract_workbook(archive: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) != 1 or members[0].filename != WORKBOOK_NAME:
                raise DownloadError(
                    "Archive must contain only the expected UCI workbook"
                )
            member = members[0]
            if member.file_size <= 0 or member.file_size > MAX_WORKBOOK_BYTES:
                raise DownloadError(
                    "Workbook exceeds extraction size limit or is empty"
                )
            # Never extract paths supplied by the ZIP archive.
            with bundle.open(member) as source, destination.open("wb") as target:
                total = 0
                while chunk := source.read(CHUNK_BYTES):
                    total += len(chunk)
                    if total > MAX_WORKBOOK_BYTES:
                        raise DownloadError("Workbook exceeds extraction size limit")
                    target.write(chunk)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise DownloadError("Invalid or unsupported official ZIP archive") from exc


def download_official(
    raw_dir: Path,
    *,
    expected_archive_sha256: str | None = None,
    attempts: int = 3,
    timeout: float = 60,
) -> DownloadResult:
    """Publish an intact source atomically, or verify an existing local cache.

    First acquisition records observed checksums (trust on first download). Pass
    an expected archive digest to pin a previously verified source version.
    """
    if attempts < 1 or attempts > 5 or timeout <= 0:
        raise DownloadError("attempts must be 1..5 and timeout must be positive")
    if expected_archive_sha256 is not None and (
        len(expected_archive_sha256) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in expected_archive_sha256)
    ):
        raise DownloadError("Expected SHA-256 must contain exactly 64 hex characters")
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    final = raw_dir / "uci-online-retail"
    if final.exists():
        return _read_cache(final, expected_archive_sha256)

    staging = Path(tempfile.mkdtemp(prefix=".download-", dir=raw_dir))
    try:
        archive = staging / "online-retail.zip"
        _fetch_archive(archive, attempts=attempts, timeout=timeout)
        archive_digest = sha256_file(archive)
        _check_expected(archive_digest, expected_archive_sha256)
        workbook = staging / WORKBOOK_NAME
        _extract_workbook(archive, workbook)
        provenance = {
            "url": OFFICIAL_URL,
            "archive_sha256": archive_digest,
            "workbook_sha256": sha256_file(workbook),
            "archive_bytes": archive.stat().st_size,
            "workbook_bytes": workbook.stat().st_size,
            "citation": "Chen, D. (2015). Online Retail. UCI. doi:10.24432/C5BW33",
            "license": "CC BY 4.0",
        }
        (staging / "source.json").write_text(
            canonical_json(provenance), encoding="utf-8"
        )
        try:
            os.rename(staging, final)
        except OSError:
            if not final.exists():
                raise
            # Another downloader may have won the publication race.
            cached = _read_cache(final, archive_digest)
            return cached
        return DownloadResult(final / WORKBOOK_NAME, provenance)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
