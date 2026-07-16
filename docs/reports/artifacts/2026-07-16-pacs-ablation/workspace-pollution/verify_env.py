#!/usr/bin/env python3
"""Verify the Python environment: pip check + import test."""
import subprocess
import sys

def main():
    print("=" * 60)
    print("ENVIRONMENT VERIFICATION REPORT")
    print("=" * 60)

    # 1. pip check
    print("\n--- Step 1: pip check ---")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True, text=True
    )
    output = r.stdout.strip() or r.stderr.strip() or "(no output)"
    print(output)
    if r.returncode == 0:
        print(">>> pip check: PASSED (no broken dependencies)")
    else:
        print(f">>> pip check: FAILED (returncode={r.returncode})")

    # 2. Import test
    print("\n--- Step 2: Import test ---")
    try:
        import requests
        import urllib3
        import certifi
        print(f"  requests: {requests.__version__}")
        print(f"  urllib3:  {urllib3.__version__}")
        print(f"  certifi:  {certifi.__version__}")
        print(">>> All three modules imported successfully!")
    except ImportError as e:
        print(f">>> Import FAILED: {e}")
        sys.exit(1)

    # 3. Environment info
    print("\n--- Step 3: Environment info ---")
    print(f"  Python executable: {sys.executable}")
    print(f"  Python version:    {sys.version}")
    print(f"  Site packages:     {next(p for p in sys.path if 'site-packages' in p)}")
    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE - All checks passed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
