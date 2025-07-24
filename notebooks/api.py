# Copyright (C) 2020-2025, Pyronear.

# This program is licensed under the Apache License 2.0.
# See LICENSE or go to <https://www.apache.org/licenses/LICENSE-2.0>
# for full license details.

from urllib.parse import urljoin

import requests

__all__ = ["get_token", "get_camera_token"]


def get_token(API_URL, login: str, passwrd: str) -> str:
    """Authenticate with API and return access token"""
    response = requests.post(
        urljoin(API_URL, "/api/v1/login/creds"),
        data={"username": login, "password": passwrd},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_camera_token(API_URL, camera_id: int, access_token: str) -> str:
    """Retrieve the streaming token for a specific camera"""
    headers = {"Authorization": f"Bearer {access_token}", "accept": "application/json"}
    response = requests.post(
        urljoin(API_URL, f"/api/v1/cameras/{camera_id}/token"),
        headers=headers,
        timeout=5,
    )
    response.raise_for_status()
    return response.json()["access_token"]
