# Copyright (C) 2020-2026, Pyronear.

# This program is licensed under the Apache License 2.0.
# See LICENSE or go to <https://www.apache.org/licenses/LICENSE-2.0>
# for full license details.

"""
Utility functions for initialization script.
Provides helper functions for API communication, file I/O, and image management.
"""

from typing import Any, Dict, Optional
import os
import io
import json
import logging
import zipfile
import requests


def get_token(api_url: str, login: str, pwd: str) -> str:
    """
    Authenticate with API and return access token.

    Args:
        api_url: Base API URL (e.g., "http://api:5050/api/v1")
        login: Username
        pwd: Password

    Returns:
        Access token string
    """
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
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]] = None,
):
    """
    Make a generic API request.

    Args:
        method_type: HTTP method (get, post, patch, delete)
        route: Full API route URL
        headers: Request headers including authorization
        payload: Optional request payload

    Returns:
        JSON response data
    """
    kwargs = {"json": payload} if isinstance(payload, dict) else {}

    response = getattr(requests, method_type)(route, headers=headers, **kwargs)
    try:
        detail = response.json()
    except (requests.exceptions.JSONDecodeError, KeyError):
        detail = response.text
    assert response.status_code // 100 == 2, print(detail)
    return response.json()


def read_json_file(file_path: str) -> Dict[str, Any]:
    """
    Read JSON data from a file.

    Args:
        file_path: Path to JSON file

    Returns:
        Parsed JSON data as dictionary
    """
    with open(file_path, "r") as file:
        return json.load(file)


def write_json_file(file_path: str, data: Dict[str, Any]) -> None:
    """
    Write JSON data to a file.

    Args:
        file_path: Path to output file
        data: Data to write as JSON
    """
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)


def download_images_if_needed(base_directory: str, sample_path: str, url: str) -> None:
    """
    Download and extract images if directory doesn't exist.

    Args:
        base_directory: Base directory for images (e.g., "data")
        sample_path: Subdirectory name (e.g., "last_image_cameras")
        url: URL to download zip file from
    """
    full_path = os.path.join(base_directory, sample_path)
    if not os.path.isdir(full_path):
        logging.info(f"Images not found at {full_path}, downloading...")

        # Download the zip file
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # Create parent directory if it doesn't exist
        os.makedirs(base_directory, exist_ok=True)

        # Extract the zip file
        zip_content = zipfile.ZipFile(io.BytesIO(response.content))
        zip_content.extractall(base_directory)

        logging.info(f"Images downloaded and extracted to {full_path}")
    else:
        logging.info(f"Directory {sample_path} exists, skipping download")
