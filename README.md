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

* Send realistic alerts by running the notebook [http://0.0.0.0:8889/notebooks/notebooks/send_real_alerts.ipynb](http://0.0.0.0:8889/notebooks/notebooks/send_real_alerts.ipynb)
  (one cell per scenario: a fire seen by three towers, a fire seen by a single camera, etc.)
* Observe the alerts on the frontend at [http://localhost:8080/](http://localhost:8080/)
* Use credentials from `data/csv/API_DATA_DEV - users.csv` (`test77` / `test` or `test07` / `test`)
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

### Send alerts

The notebook `send_real_alerts.ipynb` replays real wildfire footage with the camera that
recorded it, so images, camera names and the map agree. Its last section shows how to send
your own sequence folder with `send_sequences`. The same scenarios can be sent from a shell:

```bash
docker exec -w /app/notebooks pyro-envdev-notebooks-1 python scenarios.py            # all scenarios
docker exec -w /app/notebooks pyro-envdev-notebooks-1 python scenarios.py triangulated-fire-77
docker exec -w /app/notebooks pyro-envdev-notebooks-1 python scenarios.py --delete-all-alerts  # start over
```

The *Alerts* page only shows today's alerts: send the scenarios again on another day.
When writing your own notebooks **inside Docker**, use `API_URL = "http://api:5050"`.

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
