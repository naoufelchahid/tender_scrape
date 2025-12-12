variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "eu-west-3"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "tender-scraper"
}

# S3 Bucket Variables
variable "s3_bucket_name" {
  description = "Name of the S3 bucket for storing tender documents"
  type        = string
}

variable "s3_versioning_enabled" {
  description = "Enable versioning for S3 bucket"
  type        = bool
  default     = true
}

# PostgreSQL RDS Variables
variable "db_name"         {
  description = "Name of the PostgreSQL database"
  type        = string
  default     = "tendersdb"
}

variable "db_username" {
  description = "Master username for PostgreSQL database"
  type        = string
  default     = "dbadmin"
  sensitive   = true
}

variable "db_password" {
  description = "Master password for PostgreSQL database"
  type        = string
  sensitive   = true
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "Allocated storage for RDS instance in GB"
  type        = number
  default     = 20
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "16.11"
}

variable "db_publicly_accessible" {
  description = "Whether the database should be publicly accessible"
  type        = bool
  default     = false
}

variable "db_backup_retention_period" {
  description = "Number of days to retain backups"
  type        = number
  default     = 7
}

variable "db_skip_final_snapshot" {
  description = "Skip final snapshot when destroying database"
  type        = bool
  default     = false
}
