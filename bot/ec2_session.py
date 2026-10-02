"""Run a bash script on the EC2 instance through an interactive Session Manager session.

The team role may start sessions but not `ssm:SendCommand`, so commands go through a session driven
by the session-manager-plugin (unpacked without sudo in ~/.local/ssm). The script is base64-encoded,
decoded on the instance into a temp file and run with bash, so the echoed keystrokes never contain its
contents; output is returned after redacting every value in the repo's .env.
DECISIONS.md#ec2-cutover-2026-10-02
"""
from __future__ import annotations

import base64
import json
import os
import pty
import re
import select
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IID = os.environ.get("EC2_INSTANCE", "i-015fad70d34b0b83d")
REGION = os.environ.get("EC2_REGION", "ap-southeast-2")
PROFILE = os.environ.get("AWS_PROFILE", "hackathon")
PLUGIN = os.path.expanduser("~/.local/ssm/sessionmanager-bundle/bin/session-manager-plugin")


def _secrets() -> list[str]:
    out = []
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line:
                v = line.split("=", 1)[1].strip().strip('"')
                if len(v) >= 8:
                    out.append(v)
    return out


def redact(s: str) -> str:
    for v in _secrets():
        s = s.replace(v, "***")
    return s


def run_script(script: str, timeout: float = 900) -> tuple[int, str]:
    """Return (exit code, redacted output) of `script` run with bash on the instance; 124 on timeout."""
    import boto3
    sess = boto3.Session(profile_name=PROFILE, region_name=REGION)
    resp = sess.client("ssm").start_session(Target=IID)
    args = [PLUGIN, json.dumps(resp), REGION, "StartSession", PROFILE, json.dumps({"Target": IID}),
            f"https://ssm.{REGION}.amazonaws.com"]
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(PLUGIN, args)
    marker = "END_" + uuid.uuid4().hex[:12]
    b64 = base64.b64encode(script.encode()).decode()

    def send(text: str) -> None:
        os.write(fd, text.encode())

    def read_until(pattern: str, limit: float) -> str:
        buf, t0 = "", time.time()
        while time.time() - t0 < limit:
            r, _, _ = select.select([fd], [], [], 1.0)
            if r:
                try:
                    chunk = os.read(fd, 65536).decode(errors="replace")
                except OSError:
                    break
                buf += chunk
                if re.search(pattern, buf):
                    return buf
        return buf

    try:
        read_until(r"[\$#] $", 60)
        send("stty -echo; export HISTFILE=/dev/null; cd /tmp\n")
        time.sleep(1)
        job = f"/tmp/.job{marker}"
        send(f"rm -f {job}.b64\n")
        for i in range(0, len(b64), 2000):
            send(f"printf %s '{b64[i:i + 2000]}' >> {job}.b64\n")
            time.sleep(0.15)
        send(f"base64 -d {job}.b64 > {job}.sh && rm -f {job}.b64 && bash {job}.sh 2>&1; rc=$?; rm -f {job}.sh; "
             f"echo {marker} rc=$rc\n")
        out = read_until(marker + r" rc=\d+", timeout)
        send("exit\n")
        time.sleep(1)
    finally:
        try:
            os.kill(pid, 15)
            os.waitpid(pid, 0)
        except OSError:
            pass
    text = out.replace("\r", "")
    start = text.find(f"bash {job}.sh")
    text = text[text.find("\n", start) + 1:] if start >= 0 else text
    m = re.search(marker + r" rc=(\d+)", out)
    return (int(m.group(1)) if m else 124), redact(text.split(marker)[0])
