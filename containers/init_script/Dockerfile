FROM python:3.11-slim

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt /tmp/

# hadolint ignore=DL3013
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy initialization scripts into the container
COPY init_script.py /usr/local/bin/
COPY utils.py /usr/local/bin/

# Set execute permission on the script
RUN chmod +x /usr/local/bin/init_script.py

# Command to run the script
CMD ["python /usr/local/bin/init_script.py"]


###### TODO REFACTOR : use the init scripts which are in the test_update_pi directory
