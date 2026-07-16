from setuptools import setup

# Run verification during install
import sys
import subprocess

print("=" * 60)
print("VERIFICATION - pip check")
print("=" * 60)

py = sys.executable
r = subprocess.run([py, "-m", "pip", "check"], capture_output=True, text=True)
print(r.stdout)
if r.stderr:
    print("STDERR:", r.stderr)
print("pip check returncode:", r.returncode)
print()

print("=" * 60)
print("VERIFICATION - Import check")
print("=" * 60)

try:
    import requests
    print(f"requests version: {requests.__version__}")
    import urllib3
    print(f"urllib3 version: {urllib3.__version__}")
    import certifi
    print(f"certifi version: {certifi.__version__}")
    print("All imports OK!")
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

print()
print("Environment path:", py)
print()

setup(
    name="verify-env",
    version="0.0.1",
    description="Temporary verification package",
)
