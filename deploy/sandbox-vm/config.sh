# Shared names for the sandbox runner host. Sourced by the other scripts.
# Override any of these from the environment to deploy somewhere else.

PROJECT="${PROJECT:-dayline-507600}"
REGION="${REGION:-us-west1}"
ZONE="${ZONE:-us-west1-b}"

# A dedicated VPC: nothing else lives here, and none of the default network's
# open-to-the-internet rules (default-allow-ssh, ...) apply.
NETWORK="${NETWORK:-dayline-sandbox}"
VM_SUBNET="${VM_SUBNET:-dayline-runner}"
VM_SUBNET_RANGE="${VM_SUBNET_RANGE:-10.90.0.0/28}"
# Cloud Run Direct VPC egress needs its own subnet of at least /26.
RUN_SUBNET="${RUN_SUBNET:-dayline-run-egress}"
RUN_SUBNET_RANGE="${RUN_SUBNET_RANGE:-10.90.1.0/26}"

ROUTER="${ROUTER:-dayline-sandbox-router}"
NAT="${NAT:-dayline-sandbox-nat}"

VM="${VM:-dayline-runner}"
VM_TAG="${VM_TAG:-dayline-runner}"
VM_MACHINE_TYPE="${VM_MACHINE_TYPE:-e2-medium}"
VM_DISK_GB="${VM_DISK_GB:-20}"
VM_IP_NAME="${VM_IP_NAME:-dayline-runner-ip}"
VM_IP="${VM_IP:-10.90.0.10}"
RUNNER_PORT="${RUNNER_PORT:-8100}"

FW_RUNNER="${FW_RUNNER:-dayline-sandbox-allow-runner-from-cloud-run}"
FW_IAP_SSH="${FW_IAP_SSH:-dayline-sandbox-allow-iap-ssh}"
# Google's fixed range for IAP TCP forwarding (gcloud compute ssh --tunnel-through-iap).
IAP_RANGE="35.235.240.0/20"

SECRET="${SECRET:-dayline-sandbox-runner-secret}"

SERVICE="${SERVICE:-dayline}"

RUNNER_URL="http://${VM_IP}:${RUNNER_PORT}"

gc() { gcloud --project "$PROJECT" --quiet "$@"; }
exists() { "$@" >/dev/null 2>&1; }
step() { printf '\n==> %s\n' "$*"; }
