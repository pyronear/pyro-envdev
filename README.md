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

* Replay a real alert with `make replay-alerts ALERTS=<id>` (see [Replay real alerts](#replay-real-alerts))
* Observe the alert on the frontend at [http://localhost:8080/](http://localhost:8080/)
* Use credentials from `data/csv/API_DATA_DEV/users.csv`
* Or check directly on the API at [http://0.0.0.0:5050/docs](http://0.0.0.0:5050/docs) with the same creds

---

## 🧩 Services

* **pyro-api**: Pyronear API (uvicorn)
* **db**: PostgreSQL database
* **rustfs**: S3-compatible storage (via RustFS)
* **frontend**: Web app (React, [pyro-platform](https://github.com/pyronear/pyro-platform))
* **pyro-engine**: Engine service (requires cameras, optional)
* **reolinkdev1 / reolinkdev2**: Fake Reolink cameras sending test images
* **notebooks**: Jupyter server to run helper notebooks
* **db-ui**: pgAdmin to browse/manage the database

---

## ▶️ Running

### Full stack with engine

```bash
make build
make run-all
```

This launches everything including the engine and simulated alerts.
You can check health with:

```bash
docker logs init
docker logs engine
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

## 📂 Data Usage

### Add more images to Reolink Dev

Create a directory `data/images` before starting the environment and put your images inside.

### Replay real alerts

`scripts/replay_alerts.py` replays real production alerts (all their sequences and
images) on the local stack. Alerts are stored as `alert_<id>.zip` in the
[`replay-alerts`](https://github.com/pyronear/pyro-envdev/releases/tag/replay-alerts)
GitHub release. Needs [uv](https://docs.astral.sh/uv/) (dependencies are installed on the fly).

```bash
make list-alerts                                  # alerts available in the release
make replay-alerts ALERTS="49767 54194"           # demo mode (default)
make replay-alerts ALERTS=49767 START=2026-09-28T18:53  # demo, first sequence at a local time
make replay-alerts ALERTS=49767 MODE=live         # live mode
```

Log in to the frontend as `test77` / `test` to see them.

Published alerts (`make list-alerts` for the up-to-date list):

| Alert | Prod date | Cameras | Detections |
|---|---|---|---|
| 49767 | 2026-07-10 | croix-augas-01, nemours-01, nemours-02 | 267 |
| 54194 | 2026-09-24 | moret-sur-loing-01, croix-augas-02, nemours-01, nemours-02, videlles-01 | 488 |

* **demo**: copies the prod alert as is: images and crops go to the organization
  bucket, alert, sequences and detections are written straight into the DB, with prod
  azimuths, cones and location. Times are shifted as a block so the latest sequence
  starts 1 hour ago, or the first one at `START`. Nothing is recomputed, so replays
  never mix and it takes seconds. Each replay gets its own copy of the images.
  Sequences are left unlabeled so the alert shows as live. Tied to the pyro-api DB
  schema.
* **live**: posts one frame per camera every 30 s (`--interval`) through the API,
  dated now, so validation and triangulation run locally. Replays within 2 hours of
  each other get triangulated together when their cones cross: use a fresh stack
  (`make stop && make run`) per alert.
* Cameras are matched by name and set up as in prod (position, elevation, poses);
  local poses that do not exist in prod (seeded or left by older replays) are
  deactivated. Each sequence is attached to the local copy of its prod pose. Missing
  cameras are created in organization 2 (`--org-id`), so the alerts show up for the
  `test77` user.

To make the alert cameras look alive, `make update-cameras` sets up each camera of the
published alerts (or `ALERTS="..."`) as in prod, sets its last image to its most
recent image in those alerts and sends a heartbeat, as a real camera would. The ping goes stale like a real one: run it again
before a demo.

To test the replay:

```bash
make test-replay                     # unit tests (bboxes, frames, time shift), no stack needed
make run                             # then, end to end on the local stack:
make replay-alerts ALERTS="49767 54194"
make update-cameras
```

Log in at [http://localhost:8080](http://localhost:8080) as `test77` / `test`: both alerts
are listed as live, each at its prod location, with images and crops, and their
cameras have a recent image. `make stop && make run` starts again from an empty DB.

Add new alerts (needs prod admin creds `DISTANT_*` in `.env`, and `gh` for publishing):

```bash
make fetch-alerts ALERTS="54095"      # writes data/replay_alerts/alert_54095.zip
make publish-alerts ALERTS="54095"    # uploads it to the release
```

A zip holds `alert.json` (alert, sequences, detections, cameras), the detection
images and their crops. `publish` creates the release if needed and overwrites an existing zip.
`replay` uses the local zip when present, so publishing is only needed to share.


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
