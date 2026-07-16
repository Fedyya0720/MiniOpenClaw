from setuptools import setup
import subprocess, sys, json, os

results = {}

# pip check
try:
    r = subprocess.run(
        [sys.executable, "-m", "pip", "check", "--progress-bar", "off"],
        capture_output=True, text=True, timeout=30
    )
    results["pip_check"] = {
        "returncode": r.returncode,
        "stdout": r.stdout.strip(),
        "stderr": r.stderr.strip()
    }
except Exception as e:
    results["pip_check"] = {"error": str(e)}

# import checks
for mod in ["demo_core", "demo_plugin", "demo_addon"]:
    try:
        __import__(mod)
        results[f"import_{mod}"] = "OK"
    except Exception as e:
        results[f"import_{mod}"] = f"FAILED: {e}"

# Save results
results_path = os.path.join(os.path.dirname(__file__), "..", "verify_results.json")
with open(results_path, "w") as f:
    json.dump(results, f, indent=2)

print("=== VERIFICATION ===")
for k, v in results.items():
    print(f"  {k}: {v}")
print("=== END VERIFICATION ===")

setup(
    name="verify-dummy",
    version="0.0.1",
    py_modules=[],
)
