"""Fill the camera tokens of a credentials file from a remote alert API.

    python scripts/preprod_credentials.py data/credentials-preprod.json

Logs in with DISTANT_API_URL, DISTANT_ALERT_API_LOGIN and
DISTANT_ALERT_API_PASSWORD from .env (an admin account), asks a token for the
camera `id` of each entry and writes it back in place. Same flow as the engine
role of pi-manager-template. Do not commit the resulting tokens.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def load_env(path=".env"):
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main():
    load_env()
    api_url = os.environ.get("DISTANT_API_URL", "").rstrip("/")
    if not api_url:
        sys.exit("DISTANT_API_URL is not set in .env")
    login = urllib.parse.urlencode(
        {
            "username": os.environ["DISTANT_ALERT_API_LOGIN"],
            "password": os.environ["DISTANT_ALERT_API_PASSWORD"],
        }
    ).encode()
    with urllib.request.urlopen(f"{api_url}/api/v1/login/creds", data=login) as resp:
        headers = {"Authorization": f"Bearer {json.load(resp)['access_token']}"}

    path = Path(sys.argv[1])
    cameras = json.loads(path.read_text())
    for key, camera in cameras.items():
        request = urllib.request.Request(
            f"{api_url}/api/v1/cameras/{camera['id']}/token",
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(request) as resp:
            camera["token"] = json.load(resp)["access_token"]
        print(f"{key}: token written for camera {camera['id']} ({camera['name']})")
    path.write_text(json.dumps(cameras, indent=4) + "\n")


if __name__ == "__main__":
    main()
