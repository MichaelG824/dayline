#!/usr/bin/env bash
# Point the Dayline Cloud Run service at the runner VM (run setup.sh first).
# Adds only Direct VPC egress (private ranges), SANDBOX_RUNNER_URL and the
# SANDBOX_RUNNER_SECRET secret; every other setting is left as it is.
#
# The new revision is deployed without traffic, then promoted. If it fails
# to serve, traffic goes straight back to the revision that had it before.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=config.sh
source "$here/config.sh"

describe() { gc run services describe "$SERVICE" --region "$REGION" --format json; }
serving_revision() {
  describe | python3 -c '
import json, sys
traffic = json.load(sys.stdin)["status"].get("traffic", [])
print(next(t["revisionName"] for t in traffic if t.get("percent") == 100))'
}

step "Let the service's runtime account read $SECRET (and nothing else new)"
sa="$(gc run services describe "$SERVICE" --region "$REGION" \
  --format 'value(spec.template.spec.serviceAccountName)')"
if [[ -z "$sa" ]]; then
  sa="$(gc projects describe "$PROJECT" --format 'value(projectNumber)')-compute@developer.gserviceaccount.com"
fi
gc secrets add-iam-policy-binding "$SECRET" --member "serviceAccount:$sa" \
  --role roles/secretmanager.secretAccessor --format none

previous="$(serving_revision)"
step "Serving revision before: $previous"

step "Deploy a revision with VPC egress + runner env (no traffic yet)"
gc run services update "$SERVICE" --region "$REGION" \
  --network "$NETWORK" --subnet "$RUN_SUBNET" --vpc-egress private-ranges-only \
  --update-env-vars "SANDBOX_RUNNER_URL=$RUNNER_URL" \
  --update-secrets "SANDBOX_RUNNER_SECRET=$SECRET:latest" \
  --no-traffic
# Not latestReadyRevisionName: it can lag behind, and revision numbers are
# not ordered. `update` has already waited for this revision to be Ready.
new="$(gc run services describe "$SERVICE" --region "$REGION" \
  --format 'value(status.latestCreatedRevisionName)')"

if [[ "$new" == "$previous" ]]; then
  step "Nothing changed; $previous already has this configuration"
  exit 0
fi

step "Promote $new"
gc run services update-traffic "$SERVICE" --region "$REGION" --to-revisions "$new=100"
url="$(gc run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
if ! curl -fsS --retry 5 --retry-delay 3 --retry-all-errors "$url/api/health" >/dev/null; then
  echo "$new does not answer /api/health; rolling traffic back to $previous" >&2
  gc run services update-traffic "$SERVICE" --region "$REGION" --to-revisions "$previous=100"
  exit 1
fi

step "Live: $new (roll back with:"
echo "  gcloud run services update-traffic $SERVICE --project $PROJECT --region $REGION --to-revisions $previous=100 )"
