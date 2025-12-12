# S3 Bucket for storing tender documents
resource "aws_s3_bucket" "tender_documents" {
  bucket = var.s3_bucket_name

  tags = {
    Name        = "${var.project_name}-documents"
    Description = "Storage for tender documents and downloads"
  }
}

# S3 Bucket Versioning
resource "aws_s3_bucket_versioning" "tender_documents" {
  bucket = aws_s3_bucket.tender_documents.id

  versioning_configuration {
    status = var.s3_versioning_enabled ? "Enabled" : "Disabled"
  }
}

# S3 Bucket Server-Side Encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "tender_documents" {
  bucket = aws_s3_bucket.tender_documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 Bucket Public Access Block
resource "aws_s3_bucket_public_access_block" "tender_documents" {
  bucket = aws_s3_bucket.tender_documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Security Group for RDS PostgreSQL
resource "aws_security_group" "postgres_sg" {
  name        = "${var.project_name}-postgres-sg"
  description = "Security group for PostgreSQL RDS instance"

  ingress {
    description = "PostgreSQL access"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.db_publicly_accessible ? ["0.0.0.0/0"] : ["10.0.0.0/8"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-postgres-sg"
  }
}

# DB Subnet Group (using default VPC subnets)
resource "aws_db_subnet_group" "postgres" {
  name       = "${var.project_name}-postgres-subnet-group"
  subnet_ids = data.aws_subnets.default.ids

  tags = {
    Name = "${var.project_name}-postgres-subnet-group"
  }
}

# PostgreSQL RDS Instance
resource "aws_db_instance" "postgres" {
  identifier = "${var.project_name}-postgres"

  # Database Configuration
  engine               = "postgres"
  engine_version       = var.db_engine_version
  instance_class       = var.db_instance_class
  allocated_storage    = var.db_allocated_storage
  storage_type         = "gp3"
  storage_encrypted    = true

  # Database Credentials
  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  # Network Configuration
  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.postgres_sg.id]
  publicly_accessible    = var.db_publicly_accessible
  port                   = 5432

  # Backup Configuration
  backup_retention_period = var.db_backup_retention_period
  backup_window          = "03:00-04:00"
  maintenance_window     = "mon:04:00-mon:05:00"
  skip_final_snapshot    = var.db_skip_final_snapshot
  final_snapshot_identifier = var.db_skip_final_snapshot ? null : "${var.project_name}-final-snapshot-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"

  # Performance and Monitoring
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  monitoring_interval             = 60
  monitoring_role_arn            = aws_iam_role.rds_monitoring.arn

  # Deletion Protection
  deletion_protection = false

  tags = {
    Name = "${var.project_name}-postgres"
  }
}

# IAM Role for RDS Enhanced Monitoring
resource "aws_iam_role" "rds_monitoring" {
  name = "${var.project_name}-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "monitoring.rds.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-rds-monitoring-role"
  }
}

# Attach AWS managed policy for RDS Enhanced Monitoring
resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# Data source to get default VPC
data "aws_vpc" "default" {
  default = true
}

# Data source to get default subnets
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
