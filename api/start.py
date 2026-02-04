"""
Start both the UI server (port 8000) and API server (port 8001).
"""

import subprocess
import sys


def main():
    # Start UI server on port 8000
    ui_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"],
    )

    # Start API server on port 8001
    api_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:api_app", "--host", "0.0.0.0", "--port", "8001"],
    )

    try:
        ui_process.wait()
        api_process.wait()
    except KeyboardInterrupt:
        ui_process.terminate()
        api_process.terminate()


if __name__ == "__main__":
    main()
