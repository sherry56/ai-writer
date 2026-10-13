"""Export the current local AI-writer data for one-time Cloudflare seeding."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from web.cloudflare_state import create_state_archive

OUTPUT = ROOT / "cloudflare-state.tar.gz"


def main() -> None:
    archive = create_state_archive(ROOT)
    OUTPUT.write_bytes(archive)
    print(f"Wrote private Cloudflare state archive ({len(archive):,} bytes).")
    print("The archive excludes .env and config/models.json; keep it out of Git and delete it after seeding.")


if __name__ == "__main__":
    main()
