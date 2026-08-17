import boto3
import os
from dotenv import load_dotenv
import pytest

# Load environment variables from .env file
load_dotenv()

# Tests run on the host: prefer the public endpoint, `minio` is compose-only.
s3_endpoint_url = (os.getenv("S3_PROXY_URL") or os.getenv("S3_ENDPOINT_URL")) + "/"
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
    bucket_names = [bucket["Name"] for bucket in response["Buckets"]]

    # One bucket per organization: {SERVER_NAME}-alert-api-{org_id}
    alert_buckets = [name for name in bucket_names if name.endswith("-alert-api-1")]
    assert alert_buckets, bucket_names

    bucket_contents = s3_client.list_objects_v2(Bucket=alert_buckets[0])
    print(bucket_contents)
    [item["Key"] for item in bucket_contents.get("Contents", [])]
    # assert keys != []


if __name__ == "__main__":
    pytest.main([__file__])
