#!/usr/bin/env bash
# Create (or reconcile) the sandbox runner host: a private VPC, firewall,
# Cloud NAT, the shared runner secret, and one VM running the runner.
# Safe to re-run: every step skips what already exists, and the last step
# reinstalls the runner from this checkout's committed sandbox/ folder.
#
# Run from anywhere inside the repo, as a project owner:
#   deploy/sandbox-vm/setup.sh
# Then wire Cloud Run to it with deploy/sandbox-vm/connect-cloud-run.sh.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=config.sh
source "$here/config.sh"
repo="$(git -C "$here" rev-parse --show-toplevel)"

step "APIs"
gc services enable compute.googleapis.com secretmanager.googleapis.com iap.googleapis.com

step "Network $NETWORK"
exists gc compute networks describe "$NETWORK" ||
  gc compute networks create "$NETWORK" --subnet-mode=custom
exists gc compute networks subnets describe "$VM_SUBNET" --region "$REGION" ||
  gc compute networks subnets create "$VM_SUBNET" --network "$NETWORK" \
    --region "$REGION" --range "$VM_SUBNET_RANGE"
exists gc compute networks subnets describe "$RUN_SUBNET" --region "$REGION" ||
  gc compute networks subnets create "$RUN_SUBNET" --network "$NETWORK" \
    --region "$REGION" --range "$RUN_SUBNET_RANGE"

step "Firewall (a new VPC denies all ingress; these are the only exceptions)"
exists gc compute firewall-rules describe "$FW_RUNNER" ||
  gc compute firewall-rules create "$FW_RUNNER" --network "$NETWORK" \
    --direction INGRESS --action ALLOW --rules "tcp:$RUNNER_PORT" \
    --source-ranges "$RUN_SUBNET_RANGE" --target-tags "$VM_TAG" \
    --description "Dayline Cloud Run (Direct VPC egress) -> sandbox runner"
exists gc compute firewall-rules describe "$FW_IAP_SSH" ||
  gc compute firewall-rules create "$FW_IAP_SSH" --network "$NETWORK" \
    --direction INGRESS --action ALLOW --rules tcp:22 \
    --source-ranges "$IAP_RANGE" --target-tags "$VM_TAG" \
    --description "SSH to the sandbox runner only through IAP"

step "Cloud NAT (outbound only: the VM has no public IP, but builds pull images and packages)"
exists gc compute routers describe "$ROUTER" --region "$REGION" ||
  gc compute routers create "$ROUTER" --network "$NETWORK" --region "$REGION"
exists gc compute routers nats describe "$NAT" --router "$ROUTER" --region "$REGION" ||
  gc compute routers nats create "$NAT" --router "$ROUTER" --region "$REGION" \
    --auto-allocate-nat-external-ips --nat-custom-subnet-ip-ranges "$VM_SUBNET"

step "Internal address $VM_IP"
exists gc compute addresses describe "$VM_IP_NAME" --region "$REGION" ||
  gc compute addresses create "$VM_IP_NAME" --region "$REGION" \
    --subnet "$VM_SUBNET" --addresses "$VM_IP"

step "Secret $SECRET (generated once, never printed)"
exists gc secrets describe "$SECRET" ||
  gc secrets create "$SECRET" --replication-policy automatic
if [[ -z "$(gc secrets versions list "$SECRET" --filter state=enabled --limit 1 --format 'value(name)')" ]]; then
  openssl rand -hex 32 | tr -d '\n' | gc secrets versions add "$SECRET" --data-file=-
fi

step "VM $VM"
if ! exists gc compute instances describe "$VM" --zone "$ZONE"; then
  # No service account: code on this VM gets no Google credentials at all.
  # No external IP: the only ways in are the two firewall rules above.
  gc compute instances create "$VM" --zone "$ZONE" \
    --machine-type "$VM_MACHINE_TYPE" \
    --image-family debian-13 --image-project debian-cloud \
    --boot-disk-size "${VM_DISK_GB}GB" --boot-disk-type pd-standard \
    --subnet "$VM_SUBNET" --private-network-ip "$VM_IP_NAME" --no-address \
    --no-service-account --no-scopes \
    --tags "$VM_TAG" \
    --metadata enable-oslogin=TRUE,block-project-ssh-keys=TRUE \
    --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring
fi

ssh_vm() { gc compute ssh "$VM" --zone "$ZONE" --tunnel-through-iap --command "$1"; }

step "Waiting for SSH over IAP"
for attempt in $(seq 1 30); do
  ssh_vm true >/dev/null 2>&1 && break
  [[ $attempt == 30 ]] && { echo "SSH over IAP never came up" >&2; exit 1; }
  sleep 10
done

step "Install the runner from $(git -C "$repo" rev-parse --short HEAD)"
if ! git -C "$repo" diff --quiet HEAD -- sandbox deploy/sandbox-vm; then
  echo "sandbox/ or deploy/sandbox-vm/ has uncommitted changes; commit them first" >&2
  exit 1
fi
git -C "$repo" archive --format=tar.gz HEAD sandbox deploy/sandbox-vm |
  ssh_vm 'cat > /tmp/dayline-runner.tar.gz'
# The secret travels over the SSH session's stdin into a root-only file.
gc secrets versions access latest --secret "$SECRET" |
  ssh_vm 'sudo install -d -m 700 /etc/dayline-runner &&
    sudo sh -c "umask 077; { printf SANDBOX_RUNNER_SECRET=; cat; echo; } > /etc/dayline-runner/env"'
ssh_vm 'sudo rm -rf /tmp/dayline-runner && mkdir /tmp/dayline-runner &&
  tar -xzf /tmp/dayline-runner.tar.gz -C /tmp/dayline-runner &&
  sudo bash /tmp/dayline-runner/deploy/sandbox-vm/vm-install.sh /tmp/dayline-runner'

step "Done. Runner URL for Cloud Run: $RUNNER_URL"
