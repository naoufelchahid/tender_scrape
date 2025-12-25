# Lambda Extract Results - Deployment Guide

## Overview

This Lambda function processes tender result markdown files from S3, extracts structured data using AWS Bedrock Nova Lite, and stores results in the PostgreSQL database.

## Prerequisites

- AWS Account with access to:
  - Lambda
  - S3
  - Bedrock (Nova Lite model enabled)
  - VPC (if database is in VPC)
- PostgreSQL database with `tenders`, `contractors`, and `results` tables
- S3 bucket: `my-tender-documents-bucket`

## Deployment Steps

### 1. Create Lambda Layer with Dependencies

```bash
# Create layer directory
mkdir -p lambda-layer/python

# Install dependencies
pip install -r lambda_extract_results_requirements.txt -t lambda-layer/python/

# Create layer zip
cd lambda-layer
zip -r ../lambda-extract-results-layer.zip .
cd ..

# Upload to AWS Lambda Layers via Console or CLI
aws lambda publish-layer-version \
  --layer-name lambda-extract-results-deps \
  --zip-file fileb://lambda-extract-results-layer.zip \
  --compatible-runtimes python3.12 \
  --region us-east-1
```

### 2. Create IAM Role

Create an IAM role with the following policies:

**Trust Relationship:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Attached Policies:**
- `AWSLambdaBasicExecutionRole` (for CloudWatch Logs)
- `AWSLambdaVPCAccessExecutionRole` (if database is in VPC)

**Inline Policy for S3 and Bedrock:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::my-tender-documents-bucket/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0"
    }
  ]
}
```

### 3. Create Lambda Function

**Via AWS Console:**

1. Go to AWS Lambda Console
2. Click "Create function"
3. Choose "Author from scratch"
4. Configuration:
   - **Function name**: `lambda-extract-results`
   - **Runtime**: Python 3.12
   - **Architecture**: x86_64
   - **Execution role**: Use the IAM role created in step 2

5. Click "Create function"

6. **Upload Code:**
   - Zip the Lambda function:
     ```bash
     zip lambda_extract_results.zip lambda_extract_results.py
     ```
   - Upload via Console or CLI:
     ```bash
     aws lambda update-function-code \
       --function-name lambda-extract-results \
       --zip-file fileb://lambda_extract_results.zip \
       --region us-east-1
     ```

7. **Add Layer:**
   - In the Lambda function page, scroll to "Layers"
   - Click "Add a layer"
   - Choose "Custom layers"
   - Select `lambda-extract-results-deps` and the latest version

8. **Configure Function:**
   - **Handler**: `lambda_extract_results.lambda_handler`
   - **Timeout**: 5 minutes (300 seconds)
   - **Memory**: 512 MB (adjust based on document size)

9. **Environment Variables:**
   ```
   DB_HOST=your-database-host.rds.amazonaws.com
   DB_NAME=your_database_name
   DB_USER=your_database_user
   DB_PASSWORD=your_database_password
   DB_PORT=5432
   AWS_REGION=us-east-1
   ```

10. **VPC Configuration** (if database is in VPC):
    - Select the same VPC as your database
    - Select private subnets
    - Select security group that allows outbound to database

### 4. Configure S3 Trigger

1. In the Lambda function page, click "Add trigger"
2. Select "S3"
3. Configuration:
   - **Bucket**: `my-tender-documents-bucket`
   - **Event type**: All object create events
   - **Prefix**: `Results_markdown/`
   - **Suffix**: `.md`
4. Click "Add"

### 5. Test the Function

**Create Test Event:**

```json
{
  "Records": [
    {
      "s3": {
        "bucket": {
          "name": "my-tender-documents-bucket"
        },
        "object": {
          "key": "Results_markdown/test_tender.md"
        }
      }
    }
  ]
}
```

**Upload Test File:**

```bash
# Upload a sample markdown file to trigger the Lambda
aws s3 cp sample_result.md s3://my-tender-documents-bucket/Results_markdown/test_tender.md
```

**Monitor Execution:**

- Check CloudWatch Logs for execution details
- Verify database records were created
- Verify file was moved to `tender_doc_final/`
- Verify original file was deleted from `Results_markdown/`

## Troubleshooting

### Common Issues

1. **Database Connection Timeout**
   - Ensure Lambda is in the same VPC as the database
   - Check security group rules allow Lambda to connect to database port

2. **Bedrock Access Denied**
   - Verify IAM role has `bedrock:InvokeModel` permission
   - Ensure Nova Lite model is enabled in your AWS region

3. **S3 Access Denied**
   - Verify IAM role has S3 permissions for the bucket
   - Check bucket policy doesn't block Lambda access

4. **Memory/Timeout Issues**
   - Increase Lambda memory allocation
   - Increase timeout (large documents may take longer)

### Logs

View logs in CloudWatch:
```bash
aws logs tail /aws/lambda/lambda-extract-results --follow
```

## Cost Estimation

- **Lambda**: ~$0.20 per 1M requests + compute time
- **Bedrock Nova Lite**: ~$0.06 per 1K input tokens, ~$0.24 per 1K output tokens
- **S3**: Standard storage and request pricing
- **Data Transfer**: Minimal (within same region)

Estimated cost for 1000 documents/month: ~$5-10

## Maintenance

- Monitor CloudWatch Logs for errors
- Review extracted data quality periodically
- Update Lambda layer when dependencies change
- Adjust timeout/memory based on actual usage patterns
