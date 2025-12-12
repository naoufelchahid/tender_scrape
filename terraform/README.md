# Terraform AWS Infrastructure for Tender Scraper

This Terraform configuration creates the required AWS infrastructure for the tender scraper application:
- **S3 Bucket**: For storing downloaded tender documents
- **PostgreSQL RDS**: Database for storing tender metadata

## Prerequisites

1. **AWS CLI** configured with credentials
2. **Terraform** v1.0 or later
3. **AWS Account** with appropriate permissions

## Quick Start

### 1. Configure Variables

Copy the example variables file and edit it:

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` and set:
- **s3_bucket_name**: Must be globally unique (e.g., `my-company-tender-docs-2025`)
- **Default region**: Enter `eu-west-3` (or your preferred region) 8 characters)
- Other variables as needed

### 2. Initialize Terraform

```bash
terraform init
```

### 3. Review the Plan

```bash
terraform plan
```

### 4. Apply the Configuration

```bash
terraform apply
```

Review the changes and type `yes` to confirm.

### 5. Get Outputs

```bash
terraform output
```

To see sensitive outputs (like database connection details):

```bash
terraform output -json
```

## Resources Created

### S3 Bucket
- **Versioning**: Enabled by default
- **Encryption**: AES256 server-side encryption
- **Public Access**: Blocked (private bucket)

### PostgreSQL RDS
- **Engine**: PostgreSQL 16.3
- **Instance Class**: db.t3.micro (free tier eligible)
- **Storage**: 20 GB gp3 (encrypted)
- **Backups**: 7-day retention
- **Monitoring**: Enhanced monitoring enabled
- **Security Group**: Restricts access to port 5432

## Connecting to PostgreSQL

After deployment, get the connection details:

```bash
# Get endpoint
terraform output db_endpoint

# Get connection string
terraform output db_connection_string
```

Connect using psql:

```bash
psql "postgresql://admin:YOUR_PASSWORD@YOUR_ENDPOINT/tendersdb"
```

## Cost Estimation

### Free Tier Eligible
- **S3**: 5GB storage, 20,000 GET requests, 2,000 PUT requests/month
- **RDS db.t3.micro**: 750 hours/month, 20GB storage

### After Free Tier
- **S3**: ~$0.023 per GB/month
- **RDS db.t3.micro**: ~$15-20/month

## Cleanup

To destroy all resources:

```bash
terraform destroy
```

**Note**: If `db_skip_final_snapshot = false`, a final snapshot will be created before deletion.

## Security Recommendations

1. **Never commit** `terraform.tfvars` to version control
2. **Use strong passwords** for database
3. **Enable MFA** on AWS account
4. **Review security groups** before making database publicly accessible
5. **Enable encryption** at rest and in transit (already configured)

## Customization

### Change Instance Size

Edit `terraform.tfvars`:
```hcl
db_instance_class = "db.t3.small"  # Or larger
```

### Enable Public Access

Edit `terraform.tfvars`:
```hcl
db_publicly_accessible = true
```

**Warning**: Only enable public access if absolutely necessary and ensure strong passwords are used.

## Troubleshooting

### S3 Bucket Name Already Exists
S3 bucket names must be globally unique. Change `s3_bucket_name` in `terraform.tfvars`.

### Database Connection Timeout
- Check security group allows your IP address
- Verify `db_publicly_accessible = true` if connecting from outside AWS
- Check VPC and subnet configuration

### Invalid Password
PostgreSQL passwords must be at least 8 characters and cannot contain `/`, `"`, or `@`.
