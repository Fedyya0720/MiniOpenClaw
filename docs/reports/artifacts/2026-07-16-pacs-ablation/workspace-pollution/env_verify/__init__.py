"""Run environment verification."""
import subprocess, sys

def main():
    # pip check
    r = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True, text=True
    )
    print("=== pip check ===")
    if r.returncode == 0:
        print("No broken requirements found.")
    else:
        print(r.stdout.strip())
        print(r.stderr.strip())
    print(f"returncode: {r.returncode}")

    # imports
    print("\n=== import verification ===")
    import requests
    import urllib3
    import certifi
    print(f"requests version: {requests.__version__}")
    print(f"urllib3 version: {urllib3.__version__}")
    print(f"certifi version: {certifi.__version__}")
    print("All imports OK")
    return 0

if __name__ == "__main__":
    sys.exit(main())
