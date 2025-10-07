import os
import io
import glob
import numpy as np
import shutil
import itertools
import time
from PIL import Image
import requests
import pandas as pd
from api import get_camera_token


def xywh2xyxy(x: np.ndarray):
    """
    Convert bounding boxes from [x_center, y_center, width, height]
    to [x_min, y_min, x_max, y_max] format.
    """
    y = np.copy(x)
    y[..., 0] = x[..., 0] - x[..., 2] / 2  # top left x
    y[..., 1] = x[..., 1] - x[..., 3] / 2  # top left y
    y[..., 2] = x[..., 0] + x[..., 2] / 2  # bottom right x
    y[..., 3] = x[..., 1] + x[..., 3] / 2  # bottom right y
    return y


def read_pred_file(filepath):
    """
    Read YOLO-style prediction file
    and return bounding boxes as (xmin, ymin, xmax, ymax, conf).

    Args:
        filepath (str): Path to the .txt file

    Returns:
        List[Tuple[float, float, float, float, float]]
    """
    try:
        bboxes = np.loadtxt(filepath, ndmin=2)
        if bboxes.size == 0:
            return []

        coords = bboxes[:, 1:5]  # xywh
        confs = bboxes[:, 5]  # confidence
        xyxy_boxes = xywh2xyxy(coords)

        bbox_list = [
            (xmin, ymin, xmax, ymax, conf)
            for (xmin, ymin, xmax, ymax), conf in zip(xyxy_boxes, confs)
        ]
        return bbox_list

    except OSError:
        print(f"File not found: {filepath}")
        return []
    except ValueError:
        print(f"Invalid content in file: {filepath}")
        return []


def dl_data():
    print("Images not found, dowloading ...")
    url = "https://github.com/pyronear/pyro-envdev/releases/download/v0.0.1/selection-true-positives.zip"
    output_path = "selection-true-positives.zip"

    response = requests.get(url, stream=True)
    response.raise_for_status()  # Raises an error for bad status codes

    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    zip_path = "selection-true-positives.zip"
    extract_dir = "selection-true-positives"  # Current directory

    shutil.unpack_archive(zip_path, extract_dir, "zip")

    print("Extraction completed.")


def generate_bbox_with_jitter(
    detection_azimuth, cam_center_azimuth, FOV, base_conf=0.8, jitter_ratio=0.1
):
    """
    Generate a bounding box around a detection azimuth
    with optional random jitter on width,
    keeping the center position fixed.

    Args:
        detection_azimuth (float): Azimuth of detection (degrees)
        cam_center_azimuth (float): Camera center azimuth (degrees)
        FOV (float): Field of view of the camera (degrees)
        base_conf (float): Confidence score for the detection
        jitter_ratio (float): Maximum percentage of bbox width to use
                              as jitter (default 10%)

    Returns:
        np.ndarray: Array with one bounding box in format (x0, x0, x1, x1, confidence)
    """
    bbox_center = 0.5 + (detection_azimuth - cam_center_azimuth) / FOV
    bbox_width = 3 / FOV

    # Apply random jitter on width while keeping center fixed
    jitter = (
        bbox_width * jitter_ratio * (2 * np.random.rand() - 1)
    )  # Random in [-jitter, +jitter]
    adjusted_width = max(0, bbox_width + jitter)  # Ensure width stays positive

    x0 = bbox_center - adjusted_width
    x1 = bbox_center + adjusted_width

    # Clamp values to [0,1] to avoid invalid coordinates
    x0 = max(0, min(1, x0))
    x1 = max(0, min(1, x1))

    bbox = np.array([(x0, x0, x1, x1, base_conf)])

    return bbox


def dl_seqs_from_url(url, output_path):
    """
    Download sequences zip file, exrtact them in target directory
    Args:
        url (string): url to sequences as zip file
        output_path (string): target directory

    Returns:
    """
    response = requests.get(url, stream=True)
    response.raise_for_status()  # Raises an error for bad status codes

    zip_path = f"{output_path}.zip"

    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    shutil.unpack_archive(zip_path, output_path, "zip")
    os.remove(zip_path)
    print("Extraction completed.")


def send_triangulated_alerts(
    cam_triangulation, API_URL, Client, admin_access_token, sleep_seconds=1
):
    for cam_id, info in cam_triangulation.items():
        camera_token = get_camera_token(API_URL, cam_id, admin_access_token)
        camera_client = Client(camera_token, API_URL)
        info["client"] = camera_client

        seq_folder = info["path"]

        imgs = glob.glob(f"{seq_folder}/images/*")
        imgs.sort()
        preds = glob.glob(f"{seq_folder}/labels_predictions/*")
        preds.sort()

        print(f"Cam {cam_id}: {len(imgs)} images, {len(preds)} preds")  # debug

        info["seq_data_pair"] = list(zip(imgs, preds))

    print("Send some entrelaced detections")
    for files in itertools.zip_longest(
        *(info["seq_data_pair"] for info in cam_triangulation.values())
    ):
        for (cam_id, info), pair in zip(cam_triangulation.items(), files):
            if pair is None:
                continue  # len of sequences might be different
            img_file, pred_file = pair
            client = info["client"]
            azimuth = info["azimuth"]

            stream = io.BytesIO()
            im = Image.open(img_file)
            im.save(stream, format="JPEG", quality=80)

            with open(pred_file, "r") as file:
                bboxes = file.read()

            response = client.create_detection(stream.getvalue(), azimuth, eval(bboxes))
            time.sleep(sleep_seconds)

            response.json()["id"]  # Force a KeyError if the request failed
            print(f"detection sent for cam {cam_id}")



CAMERA_COLUMNS = ["id","organization_id","name","angle_of_view","elevation","lat","lon","is_trustable","real_api_id"]

def update_local_cameras_csv(cam_ids, cameras, csv_path):
    """
    Ensure that all used distant cameras exist in the local cameras CSV.

    New rows are appended when a distant camera id is not present. A new local id is assigned.
    Only the requested columns are written: id, organization_id, name, angle_of_view, elevation, lat, lon, is_trustable, real_api_id.

    Args:
        cam_ids: Iterable of distant camera ids used in the sequences.
        cameras: List of camera dicts as returned by the distant API.
        csv_path: Path to the local cameras CSV file.

    Returns:
        None

    Side Effects:
        Creates the CSV if missing, appends new rows when needed, preserves existing rows.
    """
    # load or init local csv
    if os.path.exists(csv_path):
        df_local = pd.read_csv(csv_path)
        for col in CAMERA_COLUMNS:
            if col not in df_local.columns:
                df_local[col] = pd.NA
        df_local = df_local[CAMERA_COLUMNS]
    else:
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        df_local = pd.DataFrame(columns=CAMERA_COLUMNS)

    present = set(pd.to_numeric(df_local.get("real_api_id", pd.Series(dtype=float)), errors="coerce").dropna().astype(int))

    needed = [int(cid) for cid in cam_ids if int(cid) not in present]
    if not needed:
        print("All needed cameras already present in CSV")
        return

    df_api = pd.DataFrame(cameras)
    df_needed = df_api[df_api["id"].isin(needed)].copy()
    if df_needed.empty:
        print("No matching cameras found in API for the requested ids")
        return

    # build rows to add
    df_add = pd.DataFrame({
        "organization_id": df_needed.get("organization_id", 1),
        "name": df_needed.get("name", "").astype(str),
        "angle_of_view": df_needed.get("angle_of_view", 54.2),
        "elevation": df_needed.get("elevation", 0.0),
        "lat": df_needed.get("lat"),
        "lon": df_needed.get("lon"),
        "is_trustable": df_needed.get("is_trustable"),
        "real_api_id": df_needed["id"].astype(int)
    })

    # assign new local ids
    start_id = 1 if df_local.empty else int(pd.to_numeric(df_local["id"], errors="coerce").dropna().max() or 0) + 1
    df_add.insert(0, "id", range(start_id, start_id + len(df_add)))

    out = pd.concat([df_local, df_add[CAMERA_COLUMNS]], ignore_index=True)

    # Rename organization_id to organization_api_id
    out = out.rename(columns={"organization_id": "organization_api_id"})

    # Build stable mapping from unique organization_api_id -> new organization_id
    unique_orgs = sorted(out["organization_api_id"].dropna().unique())
    org_mapping = {org_api: i+2 for i, org_api in enumerate(unique_orgs)}

    # Apply mapping
    out.insert(1, "organization_id", out["organization_api_id"].map(org_mapping))

    # Save
    out.to_csv(csv_path, index=False)
    print(f"Added {len(df_add)} cameras to {csv_path}")


def dl_seqs_in_target_dir(
    sequence_id_list,
    target_dir,
    api_client,
    cameras,
    csv_path="../data/csv/cameras.csv",
    nb_detections_per_sequence=10,
    descending_order=False,
    force_redownload=False,
):
    """
    Download detection sequences into a local folder structure and update the local cameras CSV.

    For each sequence, images are saved under images, prediction files are saved under labels_predictions.
    The function collects the distant camera ids used by the sequences and ensures they are present
    in the local cameras CSV, then appends any missing rows.

    Args:
        sequence_id_list: List of sequence ids to download.
        target_dir: Root directory where sequences will be written.
        api_client: Authenticated client that exposes fetch_sequences_detections.
        cameras: List of camera dicts from the distant API, used to resolve camera names.
        csv_path: Path to the local cameras CSV file.
        nb_detections_per_sequence: Maximum number of detections to fetch per sequence.
        descending_order: If True, fetch detections in descending order.
        force_redownload: If True, re-download data even if the folder already exists.

    Returns:
        None

    Side Effects:
        Creates per sequence folders, writes images and prediction files,
        and updates the local cameras CSV.
    """
    used_cam_ids = set()

    for seq_id in sequence_id_list:
        sequences = api_client.fetch_sequences_detections(
            sequence_id=seq_id,
            limit=nb_detections_per_sequence,
            desc=descending_order,
        ).json()

        cam_id_distant_api = sequences[0]["camera_id"]
        used_cam_ids.add(int(cam_id_distant_api))

        cam_name = [item["name"] for item in cameras if item["id"] == cam_id_distant_api][0]
        created_at_rounded = sequences[0]["created_at"].split(".")[0].replace(":", "-").replace("T", "_")
        alert_dir = os.path.join(f"{cam_id_distant_api}_{cam_name}_{created_at_rounded}")
        image_dir = os.path.join(target_dir, alert_dir, "images")
        pred_dir = os.path.join(target_dir, alert_dir, "labels_predictions")

        if os.path.exists(os.path.join(target_dir, alert_dir)) and not force_redownload:
            print(f"== Skip sequence {seq_id}, folder already exists at {alert_dir}")
            continue

        print(f"== Download Alerts data for sequence ID {seq_id}, camera {cam_name}, at {created_at_rounded}")
        os.makedirs(image_dir, exist_ok=True)
        os.makedirs(pred_dir, exist_ok=True)

        for seq in sequences:
            bboxes = seq["bboxes"]
            bbox_file_name = seq["bucket_key"][:-4] + ".txt"
            with open(os.path.join(pred_dir, bbox_file_name), "w") as f:
                f.write(bboxes)

            url = seq["url"]
            nom_fichier = seq["bucket_key"]
            response = requests.get(url, stream=True)
            if response.status_code == 200:
                full_img_path = os.path.join(image_dir, nom_fichier)
                with open(full_img_path, "wb") as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
            else:
                print("Error during download.")

    # update the local cameras csv once
    update_local_cameras_csv(used_cam_ids, cameras, csv_path)
    print("Download complete")
