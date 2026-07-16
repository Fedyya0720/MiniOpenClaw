#!/usr/bin/env python3
"""验证环境：pip check + 导入关键包"""
import subprocess
import sys

# 1. pip check
print("=" * 60)
print("1. Running pip check...")
print("=" * 60)
result = subprocess.run(
    [sys.executable, "-m", "pip", "check"],
    capture_output=True, text=True
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
print(f"Exit code: {result.returncode}")

# 2. 导入验证
print()
print("=" * 60)
print("2. Import verification...")
print("=" * 60)

packages = ["requests", "urllib3", "certifi"]
for pkg in packages:
    try:
        mod = __import__(pkg)
        version = getattr(mod, "__version__", "unknown")
        print(f"  ✓ {pkg} == {version}")
    except ImportError as e:
        print(f"  ✗ {pkg} FAILED to import: {e}")
        sys.exit(1)

# 3. Summary
print()
print("=" * 60)
print("3. Summary")
print("=" * 60)
print(f"  Python: {sys.executable}")
print(f"  All imports successful! ✓")
pip_ok = "✓ No conflicts" if result.returncode == 0 else "✗ Conflicts found"
print(f"  pip check: {pip_ok}")
