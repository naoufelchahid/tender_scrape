# S3 Bucket Outputs
output "s3_bucket_name" {
  description = "Name of the S3 bucket"
  value       = aws_s3_bucket.tender_documents.id
}

output "s3_bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = aws_s3_bucket.tender_documents.arn
}

output "s3_bucket_region" {
  description = "Region where the S3 bucket is hosted"
  value       = aws_s3_bucket.tender_documents.region
}

# PostgreSQL RDS Outputs
output "db_instance_id" {
  description = "RDS instance identifier"
  value       = aws_db_instance.postgres.id
}

output "db_instance_arn" {
  description = "ARN of the RDS instance"
  value       = aws_db_instance.postgres.arn
}

output "db_endpoint" {
  description = "Connection endpoint for the PostgreSQL database"
  value       = aws_db_instance.postgres.endpoint
}

output "db_address" {
  description = "Hostname of the PostgreSQL database"
  value       = aws_db_instance.postgres.address
}

output "db_port" {
  description = "Port of the PostgreSQL database"
  value       = aws_db_instance.postgres.port
}

output "db_name" {
  description = "Name of the PostgreSQL database"
  value       = aws_db_instance.postgres.db_name
}

output "db_username" {
  description = "Master username for the PostgreSQL database"
  value       = aws_db_instance.postgres.username
  sensitive   = true
}

output "db_resource_id" {
  description = "RDS resource ID"
  value       = aws_db_instance.postgres.resource_id
}

# Connection String Output
output "db_connection_string" {
  description = "PostgreSQL connection string (without password)"
  value       = "postgresql://${aws_db_instance.postgres.username}@${aws_db_instance.postgres.endpoint}/${aws_db_instance.postgres.db_name}"
  sensitive   = true
}
