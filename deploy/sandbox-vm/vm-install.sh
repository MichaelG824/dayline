#!/usr/bin/env bash
# Runs ON the runner VM as root (setup.sh calls it over SSH). Installs Docker,
# gVisor and the runner, then waits until every language pack image is built.
# Idempotent: re-running upgrades the runner to the copy in $1.
#
#   sudo bash vm-install.sh /path/to/extracted/checkout
set -euo pipefail
src="${1:?usage: vm-install.sh <dir holding sandbox/ and deploy/sandbox-vm/>}"
app=/opt/dayline-runner
port=8100
export DEBIAN_FRONTEND=noninteractive

echo "==> Packages"
apt-get update -q
apt-get install -y -q docker.io python3-venv curl gpg unattended-upgrades

# gVisor (runsc): every sandbox runs under its user-space kernel, so untrusted
# code never makes syscalls against the host kernel directly.
if [[ ! -f /etc/apt/sources.list.d/gvisor.list ]]; then
  curl -fsSL https://gvisor.dev/archive.key |
    gpg --dearmor --yes -o /usr/share/keyrings/gvisor-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
    >/etc/apt/sources.list.d/gvisor.list
  apt-get update -q
fi
apt-get install -y -q runsc

echo "==> Docker daemon"
python3 - <<'EOF'
import json
from pathlib import Path

path = Path("/etc/docker/daemon.json")
cfg = json.loads(path.read_text()) if path.exists() else {}
cfg.setdefault("runtimes", {})["runsc"] = {"path": "/usr/bin/runsc"}
# Rotated, size-capped container logs.
cfg["log-driver"] = "local"
new = json.dumps(cfg, indent=2) + "\n"
if not path.exists() or path.read_text() != new:
    path.write_text(new)
    print("daemon.json changed")
EOF
systemctl enable docker
systemctl restart docker

echo "==> Runner"
id dayline-runner >/dev/null 2>&1 ||
  useradd --system --home-dir /var/lib/dayline-runner --shell /usr/sbin/nologin dayline-runner
install -d "$app"
rm -rf "$app/sandbox"
cp -r "$src/sandbox" "$app/sandbox"
[[ -d "$app/venv" ]] || python3 -m venv "$app/venv"
"$app/venv/bin/pip" install -q --upgrade pip
"$app/venv/bin/pip" install -q --upgrade "$app/sandbox/runner"
"$app/venv/bin/pip" install -q --force-reinstall --no-deps "$app/sandbox/runner"

# setup.sh writes the secret here before calling this script.
test -s /etc/dayline-runner/env || { echo "/etc/dayline-runner/env is missing" >&2; exit 1; }
chmod 600 /etc/dayline-runner/env

install -m 644 "$src/deploy/sandbox-vm/dayline-runner.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable dayline-runner
systemctl restart dayline-runner

echo "==> Waiting for the language pack images (first build takes a few minutes)"
# shellcheck disable=SC1091
secret="$(. /etc/dayline-runner/env && echo "$SANDBOX_RUNNER_SECRET")"
for attempt in $(seq 1 120); do
  if packs="$(curl -fsS -H @<(printf "Authorization: Bearer %s" "$secret") "http://127.0.0.1:$port/packs" 2>/dev/null)"; then
    # Exit 0: all ready, 1: still building, 2: a build failed.
    summary="$(python3 -c '
import json, sys
packs = json.load(sys.stdin)
print(", ".join("%s=%s" % (p["name"], p["state"]) for p in packs))
states = {p["state"] for p in packs}
sys.exit(2 if "failed" in states else 0 if states == {"ready"} else 1)
' <<<"$packs")" && rc=0 || rc=$?
    case $rc in
      0) echo "ready: $summary"; exit 0 ;;
      2) echo "a pack failed to build: $summary" >&2
         journalctl -u dayline-runner --no-pager -n 50 >&2
         exit 1 ;;
      *) echo "  $summary" ;;
    esac
  fi
  [[ $attempt == 120 ]] && { echo "packs not ready after 20 minutes" >&2; exit 1; }
  sleep 10
done
