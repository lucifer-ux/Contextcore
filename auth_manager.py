import subprocess
import threading
import uuid
import re
import json

auth_sessions = {}

def start_auth(storage_type):
    session_id = str(uuid.uuid4())

    process = subprocess.Popen(
        ["rclone", "authorize", storage_type, "--auth-no-open-browser"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    auth_sessions[session_id] = {
        "process": process,
        "status": "starting",
        "verification_url": None,
        "user_code": None,
        "token": None
    }

    threading.Thread(
        target=_monitor_process,
        args=(session_id,),
        daemon=True
    ).start()

    return session_id


def _monitor_process(session_id):
    process = auth_sessions[session_id]["process"]

    for line in process.stdout:
        line = line.strip()
        print("AUTH OUTPUT:", line)

        # Capture verification URL
        if "http" in line and "google" in line:
            auth_sessions[session_id]["verification_url"] = line
            auth_sessions[session_id]["status"] = "waiting_for_user"

        # Capture user code
        if re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}", line):
            auth_sessions[session_id]["user_code"] = line

        # Capture token JSON
        if line.startswith("{") and "access_token" in line:
            auth_sessions[session_id]["token"] = line
            auth_sessions[session_id]["status"] = "completed"

    process.wait()
