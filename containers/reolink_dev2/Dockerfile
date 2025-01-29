# Use the official Python image as the base image
FROM python:3.9-slim

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir flask==3.0.3

# Copy the Flask server files into the container
COPY reolink_dev2.py /app/

# Expose port 5000 for Flask server
EXPOSE 443

# Command to run the Flask server
CMD ["python", "/app/reolink_dev2.py"]
