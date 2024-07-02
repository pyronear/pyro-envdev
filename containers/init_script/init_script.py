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
credentials_path = "data/credentials.json"

print(api_url)
superuser_auth = {
    "Authorization": f"Bearer {get_token(api_url, superuser_login, superuser_pwd)}",
    "Content-Type": "application/json",
}

sub_path = "_DEV"

users = pd.read_csv(f"data/csv/API_DATA{sub_path} - users.csv")
organizations = pd.read_csv(f"data/csv/API_DATA{sub_path} - organizations.csv")
cameras = pd.read_csv(f"data/csv/API_DATA{sub_path} - cameras.csv")
cameras = cameras.fillna("")

for orga in organizations.itertuples(index=False):
    logging.info(f"saving orga : {orga.name}")
    payload = {"name": orga.name, "type": orga.type}
    api_request("post", f"{api_url}/organizations/", superuser_auth, payload)


for user in users.itertuples(index=False):
    logging.info(f"saving user : {user.login}")
    payload = {
        "organization_id": user.organization_id,
        "password": user.password,
        "login": user.login,
        "role": user.role,
    }
    api_request("post", f"{api_url}/users/", superuser_auth, payload)


data = read_json_file(credentials_path)

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
        "last_active_at": camera.last_active_at,
    }
    id = api_request("post", f"{api_url}/cameras/", superuser_auth, payload)["id"]
    result = api_request("post", f"{api_url}/cameras/{id}/token", superuser_auth)

    camera_token = result["access_token"]
    logging.info(f"Token generated : {camera_token}")
    for i, key in enumerate(data):
        if data[key]["name"] == camera.name:
            data[key]["token"] = camera_token

write_json_file(credentials_path, data)

# Load environment variables from .env file
# load_dotenv()

# Get S3 endpoint URL and credentials from environment variables
# s3_endpoint_url = os.getenv("S3_ENDPOINT_URL")
# s3_access_key = os.getenv("S3_ACCESS_KEY")
# s3_secret_key = os.getenv("S3_SECRET_KEY")
# s3_region = os.getenv("S3_REGION")
# bucket_name = os.getenv("BUCKET_NAME")

# Create a Boto3 client for the S3 service
# s3_client = boto3.client(
#    "s3",
#    endpoint_url=s3_endpoint_url,
#    aws_access_key_id=s3_access_key,
#    aws_secret_access_key=s3_secret_key,
#    region_name=s3_region,
# )

# Create the bucket
# try:
#    s3_client.create_bucket(Bucket=bucket_name)
#    print(f"Bucket '{bucket_name}' created successfully.")
# except Exception as e:
#    print(f"Error creating bucket '{bucket_name}': {e}")
