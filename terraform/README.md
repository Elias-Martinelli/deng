# Terraform: the GCP resources of the final milestone

This folder creates everything the cloud path needs, and nothing else:

| Resource | Name (default) | Why |
|---|---|---|
| GCS bucket | `var.raw_bucket_name` | the raw zone: one object per API answer per day (`src/deng/raw_zone/gcs.py`) |
| BigQuery dataset | `cl_intelligence` | staging and curated tables, loaded from the bucket (backlog EPIC 10) |
| Service account | `deng-pipeline@<project>.iam.gserviceaccount.com` | the identity the pipeline runs as |
| IAM: `roles/storage.objectUser` on the bucket | — | read, write, overwrite and list objects, but not change the bucket |
| IAM: `roles/bigquery.dataEditor` on the dataset | — | create and `MERGE` into tables of this dataset only |
| IAM: `roles/bigquery.jobUser` on the project | — | run load and query jobs (jobs are project resources) |
| IAM: `roles/iam.serviceAccountTokenCreator` on the service account | for each of `var.pipeline_operators` | lets a named person act as the pipeline without a key file |
| APIs | storage, bigquery, iam, iamcredentials | a fresh project has them switched off |
| GCS bucket (optional) | `var.state_bucket_name` | remote Terraform state, with `create_state_bucket = true` |

The bucket's settings, and the reason for each:

* **Region `europe-west6` (Zurich)**, for the bucket and the dataset alike.
  BigQuery loads from GCS only within one location, and the data stays in
  Switzerland.
* **Uniform bucket-level access, public access prevented.** The bucket holds
  answers from licensed APIs, so access is IAM only, with no object ACLs and
  never public.
* **Versioning with a 30-day limit on noncurrent versions.** A rerun overwrites
  the day's object, because the object name is a function of the business key.
  Versioning keeps the answer it replaced, so a provider's silent correction
  stays visible for 30 days (`noncurrent_version_retention_days`).
* **No service-account key.** A key would sit in the state file and on a laptop
  as a long-lived secret. Operators impersonate the account instead (see below).

## Prerequisites

* Terraform ≥ 1.6. It was checked with 1.9.8 and Google provider 8.11.
* The [gcloud CLI](https://cloud.google.com/sdk/docs/install), logged in:

  ```bash
  gcloud auth login
  gcloud auth application-default login   # the credentials Terraform uses
  ```

* A GCP project with billing enabled. At this volume (about 2 MB a day,
  ADR-003) it stays within the free tier.

### Permissions of the person who runs `apply`

Terraform acts with *your* credentials. On the project you need:

| Role | For |
|---|---|
| `roles/serviceusage.serviceUsageAdmin` | enabling the four APIs |
| `roles/storage.admin` | creating the buckets and their IAM bindings |
| `roles/bigquery.admin` | creating the dataset and its IAM binding |
| `roles/iam.serviceAccountAdmin` | creating the service account and its IAM binding |
| `roles/resourcemanager.projectIamAdmin` | the project-level `bigquery.jobUser` binding |

`roles/owner` covers all five. That is fine for a student project you own, but
it is more than the list above needs.

## Usage

All commands run from this folder.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # git-ignored; set project_id and raw_bucket_name
```

**init**: downloads the Google provider and prepares the state. It is safe to
rerun.

```bash
terraform init
```

**validate** checks syntax and references, offline. `fmt -check` fails on
unformatted files. `make terraform-check` runs both.

```bash
terraform fmt -check -recursive
terraform validate
```

**plan** shows what `apply` would change. A first plan creates 10 resources,
or 12 with `create_state_bucket = true` and one operator. It changes nothing.

```bash
terraform plan -out=deng.tfplan
```

**apply** creates the resources. Passing the saved plan applies exactly what
was reviewed.

```bash
terraform apply deng.tfplan
```

Then copy the settings the pipeline needs into `.env`:

```bash
terraform output -raw env_lines >> ../.env
```

This adds `GCP_PROJECT_ID`, `GCP_REGION`, `GCS_RAW_BUCKET`, `BIGQUERY_DATASET`
and `RAW_TARGETS=postgres,gcs`.

**destroy** removes everything this folder created. The APIs stay enabled
(`disable_on_destroy = false`), because other work in the project may need them.

```bash
terraform destroy
```

A bucket that still holds objects is only deleted with
`force_destroy = true`. That is deliberate: a `destroy` by accident must not
take the raw zone with it. In a throwaway project, set it in `terraform.tfvars`,
run `apply`, then `destroy`.

## Running the pipeline against the bucket

```bash
make setup-cloud                      # installs google-cloud-storage (the `cloud` extra)
gcloud auth application-default login \
  --impersonate-service-account="$(terraform -chdir=terraform output -raw service_account_email)"
make ingest-samples                   # or `make ingest` with an API key
gcloud storage ls -r "gs://$(terraform -chdir=terraform output -raw raw_bucket_name)/raw/"
```

The impersonating login only works for principals listed in
`pipeline_operators`. The pipeline then writes with exactly the service
account's permissions, not with yours, so a missing permission shows up on
your machine first.

## Remote state

By default the state is local: `terraform.tfstate`, git-ignored. That is enough
for one person. To share it, keep it in GCS. The state bucket cannot hold the
state that creates it, so this is a two-step bootstrap:

1. In `terraform.tfvars`, set `create_state_bucket = true` and
   `state_bucket_name = "..."`, then run `terraform apply`. The state is still
   local at this point.
2. Run `cp backend.tf.example backend.tf`, set the same bucket name in it, then
   run `terraform init -migrate-state`. Terraform copies the local state into
   the bucket.

The state bucket is versioned, so every `apply` leaves the previous state
behind and a broken one can be rolled back.

## What is verified, and what is not

* `terraform fmt -check`, `init -backend=false` and `validate` pass, in CI
  too (the `terraform` job in `.github/workflows/ci.yml`).
* `terraform plan` was run offline against a placeholder project and lists the
  12 resources above.
* **Not yet applied to a real project.** That needs the team's GCP project and
  billing account (backlog 11.1).
