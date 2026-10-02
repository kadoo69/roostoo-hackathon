"""CLI: run SCRIPT_FILE on the EC2 instance through Session Manager (bot.ec2_session).

Usage: python3 deploy/ssm_shell.py SCRIPT_FILE [TIMEOUT_S]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot.ec2_session import run_script  # noqa: E402

rc, out = run_script(Path(sys.argv[1]).read_text(), float(sys.argv[2]) if len(sys.argv) > 2 else 900)
print(out[-12000:])
sys.exit(rc)
