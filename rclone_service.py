import requests

RCLONE_URL = "http://127.0.0.1:5572/"


def create_remote(storage_type, remote_name):
    payload = {
        "name": remote_name,
        "type": storage_type,
        "parameters": {
            "config_is_local": "false",
            "token": ""
        }
    }

    response = requests.post(
        f"{RCLONE_URL}/config/create",
        json=payload
    )

    print("RCLONE STATUS:", response.status_code)
    print("RCLONE RAW:", response.text)

    return {
        "status_code": response.status_code,
        "raw": response.text
    }



def check_remote(remote_name):
    response = requests.post(f"{RCLONE_URL}/config/dump").json()
    if remote_name in response and "token" in response[remote_name]:
        return True
    return False


def start_copy(remote_name, local_path):
    payload = {
        "srcFs": f"{remote_name}:",
        "dstFs": local_path,
        "_async": True
    }

    return requests.post(
        f"{RCLONE_URL}/sync/copy",
        json=payload
    ).json()


def get_job_status(job_id):
    return requests.post(
        f"{RCLONE_URL}/job/status",
        json={"jobid": job_id}
    ).json()
