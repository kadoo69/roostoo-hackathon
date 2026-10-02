"""Run a bash script on the EC2 instance through an interactive Session Manager session.

Usage: python3 deploy/ssm_shell.py SCRIPT_FILE [TIMEOUT_S]; env EC2_INSTANCE, AWS_PROFILE (default hackathon).
The team role may start sessions but not `ssm:SendCommand`, so commands go through a session
(DECISIONS.md#ec2-cutover-2026-10-02). Needs the session-manager-plugin in ~/.local/ssm.
The script is base64-encoded, decoded on the instance into a temp file and run with bash, so the
keystrokes echoed by the terminal never contain its contents. Output lines are printed after
redacting every value from ~/roostoo-hackathon/.env.
"""
import base64
import json
import os
import pty
import re
import select
import sys
import time
import uuid

import boto3

IID = os.environ.get("EC2_INSTANCE", "i-015fad70d34b0b83d")
PROFILE = os.environ.get("AWS_PROFILE", "hackathon")
REGION = "ap-southeast-2"
PLUGIN = os.path.expanduser("~/.local/ssm/sessionmanager-bundle/bin/session-manager-plugin")

script = open(sys.argv[1]).read()
timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 900
secrets = []
envp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(envp):
    for line in open(envp):
        if "=" in line:
            v = line.split("=", 1)[1].strip().strip('"')
            if len(v) >= 8:
                secrets.append(v)


def redact(s: str) -> str:
    for v in secrets:
        s = s.replace(v, "***")
    return s


sess = boto3.Session(profile_name=PROFILE, region_name=REGION)
ssm = sess.client("ssm")
resp = ssm.start_session(Target=IID)
endpoint = f"https://ssm.{REGION}.amazonaws.com"
args = [PLUGIN, json.dumps(resp), REGION, "StartSession", PROFILE, json.dumps({"Target": IID}), endpoint]
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


read_until(r"[\$#] $", 60)
send("stty -echo; export HISTFILE=/dev/null; cd /tmp\n")
time.sleep(1)
chunks = [b64[i:i + 2000] for i in range(0, len(b64), 2000)]
send("rm -f /tmp/.job.b64\n")
for c in chunks:
    send(f"printf %s '{c}' >> /tmp/.job.b64\n")
    time.sleep(0.15)
send(f"base64 -d /tmp/.job.b64 > /tmp/.job.sh && rm -f /tmp/.job.b64 && bash /tmp/.job.sh 2>&1; rc=$?; rm -f /tmp/.job.sh; echo {marker} rc=$rc\n")
out = read_until(marker + r" rc=\d+", timeout)
send("exit\n")
time.sleep(1)
try:
    os.kill(pid, 15)
except OSError:
    pass
text = out.replace("\r", "")
start = text.find("bash /tmp/.job.sh")
text = text[text.find("\n", start) + 1:] if start >= 0 else text
print(redact(text)[-12000:])
m = re.search(marker + r" rc=(\d+)", out)
sys.exit(int(m.group(1)) if m else 124)
