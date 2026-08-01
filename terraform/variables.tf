variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "ringed-hearth-504112-e3"
}

variable "region" {
  description = "Default region for regional resources"
  type        = string
  default     = "europe-west1"
}

variable "dataset_id" {
  description = "BigQuery dataset for the audit data-quality pipeline"
  type        = string
  default     = "audit_controls"
}

variable "create_dataset" {
  description = "Set to false if audit_controls already exists (import it instead: terraform import google_bigquery_dataset.audit_controls projects/<project>/datasets/<dataset>)"
  type        = bool
  default     = true
}

variable "bucket_name" {
  description = "GCS bucket the pipeline reads/writes (functional-docs/, incoming/, specs/). Must be globally unique across all of GCS, not just this project."
  type        = string
  default     = "ringed-hearth-504112-e3-dq-bucket"
}

variable "bucket_location" {
  description = "GCS bucket location. Defaults to US (multi-region) to match the BigQuery dataset's location so GCS->BigQuery loads stay in-region; the Cloud Run services themselves run in var.region regardless."
  type        = string
  default     = "US"
}
