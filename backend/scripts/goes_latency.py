"""Print how late the newest GOES-19 FDCC files reach S3.  Usage: python -m scripts.goes_latency [N]"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingest.goes import latency_record, newest_files  # noqa: E402


def main(argv: list[str]) -> int:
    n = int(argv[1]) if len(argv) > 1 else 6
    try:
        files = newest_files(n)
    except RuntimeError as e:
        print(f"error: {e}")
        return 1
    now = datetime.now(timezone.utc)
    recs = [latency_record(f, now) for f in files]
    print(f"{'scan end (UTC)':<22}{'on S3 (UTC)':<22}{'delay (min)':>12}")
    for r in recs:
        print(f"{r['scan_end']:<22}{r['s3_last_modified']:<22}{r['scan_end_to_s3_min']:>12.1f}")
    d = [r["scan_end_to_s3_min"] for r in recs]
    if d:
        print(f"\n{len(d)} files: min {min(d):.1f}, median {sorted(d)[len(d)//2]:.1f}, max {max(d):.1f} min after scan end")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
