import subprocess, sys, os

# 这个脚本会在安装时由 pip 以 setup.py 方式执行
# 我们用它来验证环境

env_python = sys.executable

def run_checks():
    results = {}
    
    # pip check
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "check", "--progress-bar", "off"],
            capture_output=True, text=True, timeout=30
        )
        results["pip_check"] = {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()
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
    
    return results

def main():
    results = run_checks()
    import json
    report_path = os.path.join(os.path.dirname(__file__), "verify_results.json")
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print("=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)
    for k, v in results.items():
        print(f"  {k}: {v}")
    print("=" * 60)

if __name__ == "__main__":
    main()
