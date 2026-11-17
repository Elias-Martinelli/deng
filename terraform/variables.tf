# Inputs. Only project_id and raw_bucket_name have no default: both must be
# globally unique (project ids and bucket names are shared by every GCP
# customer), so no value here could work for everyone.

variable "project_id" {
  description = "GCP project that holds the bucket, the dataset and the service account."
  type        = string
}

variable "region" {
  description = "Location of the bucket and the dataset. europe-west6 is Zurich: the data stays in Switzerland."
  type        = string
  default     = "europe-west6"
}

variable "raw_bucket_name" {
  description = "Name of the raw-zone bucket (GCS_RAW_BUCKET in .env). Globally unique, e.g. <project-id>-deng-raw."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]$", var.raw_bucket_name))
    error_message = "Bucket names are 3-63 characters: lowercase letters, digits, '-' and '_', starting and ending with a letter or digit."
  }
}

variable "bigquery_dataset_id" {
  description = "BigQuery dataset for staging and curated tables (BIGQUERY_DATASET in .env)."
  type        = string
  default     = "cl_intelligence"

  validation {
    condition     = can(regex("^[A-Za-z0-9_]+$", var.bigquery_dataset_id)) && length(var.bigquery_dataset_id) <= 1024
    error_message = "Dataset ids contain letters, digits and underscores only."
  }
}

variable "service_account_id" {
  description = "Account id of the pipeline's service account (the part before @)."
  type        = string
  default     = "deng-pipeline"
}

variable "pipeline_operators" {
  description = <<-EOT
    Principals allowed to act as the pipeline's service account, e.g.
    ["user:someone@example.com"]. They run the pipeline with
    `gcloud auth application-default login --impersonate-service-account=...`,
    so nobody needs a key file.
  EOT
  type        = list(string)
  default     = []
}

variable "noncurrent_version_retention_days" {
  description = "Days an overwritten raw answer is kept as a noncurrent object version before it is deleted."
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_retention_days >= 1
    error_message = "Keep overwritten versions for at least one day."
  }
}

variable "create_state_bucket" {
  description = "Also create a versioned bucket for remote Terraform state (see backend.tf.example)."
  type        = bool
  default     = false
}

variable "state_bucket_name" {
  description = "Name of the Terraform state bucket; only used with create_state_bucket = true."
  type        = string
  default     = ""
}

variable "force_destroy" {
  description = "Let `terraform destroy` delete buckets that still contain objects. Keep false outside of a throwaway project."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Labels put on every resource that supports them."
  type        = map(string)
  default = {
    project = "deng-hs26"
    managed = "terraform"
  }
}
