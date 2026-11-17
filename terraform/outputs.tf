# What the pipeline needs to know after `terraform apply`. `env_lines` prints
# the block to paste into .env, so the names cannot drift between Terraform and
# the settings in src/deng/config.py.

output "raw_bucket_name" {
  description = "Raw-zone bucket (GCS_RAW_BUCKET)."
  value       = google_storage_bucket.raw.name
}

output "raw_bucket_url" {
  description = "gs:// URL of the raw zone."
  value       = google_storage_bucket.raw.url
}

output "bigquery_dataset_id" {
  description = "BigQuery dataset (BIGQUERY_DATASET)."
  value       = google_bigquery_dataset.warehouse.dataset_id
}

output "service_account_email" {
  description = "The pipeline's service account; impersonate it to run the pipeline."
  value       = google_service_account.pipeline.email
}

output "state_bucket_name" {
  description = "Remote-state bucket, if created."
  value       = var.create_state_bucket ? google_storage_bucket.terraform_state[0].name : null
}

output "env_lines" {
  description = "Lines for .env."
  value       = <<-EOT
    GCP_PROJECT_ID=${var.project_id}
    GCP_REGION=${var.region}
    GCS_RAW_BUCKET=${google_storage_bucket.raw.name}
    BIGQUERY_DATASET=${google_bigquery_dataset.warehouse.dataset_id}
    RAW_TARGETS=postgres,gcs
  EOT
}
