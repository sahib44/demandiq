"""Install a pinned official Homebrew OpenMP bottle into a local ignored cache.

Optional alternative to `brew install libomp` for Apple Silicon macOS 15/26.
Only the expected library is extracted; no system directories are changed.
"""

import argparse
import hashlib
import io
import json
import platform
import tarfile
import urllib.request
from pathlib import Path

BOTTLES = {
    "tahoe": "16242d8803a0f31370b94f685a219c83783317748a76f02b9144cd6ce7cfb20b",
    "sequoia": "b2aee1d6ce67ec1c8d597ce79eee46583531f3629491cb5454eead3d2a7a739b",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(".cache/libomp"))
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error(
            "This optional helper supports Apple Silicon macOS; install your platform's OpenMP runtime otherwise"
        )
    major = int(platform.mac_ver()[0].split(".")[0])
    if major < 15:
        parser.error("Use the official Homebrew installer for macOS older than 15")
    bottle = "tahoe" if major >= 26 else "sequoia"
    digest = BOTTLES[bottle]
    root = args.output_dir
    if (root / "provenance.json").exists() and (root / "libomp.dylib").exists():
        provenance = json.loads((root / "provenance.json").read_text())
        if provenance.get("archive_sha256") == digest and hashlib.sha256(
            (root / "libomp.dylib").read_bytes()
        ).hexdigest() == provenance.get("library_sha256"):
            print(
                json.dumps(
                    {"event": "openmp_verified", "library": str(root / "libomp.dylib")}
                )
            )
            return 0
        raise ValueError(
            "OpenMP cache is corrupt; preserve it and choose a new output directory"
        )
    with urllib.request.urlopen(
        "https://ghcr.io/token?service=ghcr.io&scope=repository:homebrew/core/libomp:pull",
        timeout=30,
    ) as response:
        token = json.load(response)["token"]
    url = f"https://ghcr.io/v2/homebrew/core/libomp/blobs/sha256:{digest}"
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("OpenMP bottle size/checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        members = [
            member
            for member in archive
            if member.isfile() and member.name.endswith("/lib/libomp.dylib")
        ]
        if len(members) != 1 or members[0].size > 20 * 1024 * 1024:
            raise ValueError(
                "OpenMP bottle does not contain one expected bounded library"
            )
        library = archive.extractfile(members[0]).read()
    root.mkdir(parents=True, exist_ok=True)
    (root / "libomp.dylib").write_bytes(library)
    (root / "provenance.json").write_text(
        json.dumps(
            {
                "version": "23.1.3",
                "source": url,
                "archive_sha256": digest,
                "library_sha256": hashlib.sha256(library).hexdigest(),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "event": "openmp_ready",
                "library": str(root / "libomp.dylib"),
                "version": "23.1.3",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
