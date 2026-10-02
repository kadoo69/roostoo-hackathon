"""Refresh the `hackathon` AWS profile from the portal's 'Option 2' block on the clipboard.

In the AWS access portal, open the account, choose 'Access keys', copy the whole 'Option 2' block
(the [..._HackathonPermissionSet] profile with three keys), then run: python3 deploy/aws_creds.py
Writes ~/.aws/credentials (mode 600) and checks the identity. Nothing is printed except the role.
DECISIONS.md#ec2-cutover-2026-10-02
"""
import configparser
import os
import re
import subprocess
import sys

text = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout if len(sys.argv) < 2 else open(sys.argv[1]).read()
vals = {k: re.search(rf"{k}\s*=\s*(\S+)", text) for k in ("aws_access_key_id", "aws_secret_access_key", "aws_session_token")}
if not all(vals.values()):
    sys.exit("clipboard does not hold the 'Option 2' block (aws_access_key_id, aws_secret_access_key, aws_session_token)")
path = os.path.expanduser("~/.aws/credentials")
os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
cfg = configparser.ConfigParser()
cfg.read(path)
cfg["hackathon"] = {k: m.group(1) for k, m in vals.items()}
with open(path, "w") as fh:
    cfg.write(fh)
os.chmod(path, 0o600)
import boto3  # noqa: E402

arn = boto3.Session(profile_name="hackathon", region_name="ap-southeast-2").client("sts").get_caller_identity()["Arn"]
print("ok:", arn.split("/")[1])
