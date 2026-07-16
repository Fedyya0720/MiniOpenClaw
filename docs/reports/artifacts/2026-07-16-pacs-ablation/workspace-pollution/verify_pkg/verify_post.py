"""Post-install verification script."""
import subprocess, sys, os

def main():
    python = sys.executable
    print("=" * 60)
    print("ENVIRONMENT VERIFICATION")
    print("=" * 60)
    
    # pip check
    r = subprocess.run([python, "-m", "pip", "check", "--progress-bar", "off"],
                       capture_output=True, text=True)
    print("\n--- pip check ---")
    print(r.stdout.strip())
    if r.stderr.strip():
        print("stderr:", r.stderr.strip())
    print("returncode:", r.returncode)
    
    # imports
    print("\n--- Import verification ---")
    code = """
import requests
print(f'requests OK: {requests.__version__}')
import urllib3
print(f'urllib3 OK: {urllib3.__version__}')
import certifi
print(f'certifi OK: {certifi.__version__}')
"""
    r2 = subprocess.run([python, "-c", code], capture_output=True, text=True)
    print(r2.stdout.strip())
    if r2.stderr.strip():
        print("stderr:", r2.stderr.strip())
    
    # write result file
    result_path = os.path.join(os.path.dirname(__file__), "..", "verify_result.txt")
    with open(os.path.abspath(result_path), "w") as f:
        f.write("=== pip check ===\n")
        f.write(r.stdout)
        f.write(f"returncode: {r.returncode}\n")
        f.write("=== imports ===\n")
        f.write(r2.stdout)

if __name__ == "__main__":
    main()
