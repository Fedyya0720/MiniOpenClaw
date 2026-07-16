#!/usr/bin/env python3
"""Install dependencies with progress bar disabled."""
import subprocess
import sys

env_python = sys.argv[1]
packages = ["requests==2.25.0", "urllib3==1.26.20", "certifi==2023.11.17"]

cmd = [env_python, "-m", "pip", "install", "--progress-bar", "off"] + packages
result = subprocess.run(cmd, capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
