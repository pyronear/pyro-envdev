FROM python:3.8.16-slim

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# hadolint ignore=DL3013
RUN pip install --no-cache-dir pandas git+https://github.com/pyronear/pyro-engine@develop python-dotenv==1.0.1 boto3==1.34.90

# Copy your initialization script into the container
COPY init_script.py /usr/local/bin/

# Set execute permission on the script
RUN chmod +x /usr/local/bin/init_script.py

# Command to run the script
CMD ["python /usr/local/bin/init_script.py"]
