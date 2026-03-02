#  TODO REFACTOR : use the init scripts which are in the test_update_pi directory

#!/usr/bin/env python
import sys
import logging
import os
import glob
import itertools
import random
import io
import pandas as pd
import requests
from PIL import Image
from pyroclient import Client

# Import utility functions
from utils import (
    get_token,
    api_request,
    read_json_file,
    write_json_file,
    download_images_if_needed,
)

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")

# Base URL for Client initialization (like in notebook: "http://api:5050")
base_url = os.environ.get("API_URL")
# API URL with /api/v1 for direct API requests
api_url = base_url + "/api/v1"

superuser_login = os.environ.get("SUPERADMIN_LOGIN")
superuser_pwd = os.environ.get("SUPERADMIN_PWD")
slack_hook = os.environ.get("SLACK_HOOK")
credentials_path = "data/credentials.json"
credentials_path_etl = "data/credentials-wildfire.json"


superuser_auth = {
    "Authorization": f"Bearer {get_token(api_url, superuser_login, superuser_pwd)}",
    "Content-Type": "application/json",
}

sub_path = "_DEV"

users = pd.read_csv(f"data/csv/API_DATA{sub_path} - users.csv")
organizations = pd.read_csv(f"data/csv/API_DATA{sub_path} - organizations.csv")
cameras = pd.read_csv(f"data/csv/API_DATA{sub_path} - cameras.csv")
cameras = cameras.fillna("")
poses = pd.read_csv(f"data/csv/API_DATA{sub_path} - poses.csv")

# ============================================================================
# ORGAS CREATION
# ============================================================================

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

# ============================================================================
# USERS CREATION
# ============================================================================

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
data_wildfire = read_json_file(credentials_path_etl)

# ============================================================================
# CAMERAS CREATION
# ============================================================================

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
    logging.info(f"Caméra créé, id : {str(id)}")
    result = api_request("post", f"{api_url}/cameras/{id}/token", superuser_auth)

    camera_token = result["access_token"]
    logging.info(f"Token generated : {camera_token}")
    for i, key in enumerate(data):
        if data[key]["name"] == camera.name:
            data[key]["token"] = camera_token
    for i, key in enumerate(data_wildfire):
        if data_wildfire[key]["name"] == camera.name:
            data_wildfire[key]["token"] = camera_token

write_json_file(credentials_path, data)
write_json_file(credentials_path_etl, data_wildfire)

# ============================================================================
# POSES CREATION
# ============================================================================

logging.info("creating poses")
for pose in poses.itertuples(index=False):
    payload = {
        "camera_id": pose.camera_id,
        "azimuth": pose.azimuth,
        "patrol_id": pose.patrol_id,
    }
    api_request("post", f"{api_url}/poses/", superuser_auth, payload)


# ============================================================================
# CAMERA STATUS UPDATES AND POSE IMAGE UPLOADS
# ============================================================================

# Constants
BASE_DIRECTORY = "data"
SAMPLE_PATH = "last_image_cameras"
IMAGES_URL = "https://github.com/pyronear/pyro-envdev/releases/download/v0.0.1/last_image_cameras.zip"

# Predefined list of image filenames for pose images
# (to be filled with actual filenames)
POSE_IMAGE_FILES = [
    "11-20251001151013-d6de7b82.jpg",
    "17-20251001143249-dc04ad6f.jpg",
    "22-20251001150858-6578cf9e.jpg",
    "59-20251001151203-354621da.jpg",
    "69-20251003170645-721ec72e.jpg",
]

# Cameras to skip for pose images (one per organization)
# Format: {organization_id: camera_id_to_skip}
CAMERAS_TO_SKIP_POSE_IMAGES = {
    2: 8,  # Organization 2: skip camera 1 (videlles-01)
    3: 14,  # Organization 3: skip camera 9 (brison-01)
}

# Download images if needed
logging.info("Checking for image files...")
download_images_if_needed(BASE_DIRECTORY, SAMPLE_PATH, IMAGES_URL)

# Get all image files
image_dir = os.path.join(BASE_DIRECTORY, SAMPLE_PATH)
all_images = glob.glob(os.path.join(image_dir, "*.jpg"))

if not all_images:
    logging.warning(
        "No images found in directory, skipping camera and pose image updates"
    )
else:
    # Cycle images for camera last image updates
    images_cycle = itertools.cycle(all_images)

    # Prepare pose images
    pose_images_full_paths = [
        os.path.join(image_dir, fname)
        for fname in POSE_IMAGE_FILES
        if os.path.exists(os.path.join(image_dir, fname))
    ]

    if not pose_images_full_paths:
        logging.warning("No valid pose images found in predefined list")

    logging.info("Updating cameras (heartbeat, last image) and pose images...")

    # Create admin client once for all operations
    admin_token = superuser_auth["Authorization"].replace("Bearer ", "")
    admin_client = Client(admin_token, base_url)

    # Fetch all cameras using pyroclient
    cameras_response = admin_client.fetch_cameras().json()

    # Process each camera
    for camera_data in cameras_response:
        camera_id = camera_data["id"]
        camera_name = camera_data["name"]
        org_id = camera_data["organization_id"]

        logging.info(f"Processing camera {camera_name} (id: {camera_id})...")

        try:
            result = api_request(
                "post", f"{api_url}/cameras/{camera_id}/token", superuser_auth
            )
            camera_token = result["access_token"]

            camera_client = Client(camera_token, base_url)

            # Update heartbeat
            camera_client.heartbeat()
            logging.info("  ✓ Heartbeat updated")

            # Update camera last image
            img_file = next(images_cycle)
            stream = io.BytesIO()
            im = Image.open(img_file)
            im.save(stream, format="JPEG", quality=80)
            stream.seek(0)
            camera_client.update_last_image(stream.getvalue())
            logging.info("  ✓ Last image updated")

            # Fetch camera details including poses
            camera_details = requests.get(
                f"{api_url}/cameras/{camera_id}", headers=superuser_auth, timeout=10
            ).json()

            camera_poses = camera_details.get("poses", [])

            if not camera_poses:
                logging.info("  No poses for this camera")
            elif CAMERAS_TO_SKIP_POSE_IMAGES.get(org_id) == camera_id:
                logging.info(f"  Skipping pose images (org {org_id} skip rule)")
            elif not pose_images_full_paths:
                logging.info("  No pose images available")
            else:
                # Upload pose images
                num_poses = len(camera_poses)
                num_images = min(num_poses, len(pose_images_full_paths))
                selected_images = random.sample(pose_images_full_paths, num_images)

                logging.info(f"  Uploading {num_images} pose images...")
                for pose_data, image_path in zip(camera_poses, selected_images):
                    try:
                        with open(image_path, "rb") as f:
                            image_data = f.read()

                        # time.sleep(2)
                        admin_client.update_pose_image(pose_data["id"], image_data)
                        logging.info(
                            f"✓ Pose {pose_data['id']} (azimuth {pose_data['azimuth']})"
                        )
                    except Exception as e:
                        logging.error(f"    ✗ Pose {pose_data['id']}: {e}")

            logging.info(f"  Completed camera {camera_name}")

        except Exception as e:
            logging.error(f"  Error processing camera {camera_name}: {e}")
            continue

    logging.info("All camera and pose updates completed")

logging.info("Initialization script completed successfully")

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
