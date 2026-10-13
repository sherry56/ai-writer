"""Upload the private first-run state archive to the Cloudflare Worker once."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "cloudflare-state.tar.gz"
SECRETS = ROOT / ".cloudflare-secrets.json"
URL = "https://writer.huibara.cn/_ops/seed-state"


def main() -> None:
    if not ARCHIVE.is_file() or not SECRETS.is_file():
        raise SystemExit("Run export_cloudflare_state.py and prepare_cloudflare_secrets.py first.")
    token = json.loads(SECRETS.read_text(encoding="utf-8"))["STATE_SEED_TOKEN"]
    request = urllib.request.Request(
        URL,
        data=ARCHIVE.read_bytes(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/gzip"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    if status == 201:
        print("Initial Cloudflare state archive uploaded.")
    elif status == 409:
        raise SystemExit("Cloudflare state already exists; refusing to overwrite it.")
    else:
        raise SystemExit(f"Cloudflare state upload failed with HTTP {status}.")


if __name__ == "__main__":
    main()
