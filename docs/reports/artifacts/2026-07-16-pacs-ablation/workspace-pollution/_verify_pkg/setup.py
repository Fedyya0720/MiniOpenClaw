import sys, subprocess, os

# Run pip check
print("=" * 60)
print("RUNNING: pip check")
print("=" * 60)
r = subprocess.run(
    [sys.executable, '-m', 'pip', 'check'],
    capture_output=True, text=True, timeout=30
)
print(r.stdout, end="")
if r.stderr:
    print("STDERR:", r.stderr)
print("RC:", r.returncode)
pip_ok = r.returncode == 0

# Verify imports
print("\n" + "=" * 60)
print("RUNNING: import verification")
print("=" * 60)
r2 = subprocess.run(
    [sys.executable, '-c',
     'import requests; import urllib3; import certifi; '
     'print(f"requests: {requests.__version__}"); '
     'print(f"urllib3: {urllib3.__version__}"); '
     'print(f"certifi: {certifi.__version__}"); '
     'print("All imports OK!")'],
    capture_output=True, text=True, timeout=30
)
print(r2.stdout, end="")
if r2.stderr:
    print("STDERR:", r2.stderr)
print("RC:", r2.returncode)
imp_ok = r2.returncode == 0

# Print env path
env_python = sys.executable
env_base = os.path.dirname(os.path.dirname(env_python))
print(f"\nEnvironment path: {env_base}")

# Summary
print("\n" + "=" * 60)
print("VERIFICATION SUMMARY")
print("=" * 60)
print(f"pip check: {'PASS' if pip_ok else 'FAIL'}")
print(f"Imports:   {'PASS' if imp_ok else 'FAIL'}")
print("=" * 60)

if not (pip_ok and imp_ok):
    sys.exit(1)

from setuptools import setup
setup(name='verify-pkg', version='0.0.1', py_modules=[])
