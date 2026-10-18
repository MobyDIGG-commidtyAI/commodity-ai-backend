#!/usr/bin/env bash
# Deploy the API + dashboard (this repo) to Cloud Run with the shared bucket mounted read-only at /mnt/tank.
# The bucket is filled and refreshed by commodity-ai-caller (its deploy/gcp.sh seed / deploy). Idempotent.
#
#   PROJECT=my-project deploy/gcp.sh all            # setup build deploy monitor
#   PROJECT=my-project deploy/gcp.sh build deploy   # ship a new version
#
# Steps: setup | build | deploy | monitor | url | all.  Details: README.md
set -euo pipefail
cd "$(dirname "$0")/.."

: "${PROJECT:?set PROJECT to the GCP project id}"
REGION=${REGION:-asia-southeast1}
BUCKET=${BUCKET:-$PROJECT-cai-tank}
REPO=${REPO:-cai}
SERVICE=${SERVICE:-cai-api}
JOB=${JOB:-cai-refresh}
SCHEDULE=${SCHEDULE:-0 9 * * *}
TIME_ZONE=${TIME_ZONE:-Asia/Bangkok}
MIN_INSTANCES=${MIN_INSTANCES:-0}      # 1 removes cold starts (~870 MB image) for about US$10-15/month
TH_MARKUP=${TH_MARKUP:-1.0}
CORS_ORIGINS=${CORS_ORIGINS:-}          # empty: no CORS headers (the extension does not need them)
HTTPS_PROXY_SECRET=${HTTPS_PROXY_SECRET:-}   # Secret Manager secret holding a proxy URL for collectors blocked on GCP IPs
ALERT_EMAIL=${ALERT_EMAIL:-}
TAG=${TAG:-$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- . ':!data/export' || echo -dirty)}

IMAGE=$REGION-docker.pkg.dev/$PROJECT/$REPO/commodity-ai-backend:$TAG
API_SA=cai-api@$PROJECT.iam.gserviceaccount.com
JOB_SA=cai-refresh@$PROJECT.iam.gserviceaccount.com
MOUNT=/mnt/tank
gc() { gcloud --project "$PROJECT" --quiet "$@"; }
log() { printf '\n== %s\n' "$*"; }

setup() {
  log "enable APIs"
  gc services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    cloudscheduler.googleapis.com monitoring.googleapis.com storage.googleapis.com iam.googleapis.com \
    ${HTTPS_PROXY_SECRET:+secretmanager.googleapis.com}

  log "Artifact Registry repo $REPO"
  gc artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 ||
    gc artifacts repositories create "$REPO" --location "$REGION" --repository-format docker

  log "bucket gs://$BUCKET (versioned: each refresh keeps the previous tank and export for rollback)"
  gc storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 ||
    gc storage buckets create "gs://$BUCKET" --location "$REGION" --uniform-bucket-level-access --public-access-prevention
  gc storage buckets update "gs://$BUCKET" --versioning --lifecycle-file deploy/bucket-lifecycle.json

  log "service accounts"
  for sa in cai-api cai-refresh cai-scheduler; do
    gc iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com" >/dev/null 2>&1 ||
      gc iam service-accounts create "$sa" --display-name "commodity-ai $sa"
  done
  # API reads the export, the job owns the bucket, the scheduler may only start the job (granted in deploy)
  gc storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$API_SA" --role roles/storage.objectViewer >/dev/null
  gc storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$JOB_SA" --role roles/storage.objectAdmin >/dev/null
  if [ -n "$HTTPS_PROXY_SECRET" ]; then
    gc secrets add-iam-policy-binding "$HTTPS_PROXY_SECRET" --member "serviceAccount:$JOB_SA" --role roles/secretmanager.secretAccessor >/dev/null
  fi
  # Cloud Build runs as the default compute account in new projects, which cannot push images until granted this
  local number; number=$(gc projects describe "$PROJECT" --format 'value(projectNumber)')
  gc projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$number-compute@developer.gserviceaccount.com" \
    --role roles/cloudbuild.builds.builder --condition None >/dev/null
}

build() {
  log "build $IMAGE"
  gc builds submit --region "$REGION" --tag "$IMAGE" .
}

deploy() {
  local volume="name=tank,type=cloud-storage,bucket=$BUCKET"
  log "service $SERVICE"
  gc run deploy "$SERVICE" --region "$REGION" --image "$IMAGE" --service-account "$API_SA" \
    --allow-unauthenticated --execution-environment gen2 \
    --add-volume "$volume,readonly=true" --add-volume-mount "volume=tank,mount-path=$MOUNT" \
    --set-env-vars "^@^DATA_DIR=$MOUNT/export@TH_MARKUP=$TH_MARKUP@CORS_ORIGINS=$CORS_ORIGINS" \
    --memory 1Gi --cpu 1 --concurrency 40 --timeout 30 --min-instances "$MIN_INSTANCES" --max-instances 3

  echo "API: $(api_url)"
}

api_url() { gc run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)'; }

monitor() {
  local channel="" host check
  if [ -n "$ALERT_EMAIL" ]; then
    log "alert channel $ALERT_EMAIL"
    channel=$(gc beta monitoring channels list --filter "labels.email_address=\"$ALERT_EMAIL\"" --format 'value(name)' | head -1)
    [ -n "$channel" ] || channel=$(gc beta monitoring channels create --display-name "commodity-ai $ALERT_EMAIL" \
      --type email --channel-labels "email_address=$ALERT_EMAIL" --format 'value(name)')
  else
    echo "ALERT_EMAIL not set: alert policies are created without a notification channel (add one in the console)"
  fi

  log "uptime check on /api/health"
  host=$(api_url | sed 's#^https://##')
  check=$(gc monitoring uptime list-configs --filter "displayName=\"$SERVICE health\"" --format 'value(name)' | head -1)
  [ -n "$check" ] || check=$(gc monitoring uptime create "$SERVICE health" --resource-type uptime-url \
    --resource-labels "host=$host,project_id=$PROJECT" --protocol https --path /api/health \
    --matcher-content '"ok":true' --period 5 --timeout 10 --format 'value(name)')

  log "alert policies"
  local f name policy
  for f in deploy/alert-*.json; do
    policy=$(sed -e "s#__JOB__#$JOB#g" -e "s#__CHECK_ID__#${check##*/}#g" "$f")
    name=$(printf '%s' "$policy" | python3 -c 'import json,sys; print(json.load(sys.stdin)["displayName"])')
    if [ -z "$(gc monitoring policies list --filter "displayName=\"$name\"" --format 'value(name)')" ]; then
      printf '%s' "$policy" > "${TMPDIR:-/tmp}/cai-policy.json"
      gc monitoring policies create --policy-from-file "${TMPDIR:-/tmp}/cai-policy.json" ${channel:+--notification-channels "$channel"} >/dev/null
      echo "created: $name"
    else
      echo "exists: $name"
    fi
  done
}

[ $# -gt 0 ] || { sed -n '2,9p' "$0"; exit 1; }
for step in "$@"; do
  case $step in
    setup) setup ;; build) build ;; deploy) deploy ;; monitor) monitor ;; url) api_url ;;
    all) setup; build; deploy; monitor ;;
    *) echo "unknown step: $step"; exit 1 ;;
  esac
done
