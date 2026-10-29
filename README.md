# Pyronear Dev Environment

This repository provides a Docker Compose configuration to run a full Pyronear development environment with the API, database, S3 emulation, frontend, notebooks, and optional camera engine.

---

## ⚙️ Installation

### Prerequisites

* Docker and Docker Compose

> **Upgrading?** MinIO was replaced by [RustFS](https://github.com/rustfs/rustfs): set
> `S3_ENDPOINT_URL=http://rustfs:9000` in your `.env` (or re-run `cp .env.test .env`).
> The `127.0.0.1 minio` hosts entry is no longer needed either.

---

## 🚀 Quick Start

### Init

```bash
make init
make build
```

### Run

```bash
make run
```

* Send an alert by opening [http://0.0.0.0:8889/notebooks/notebooks/send_real_alerts.ipynb](http://0.0.0.0:8889/notebooks/notebooks/send_real_alerts.ipynb)
* Observe the alert on the frontend at [http://localhost:8080/](http://localhost:8080/)
* Use credentials from `data/csv/API_DATA_DEV/users.csv`
* Or check directly on the API at [http://0.0.0.0:5050/docs](http://0.0.0.0:5050/docs) with the same creds

---

## 🧩 Services

* **pyro-api**: Pyronear API (uvicorn)
* **db**: PostgreSQL database
* **rustfs**: S3-compatible storage (via RustFS)
* **frontend**: Web app (React, [pyro-platform](https://github.com/pyronear/pyro-platform))
* **pyro_camera_api / engine**: the real camera API and engine from [pyro-engine](https://github.com/pyronear/pyro-engine) (optional)
* **fakecam-1 / fakecam-2**: fake Reolink cameras playing a scenario (see below)
* **notebooks**: Jupyter server to run helper notebooks
* **db-ui**: pgAdmin to browse/manage the database

---

## ▶️ Running

### Full stack with engine

```bash
make build
make run-all
```

This launches everything, including the engine and the fake cameras playing the
`smoke-then-clear` scenario. You can check health with:

```bash
docker logs init
docker compose logs -f engine
```

### Partial runs

* Backend only (API, DB, S3):

  ```bash
  make run-backend
  ```
* Engine only:

  ```bash
  make run-engine
  ```
* Tools only (notebooks, db-ui):

  ```bash
  make run-tools
  ```

---

## 🔑 Access

* **API**: [http://localhost:5050/docs](http://localhost:5050/docs)
* **Frontend (React app)**: [http://localhost:8080](http://localhost:8080)

  * If issues: use a private browser window
  * Admin access currently does not display camera alerts, use user creds from `data/csv/users.csv`
  * Configuration (API URL, etc.) lives in `containers/frontend/app-config.js`
* **Notebooks**: [http://localhost:8889](http://localhost:8889)
* **pgAdmin (db-ui)**: [http://localhost:8888/browser/](http://localhost:8888/browser/)

  * Login: `DB_UI_MAIL` / `DB_UI_PWD` (set in `.env`)
  * First connection: register server with host `db`, user/password from `.env`
* **RustFS console (S3 GUI)**: [http://localhost:9001/rustfs/console/](http://localhost:9001/rustfs/console/)

  * Login: `S3_ACCESS_KEY` / `S3_SECRET_KEY` (set in `.env`)
  * Manage buckets, upload/delete files
* **RustFS S3 API**: `rustfs:9000` from the compose network (`S3_ENDPOINT_URL`),
  [http://localhost:9000](http://localhost:9000) from the host (`S3_PROXY_URL`, used
  for presigned image URLs)

---

## 📷 Fake cameras and scenarios

`fakecam-1` (`croix-augas-01`) and `fakecam-2` (`nemours-02`) answer the Reolink HTTP
API (`/cgi-bin/api.cgi?cmd=Snap|PtzCtrl|GetPtzPreset|...`) over HTTPS with a self-signed
certificate, so the real `pyro_camera_api` and `engine` run against them unchanged
(`data/credentials.json`, adapter `reolink`). Each one plays a scenario: a list of
images shown one after the other, the last image being held forever. Each preset moves to
its next image on its next visit by the patrol (the first `Snap` after a `ToPos`), so the
engine sees every image once per preset, in order, whatever its timing; snaps taken in place,
like the autofocus ones, see the same image. Every preset of a camera serves the same images
for now.

```bash
make run-engine                              # engine + camera API + fake cameras
SCENARIO=never-smoke make run-engine         # pick another scenario
make restart-engine                          # replay the scenario from the start
```

Scenarios:

* `smoke-then-clear` (default): real wildfire seen by both cameras, 40 frames of smoke then a clear view
* `never-smoke`: both cameras hold a clear view
* `false-positive`: false positives from the pyro-dataset val set, YOLO fires but the temporal model rejects them (no alert expected with temporal validation)

`GET https://localhost:8443/scenario` (8444 for `fakecam-2`) reports the camera state:
current preset and azimuth, its frame index and `finished` once every visited preset shows the
last frame.

The image embeds `smoke-then-clear`, so it also runs alone, without the `data/scenarios`
volume (used by pi-manager-template on a test station).

The image `pyronear/fake-camera` is published by the `fake-camera-image` workflow: `latest`
on every change to `containers/fake_camera/` on `main`, and `X.Y.Z` on a `fake-camera-vX.Y.Z`
tag (used by pi-manager-template). It needs the `DOCKERHUB_LOGIN` / `DOCKERHUB_PW` secrets.

### Scenario format

`data/scenarios/<name>/scenario.json` describes the scenario (committed), the images
live next to it and are downloaded by `make fetch-scenario SCENARIO=<name>` from the
[`scenarios` release](https://github.com/pyronear/pyro-envdev/releases/tag/scenarios):

```
data/scenarios/smoke-then-clear/
  scenario.json          # {"cameras": {"<name>": {"poses": {"<preset>": <azimuth>}}}}
  croix-augas-01/        # frames of fakecam-1, in order: 000.jpg, 001.jpg, ...
  nemours-02/            # frames of fakecam-2
```

Camera names and presets match `data/csv/API_DATA_DEV - cameras.csv` / `poses.csv`, so
the init script gives each fake camera its token and the engine finds its poses.

To build the frames of a camera from a replayed alert zip (see `make fetch-alerts`) and
a clear image for the end of the scenario:

```bash
python scripts/make_scenario.py data/scenarios/<name>/croix-augas-01 \
    --alert data/replay_alerts/alert_49767.zip --frames 40 --clear clear.jpg
```

Then zip the images (`cd data/scenarios && zip -r <name>.zip <name> -x '*/scenario.json'`)
and attach the zip to the `scenarios` release. `scenario.json` itself is committed.

### Working on pyro-engine without a camera

Start only the fake cameras:

```bash
make run-camera
```

They are published on `https://localhost:8443` and `https://localhost:8444`. In your
pyro-engine checkout, point `credentials.json` at them with the host and port as key:

```json
{
  "localhost:8443": {"name": "croix-augas-01", "adapter": "reolink", "type": "ptz", "poses": [1, 2, 3], ...}
}
```

and use the same `CAM_USER` / `CAM_PWD` as in this repo's `.env`.

### Robustness tests on a Pi

`scripts/replay-robustness-tests.sh` replays the failures of
[roadmap#16](https://github.com/pyronear/roadmap/issues/16) on a test Pi running the real
engine stack, with the fake cameras standing in for broken ones. It runs on the Pi itself:

```bash
scp scripts/replay-robustness-tests.sh pi@<ip>:~ && ssh pi@<ip>
./replay-robustness-tests.sh setup      # pyro-engine branch, images, fake cameras, scenarios
./replay-robustness-tests.sh all        # every scenario below, about 90 min
./replay-robustness-tests.sh real       # back to the real cameras
```

The Pi needs Docker, passwordless sudo and a `~/pyro-engine` checkout with its `.env` and a
two-camera `data/credentials.json`. Point `API_URL` at preprod: the engine sends heartbeats
and images with the real camera tokens. Do not deploy with pi-manager on the Pi during a run,
it recreates the containers.

| Scenario | Fault injected | Expected | Time |
|---|---|---|---|
| `camera-timeout` | camera HTTPS redirected to a listener that never answers | `Read timed out (read timeout=10)` | 2 min |
| `api-frozen` | camera API process frozen | healthcheck restarts the API | 3 min |
| `night-per-frame` | one camera in grayscale (infrared), then one without a fresh image (204), then both grayscale | night frames skipped, no sleep on 204, sleep when every camera is at night | 15 min |
| `camera-silent` | both cameras redirected to the silent listener | API reboot attempt, no password in logs, budget kept after a container restart | 18 min |
| `camera-frozen` | one fake camera holding one frame, one serving noisy variants of one view | `frozen` and `not_moving` reboots, one "budget spent" line, second reboot after the 30 min cooldown | 50 min |

Each scenario prints `OK:` or `FAIL:` and exits non-zero on failure. The redirect rule and
its listener are removed on exit. Timings are the detector's own (5 min checks, 30 min
cooldown), so there is no fast mode.

---

## 📂 Data Usage

### Add more images to Reolink Dev

Create a directory `data/images` before starting the environment and put your images inside.

### Send custom alerts

Use Jupyter notebooks (e.g., `notebooks/send_real_alerts.ipynb`).
When running notebooks **inside Docker**, set:

```python
API_URL = "http://api:5050"

### Update the last image for a camera

1. Upload a new image in RustFS under the bucket ending with `...-alert-api-{organisation_id}`
2. In pgAdmin, update the `cameras` table:

   * `last_image` with the filename
   * `last_active_at` timestamp


```

---

## 🛑 Cleanup

Stop and remove everything:

```bash
make stop
```
