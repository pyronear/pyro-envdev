import boto3
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get S3 endpoint URL and credentials from environment variables
s3_endpoint_url = os.getenv("S3_ENDPOINT_URL")
s3_access_key = os.getenv("S3_ACCESS_KEY")
s3_secret_key = os.getenv("S3_SECRET_KEY")
s3_region = os.getenv("S3_REGION")

# Create a Boto3 client for the S3 service
s3_client = boto3.client(
    "s3",
    endpoint_url=s3_endpoint_url,
    aws_access_key_id=s3_access_key,
    aws_secret_access_key=s3_secret_key,
    region_name=s3_region,
)

# List all S3 buckets
response = s3_client.list_buckets()

# Print the names of all buckets
print("S3 Buckets:")
for bucket in response["Buckets"]:
    print(bucket["Name"])
