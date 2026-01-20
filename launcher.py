import subprocess
import os
import sys
import time

print("[LAUNCHER] Cleaning up existing processes...")
subprocess.run(["pkill", "-9", "-f", "api_bridge"], capture_output=True)

print("[LAUNCHER] Starting api_bridge:app via uvicorn...")
cmd = [
    sys.executable, "-u", "-m", "uvicorn", 
    "dashboard.api_bridge:app", 
    "--host", "127.0.0.1", 
    "--port", "8002",
    "--log-level", "debug"
]

proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

print(f"[LAUNCHER] PID: {proc.pid}. Waiting for logs...")

start_time = time.time()
while time.time() - start_time < 15:
    line = proc.stdout.readline()
    if line:
        print(f"[SERVER] {line.strip()}")
        if "Uvicorn running on" in line:
            print("[LAUNCHER] ✅ SUCCESS detected in logs!")
            break
    else:
        # Check if process died
        ret = proc.poll()
        if ret is not None:
            print(f"[LAUNCHER] ❌ Server DIED with code {ret}")
            break
        time.sleep(0.1)

print("[LAUNCHER] Trace complete. Shutting down test process...")
proc.terminate()
try:
    proc.wait(timeout=2)
except:
    proc.kill()
