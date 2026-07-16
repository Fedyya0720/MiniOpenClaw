#!/usr/bin/env python3
"""Run pip check and import verification."""
import subprocess
import sys
import os

env_python = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '.miniopenclaw_envs', 'env-7efd098929b2', 'bin', 'python'
)

# Run pip check
print("=" * 60)
print("STEP 1: pip check")
print("=" * 60)
result = subprocess.run(
    [env_python, '-m', 'pip', 'check'],
    capture_output=True, text=True, timeout=30
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("RC:", result.returncode)

# Run import verification
print("\n" + "=" * 60)
print("STEP 2: Import verification")
print("=" * 60)
import_result = subprocess.run(
    [env_python, '-c', 
     'import requests; import urllib3; import certifi; '
     'print(f"requests: {requests.__version__}"); '
     'print(f"urllib3: {urllib3.__version__}"); '
     'print(f"certifi: {certifi.__version__}"); '
     'print("All imports OK!")'],
    capture_output=True, text=True, timeout=30
)
print("STDOUT:", import_result.stdout)
print("STDERR:", import_result.stderr)
print("RC:", import_result.returncode)

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
pip_check_ok = result.returncode == 0
import_ok = import_result.returncode == 0
print(f"pip check: {'PASS' if pip_check_ok else 'FAIL'}")
print(f"Imports:   {'PASS' if import_ok else 'FAIL'}")

# Print env path
print(f"\nEnvironment path: {os.path.dirname(os.path.dirname(env_python))}")
