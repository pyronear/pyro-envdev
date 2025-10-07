###### TODO REFACTOR : use the init scripts which are in the test_update_pi directory

#!/usr/bin/env python

from typing import Any, Dict, Optional
import pandas as pd
import sys
import logging
import os
import requests
import json

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")


def get_token(api_url: str, login: str, pwd: str) -> str:
    response = requests.post(
        f"{api_url}/login/creds",
        data={"username": login, "password": pwd},
        timeout=5,
    )
    if response.status_code != 200:
        raise ValueError(response.json()["detail"])
    return response.json()["access_token"]


def api_request(
    method_type: str,
    route: str,
    headers=Dict[str, str],
    payload: Optional[Dict[str, Any]] = None,
):
    kwargs = {"json": payload} if isinstance(payload, dict) else {}

    response = getattr(requests, method_type)(route, headers=headers, **kwargs)
    try:
        detail = response.json()
    except (requests.exceptions.JSONDecodeError, KeyError):
        detail = response.text
    assert response.status_code // 100 == 2, print(detail)
    return response.json()


# Function to read JSON data from a file
def read_json_file(file_path):
    with open(file_path, "r") as file:
        return json.load(file)


# Function to write JSON data to a file
def write_json_file(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)


api_url = os.environ.get("API_URL") + "/api/v1"
superuser_login = os.environ.get("SUPERADMIN_LOGIN")
superuser_pwd = os.environ.get("SUPERADMIN_PWD")
slack_hook = os.environ.get("SLACK_HOOK")

superuser_auth = {
    "Authorization": f"Bearer {get_token(api_url, superuser_login, superuser_pwd)}",
    "Content-Type": "application/json",
}


users = pd.read_csv(f"data/csv/users.csv")
organizations = pd.read_csv(f"data/csv/organizations.csv")
cameras = pd.read_csv(f"data/csv/cameras.csv")
cameras = cameras.fillna("")

for orga in organizations.itertuples(index=False):
    logging.info(f"saving orga : {orga.name}")
    payload = {"name": orga.name}
    api_request("post", f"{api_url}/organizations/", superuser_auth, payload)

    # ACTIVATE SLACK NOTIFICATION
    if slack_hook:
        logging.info("Notifications slack activés")
        payload = {"slack_hook": slack_hook}
        result = api_request(
            "patch",
            f"{api_url}/organizations/slack-hook/{orga.id}",
            superuser_auth,
            payload,
        )


for user in users.itertuples(index=False):
    logging.info(f"saving user : {user.login}")
    payload = {
        "organization_id": user.organization_id,
        "password": user.password,
        "login": user.login,
        "role": user.role,
    }
    api_request("post", f"{api_url}/users/", superuser_auth, payload)


for camera in cameras.itertuples(index=False):
    logging.info(f"saving camera : {camera.name}")
    payload = {
        "organization_id": camera.organization_id,
        "name": camera.name,
        "angle_of_view": camera.angle_of_view,
        "elevation": camera.elevation,
        "lat": camera.lat,
        "lon": camera.lon,
        "is_trustable": camera.is_trustable,
    }
    id = api_request("post", f"{api_url}/cameras/", superuser_auth, payload)["id"]
    logging.info(f"Camera created, id : {str(id)}")
    result = api_request("post", f"{api_url}/cameras/{id}/token", superuser_auth)
