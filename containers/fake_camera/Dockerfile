FROM python:3.12-slim

WORKDIR /app

# Self-signed certificate: pyro_camera_api talks HTTPS to Reolink cameras without verifying it.
RUN openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=fakecam" \
    -keyout key.pem -out cert.pem

COPY server.py .

# Default scenario, so the image runs alone (e.g. on a test station); a volume on
# /scenarios overrides it. Built with --build-context scenarios=data/scenarios (Makefile).
# hadolint ignore=DL3022
COPY --from=scenarios smoke-then-clear /scenarios/smoke-then-clear

EXPOSE 443

CMD ["python", "server.py"]
