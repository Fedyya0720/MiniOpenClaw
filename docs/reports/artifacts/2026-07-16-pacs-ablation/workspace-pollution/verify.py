#!/usr/bin/env python3
import subprocess, sys

# Run pip check
result = subprocess.run(
    [sys.executable, "-m", "pip", "check"],
    capture_output=True, text=True
)
print("=== pip check ===")
print(result.stdout)
if result.stderr:
    print("stderr:", result.stderr)
print("pip check exit code:", result.returncode)

# Verify imports
print("\n=== Import verification ===")
try:
    import requests
    import urllib3
    import certifi
    print("requests:", requests.__version__)
    print("urllib3:", urllib3.__version__)
    print("certifi:", certifi.__version__)
    print("All imports successful!")
except Exception as e:
    print("Import failed:", e)
    sys.exit(1)
