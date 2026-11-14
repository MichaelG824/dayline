#!/usr/bin/env bash
# Remove the runner host and everything setup.sh / connect-cloud-run.sh made.
# Live mock sessions become "sandbox unavailable"; the rest of Dayline is
# unaffected. Pass --yes to skip the prompt.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=config.sh
source "$here/config.sh"

if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "Delete $VM, its network $NETWORK and secret $SECRET in $PROJECT? [y/N] " answer
  [[ "$answer" == [yY] ]] || exit 1
fi

step "Disconnect Cloud Run (new revision without VPC egress or runner env)"
gc run services update "$SERVICE" --region "$REGION" --clear-network \
  --remove-env-vars SANDBOX_RUNNER_URL --remove-secrets SANDBOX_RUNNER_SECRET
# A revision pinned at 100% does not follow new revisions on its own.
gc run services update-traffic "$SERVICE" --region "$REGION" --to-latest

step "Delete the VM and its network"
if exists gc compute instances describe "$VM" --zone "$ZONE"; then
  gc compute instances delete "$VM" --zone "$ZONE"
fi
if exists gc compute addresses describe "$VM_IP_NAME" --region "$REGION"; then
  gc compute addresses delete "$VM_IP_NAME" --region "$REGION"
fi
# Deleting the router deletes its NAT too.
if exists gc compute routers describe "$ROUTER" --region "$REGION"; then
  gc compute routers delete "$ROUTER" --region "$REGION"
fi
for rule in "$FW_RUNNER" "$FW_IAP_SSH"; do
  if exists gc compute firewall-rules describe "$rule"; then
    gc compute firewall-rules delete "$rule"
  fi
done
# Cloud Run releases its Direct VPC egress addresses a while after the
# disconnect; retry until the subnet is free.
for subnet in "$RUN_SUBNET" "$VM_SUBNET"; do
  for attempt in $(seq 1 30); do
    exists gc compute networks subnets describe "$subnet" --region "$REGION" || break
    gc compute networks subnets delete "$subnet" --region "$REGION" && break
    [[ $attempt == 30 ]] && { echo "$subnet is still in use; delete it later" >&2; exit 1; }
    sleep 60
  done
done
if exists gc compute networks describe "$NETWORK"; then
  gc compute networks delete "$NETWORK"
fi

step "Delete secret $SECRET"
if exists gc secrets describe "$SECRET"; then
  gc secrets delete "$SECRET"
fi
step "Done"
