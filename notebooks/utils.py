import numpy as np

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
import numpy as np

def xywh2xyxy(x: np.ndarray):
    y = np.copy(x)
    y[..., 0] = x[..., 0] - x[..., 2] / 2
    y[..., 1] = x[..., 1] - x[..., 3] / 2
    y[..., 2] = x[..., 0] + x[..., 2] / 2
    y[..., 3] = x[..., 1] + x[..., 3] / 2
    return y

def read_pred_file(filepath):
    """
    Read YOLO-style prediction file and return bounding boxes as (xmin, ymin, xmax, ymax, conf).

    Args:
        filepath (str): Path to the .txt file

    Returns:
        List[Tuple[float, float, float, float, float]]
    """
    try:
        bboxes = np.loadtxt(filepath, ndmin=2)
        if bboxes.size == 0:
            return []

        coords = bboxes[:, 1:5]          # xywh
        confs = bboxes[:, 5]             # confidence
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
