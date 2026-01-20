import os
import subprocess
import signal

def super_cleanup():
    print("Super Cleanup Initializing...")
    # 1. Kill by port
    for port in [8000, 8001, 8002, 8003, 8005]:
        try:
            cmd = f"lsof -t -i :{port}"
            pids = subprocess.check_output(cmd, shell=True).decode().strip().split("\n")
            for pid in pids:
                if pid:
                    print(f"Killing PID {pid} on port {port}")
                    os.kill(int(pid), signal.SIGKILL)
        except:
            pass

    # 2. Kill by name
    try:
        cmd = "ps aux | grep -Ei 'python|uvicorn|hardened_run' | grep -v grep | awk '{print $2}'"
        pids = subprocess.check_output(cmd, shell=True).decode().strip().split("\n")
        for pid in pids:
            if pid:
                print(f"Killing PID {pid} (process name match)")
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except:
                    pass
    except:
        pass
    print("Cleanup Finished.")

if __name__ == "__main__":
    super_cleanup()
