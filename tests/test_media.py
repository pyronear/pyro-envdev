import boto3
import os
from dotenv import load_dotenv
import pytest

# Load environment variables from .env file
load_dotenv()

# Get S3 endpoint URL and credentials from environment variables
s3_endpoint_url = "http://localhost:4566/"
s3_access_key = os.getenv("S3_ACCESS_KEY")
s3_secret_key = os.getenv("S3_SECRET_KEY")
s3_region = os.getenv("S3_REGION")


@pytest.fixture
def s3_client():
    # Create a Boto3 client for the S3 service
    s3_client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint_url,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
        region_name=s3_region,
    )
    return s3_client


def test_s3_bucket(s3_client):
    response = s3_client.list_buckets()
    assert response["Buckets"][0]["Name"] == "admin"
    assert response["Buckets"][1]["Name"] == "organization1"


def test_s3_content(s3_client):
    bucket_contents = s3_client.list_objects_v2(Bucket="organization1")
    print(bucket_contents)
    keys = [item["Key"] for item in bucket_contents.get("Contents", [])]
    assert keys != []


if __name__ == "__main__":
    pytest.main([__file__])
