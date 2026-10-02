"""Copy the live books' trade logs into the tracked `logs/` folder for the judges.

`live/` is git-ignored, and since 2026-10-02 12:36Z the live books run on EC2, so their logs live there.
This pulls `live/<book>/*.jsonl` (all but the 30-second cycle snapshots) and the FIFO trade CSVs (`bot.blotter --csv`) from the instance into
`logs/ec2/<book>/`, and copies the same books' logs written on the Mac before the cutover into
`logs/mac/<book>/`. Re-run before submitting and commit the result.
Usage: python3 deploy/export_logs.py     DECISIONS.md#submission-deliverables-2026-10-02
"""
from __future__ import annotations

import base64
import io
import shutil
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bot.ec2_session import run_script  # noqa: E402

BOOKS = ("competition", "competition_rehearsal")
KEEP = ("orders-", "signals-", "reconcile-", "errors-", "lifecycle-", "waiting-", "intents", "trades_")
REMOTE = f"""
cd /opt/roostoo-hackathon
sudo -u roostoo .venv/bin/python -m bot.blotter {' '.join(BOOKS)} --csv >/dev/null 2>&1 || true
cd live
echo LOGTAR_BEGIN
sudo tar czf - $(for b in {' '.join(BOOKS)}; do ls -d $b/*.jsonl $b/*.csv 2>/dev/null; done) | base64 -w0
echo
echo LOGTAR_END
"""


def kept(name: str) -> bool:
    return name.startswith(KEEP) and name.endswith((".jsonl", ".csv"))


def main() -> int:
    rc, out = run_script(REMOTE, timeout=600)
    if "LOGTAR_BEGIN" not in out or "LOGTAR_END" not in out:
        print(out[-2000:])
        return rc or 1
    blob = out.split("LOGTAR_BEGIN", 1)[1].split("LOGTAR_END", 1)[0]
    data = base64.b64decode("".join(blob.split()))
    dest = ROOT / "logs" / "ec2"
    shutil.rmtree(dest, ignore_errors=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if m.isfile() and kept(Path(m.name).name):
                target = dest / m.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(m).read())
                n += 1
    m_n = 0
    for b in BOOKS:
        src = ROOT / "live" / b
        if not src.exists():
            continue
        dst = ROOT / "logs" / "mac" / b
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file() and kept(f.name) and f.name.endswith(".jsonl"):
                shutil.copy2(f, dst / f.name)
                m_n += 1
    print(f"logs/ec2: {n} files, logs/mac: {m_n} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
