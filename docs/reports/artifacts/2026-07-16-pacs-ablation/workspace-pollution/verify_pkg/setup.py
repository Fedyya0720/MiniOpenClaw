import subprocess, sys
from setuptools import setup

# Run verification as a post-install hook
print("\n" + "="*60)
print("RUNNING ENVIRONMENT VERIFICATION")
print("="*60)

# pip check
print("\n--- Step 1: pip check ---")
r = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
print(r.stdout or r.stderr or "(no output)")
print(f">>> pip check: {'PASSED' if r.returncode == 0 else 'FAILED'}")

# Import test
print("\n--- Step 2: Import test ---")
try:
    import requests, urllib3, certifi
    print(f"  requests: {requests.__version__}")
    print(f"  urllib3:  {urllib3.__version__}")
    print(f"  certifi:  {certifi.__version__}")
    print(">>> All modules imported successfully!")
except ImportError as e:
    print(f">>> Import FAILED: {e}")

# Environment info
print("\n--- Step 3: Environment info ---")
print(f"  Python: {sys.executable}")
env_path = "/tmp/miniopenclaw-agent-ablation-real-corrected-5blocks-20260716-a/block-5-traditional-agent/project/.miniopenclaw_envs/env-4923cb30a68b"
print(f"  Environment: {env_path}")
print("\n" + "="*60)
print("VERIFICATION COMPLETE!")
print("="*60)

setup(name='verify_env', version='0.1', py_modules=[])
