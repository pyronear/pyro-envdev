import numpy as np
import shutil
import requests


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
