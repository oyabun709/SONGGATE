#!/bin/sh
# Creates the S3 bucket in LocalStack on startup
awslocal s3 mb s3://ropqa-artifacts
awslocal s3api put-bucket-cors \
  --bucket ropqa-artifacts \
  --cors-configuration '{
    "CORSRules": [{
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["PUT", "GET", "HEAD"],
      "AllowedOrigins": ["http://localhost:3000"],
      "ExposeHeaders": ["ETag"]
    }]
  }'
echo "LocalStack S3 bucket ready."
