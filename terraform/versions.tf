# Terraform and provider versions.
#
# The provider is pinned to one major release: a new major of the Google
# provider renames or removes arguments, and `terraform init` on a reviewer's
# machine must resolve the same provider the code was validated against.
#
# State is local by default (terraform.tfstate, git-ignored). To keep it in GCS
# instead, see backend.tf.example and README.md "Remote state".

terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.11"
    }
  }
}

# No credentials here, on purpose: the provider uses Application Default
# Credentials (`gcloud auth application-default login`), so no key file is ever
# named in the code or committed next to it.
provider "google" {
  project = var.project_id
  region  = var.region
}
