# Pyronear Dev Environment

This repository provides a Docker Compose configuration to run a full Pyronear development environment with the API, database, S3 emulation, frontend, notebooks, and optional camera engine.

---

## ⚙️ Installation

### Prerequisites

* Docker and Docker Compose
* Add this line to `/etc/hosts` so the MinIO endpoint resolves correctly:

  ```
  127.0.0.1 minio
  ```

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
* Observe the alert on the frontend at [http://0.0.0.0:8050/](http://0.0.0.0:8050/)
* Use credentials from `data/csv/API_DATA_DEV/users.csv`
* Or check directly on the API at [http://0.0.0.0:5050/docs](http://0.0.0.0:5050/docs) with the same creds

---

## 🧩 Services

* **pyro-api**: Pyronear API (uvicorn)
* **db**: PostgreSQL database
* **minio**: S3-compatible storage (via MinIO)
* **frontend**: Web app (Dash)
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
* **Frontend (Dash app)**: [http://localhost:8050](http://localhost:8050)

  * If issues: use a private browser window
  * Admin access currently does not display camera alerts, use user creds from `data/csv/users.csv`
* **Notebooks**: [http://localhost:8889](http://localhost:8889)
* **pgAdmin (db-ui)**: [http://localhost:8888/browser/](http://localhost:8888/browser/)

  * Login: `DB_UI_MAIL` / `DB_UI_PWD` (set in `.env`)
  * First connection: register server with host `db`, user/password from `.env`
* **MinIO console (S3 GUI)**: [http://localhost:9001](http://localhost:9001)

  * Manage buckets, upload/delete files

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

1. Upload a new image in MinIO under the bucket ending with `...-alert-api-{organisation_id}`
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
