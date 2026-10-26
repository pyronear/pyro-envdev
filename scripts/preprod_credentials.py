"""Fill the camera tokens of a credentials file from a remote alert API.

    python scripts/preprod_credentials.py \\
        data/credentials-preprod.template.json data/credentials-preprod.json

Logs in with DISTANT_API_URL, DISTANT_ALERT_API_LOGIN and
DISTANT_ALERT_API_PASSWORD from .env (an admin account), checks that the camera
`id` of each entry of the template has its `name` on that API, asks a token for
it and writes the output file, which is gitignored. Same flow as the engine role of pi-manager-template.
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
    with urllib.request.urlopen(
        f"{api_url}/api/v1/login/creds", data=login, timeout=10
    ) as resp:
        headers = {"Authorization": f"Bearer {json.load(resp)['access_token']}"}

    template, output = Path(sys.argv[1]), Path(sys.argv[2])
    cameras = json.loads(template.read_text())
    # Check every camera before asking any token: an id names another camera on the
    # wrong API, and its token would send fake alerts there.
    for key, camera in cameras.items():
        request = urllib.request.Request(
            f"{api_url}/api/v1/cameras/{camera['id']}", headers=headers
        )
        with urllib.request.urlopen(request, timeout=10) as resp:
            name = json.load(resp)["name"]
        if name != camera["name"]:
            sys.exit(
                f"{key}: camera {camera['id']} of {api_url} is {name!r}, "
                f"expected {camera['name']!r}"
            )
    for key, camera in cameras.items():
        request = urllib.request.Request(
            f"{api_url}/api/v1/cameras/{camera['id']}/token",
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=10) as resp:
            camera["token"] = json.load(resp)["access_token"]
        print(f"{key}: token written for camera {camera['id']} ({camera['name']})")
    # Holds camera tokens: owner-only from creation, fchmod narrows an existing file.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(cameras, indent=4) + "\n")


if __name__ == "__main__":
    main()
