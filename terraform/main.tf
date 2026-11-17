# The cloud resources of the final milestone: one bucket for the raw zone, one
# BigQuery dataset for staging and curated, one service account the pipeline
# runs as, and the narrowest IAM bindings that let it do its work.

locals {
  service_account_member = "serviceAccount:${google_service_account.pipeline.email}"
}

# --- APIs ---------------------------------------------------------------------
# A fresh project has these switched off; every resource below needs one.
# disable_on_destroy = false: `terraform destroy` removes our resources, not the
# project's ability to use the services (other work in the project may need them).

resource "google_project_service" "required" {
  for_each = toset([
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com", # impersonation of the service account
  ])

  service            = each.value
  disable_on_destroy = false
}

# --- Raw zone -----------------------------------------------------------------

resource "google_storage_bucket" "raw" {
  name     = var.raw_bucket_name
  location = var.region
  labels   = var.labels

  # Raw answers are read by BigQuery a few times a day, not served: Standard is
  # the right class, and the volume (about 2 MB a day, ADR-003) is too small
  # for a colder class to save anything.
  storage_class = "STANDARD"

  # IAM only, no per-object ACLs, and never public: the bucket holds answers
  # from licensed APIs.
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # A rerun overwrites the object of its day (the name is a function of the
  # business key, src/deng/raw_zone/gcs.py). Versioning keeps the answer it
  # replaced, so a provider's silent correction stays visible for a while ...
  versioning {
    enabled = true
  }

  # ... and this rule bounds how long, so overwritten versions do not pile up.
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = var.noncurrent_version_retention_days
    }
    action {
      type = "Delete"
    }
  }

  force_destroy = var.force_destroy

  depends_on = [google_project_service.required]
}

# --- Warehouse ----------------------------------------------------------------

resource "google_bigquery_dataset" "warehouse" {
  dataset_id    = var.bigquery_dataset_id
  friendly_name = "Champions League match intelligence"
  description   = "Staging and curated tables built from the raw zone in gs://${var.raw_bucket_name}."
  # Same location as the bucket: BigQuery loads from GCS only within a location.
  location = var.region
  labels   = var.labels

  # Tables are rebuilt from the raw zone, so deleting the dataset loses nothing
  # that cannot be recomputed - but only with force_destroy, never by accident.
  delete_contents_on_destroy = var.force_destroy

  depends_on = [google_project_service.required]
}

# --- Identity -----------------------------------------------------------------

resource "google_service_account" "pipeline" {
  account_id   = var.service_account_id
  display_name = "DENG pipeline"
  description  = "Writes raw API answers to gs://${var.raw_bucket_name} and builds ${var.bigquery_dataset_id} in BigQuery."

  depends_on = [google_project_service.required]
}

# No google_service_account_key on purpose: a key in the state file or on a
# laptop is a long-lived secret. Operators impersonate the account instead.
resource "google_service_account_iam_member" "operators" {
  for_each = toset(var.pipeline_operators)

  service_account_id = google_service_account.pipeline.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = each.value
}

# --- Permissions (least privilege) -----------------------------------------------
# Bucket: read, write, overwrite and list objects - but not change the bucket
# or its IAM. objectUser is the smallest predefined role that can overwrite an
# object (an overwrite is a delete plus a create) and list a prefix. It has no
# storage.buckets.get: the client library's background read of bucket metadata
# (for its telemetry) then gets a 403, caches a fallback and does not ask again.
resource "google_storage_bucket_iam_member" "pipeline_raw_objects" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectUser"
  member = local.service_account_member
}

# Dataset: create, replace and MERGE into tables of this one dataset only.
resource "google_bigquery_dataset_iam_member" "pipeline_data_editor" {
  dataset_id = google_bigquery_dataset.warehouse.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = local.service_account_member
}

# Project: BigQuery jobs (loads, queries) are project resources, so running one
# can only be granted here. jobUser runs jobs; it reads no data by itself.
resource "google_project_iam_member" "pipeline_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = local.service_account_member
}

# --- Optional: remote state -----------------------------------------------------

resource "google_storage_bucket" "terraform_state" {
  count = var.create_state_bucket ? 1 : 0

  name                        = var.state_bucket_name
  location                    = var.region
  labels                      = var.labels
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy

  # Every apply writes a new state version; versioning is what lets a broken
  # state be rolled back.
  versioning {
    enabled = true
  }

  lifecycle {
    precondition {
      condition     = var.state_bucket_name != ""
      error_message = "Set state_bucket_name when create_state_bucket = true."
    }
  }

  depends_on = [google_project_service.required]
}
