# Sandbox runner host (GCE VM)

Live mock sessions run untrusted code, so the sandbox runner (`sandbox/runner`) cannot live inside the Cloud Run service.
In production it runs alone on one small Compute Engine VM that only the Dayline Cloud Run service can reach, over a private network.

```
browser ─► Cloud Run "dayline" ──(Direct VPC egress, private ranges only)──► 10.90.0.10:8100
                                                                             dayline-runner VM
                                                                             runner ─► Docker + gVisor ─► one container per session
```

## What it creates

All names live in `config.sh` and can be overridden from the environment.

| Resource | Name | Notes |
| --- | --- | --- |
| VPC | `dayline-sandbox` | Custom mode. Nothing else lives here, and the default network's open-to-the-internet rules do not apply. |
| Subnet | `dayline-runner` (`10.90.0.0/28`) | The VM. |
| Subnet | `dayline-run-egress` (`10.90.1.0/26`) | Cloud Run Direct VPC egress (needs at least a /26). |
| Firewall | `dayline-sandbox-allow-runner-from-cloud-run` | `tcp:8100` from `10.90.1.0/26` only. |
| Firewall | `dayline-sandbox-allow-iap-ssh` | `tcp:22` from IAP (`35.235.240.0/20`) only. |
| Cloud Router + NAT | `dayline-sandbox-router`, `dayline-sandbox-nat` | Outbound only, for the VM subnet, so pack builds can pull images and packages. |
| Internal address | `dayline-runner-ip` = `10.90.0.10` | So `SANDBOX_RUNNER_URL` never changes. |
| VM | `dayline-runner` (e2-small, Debian 13, 20 GB pd-standard, `us-west1-b`) | No external IP, no service account, OS Login, Shielded VM. |
| Secret | `dayline-sandbox-runner-secret` | The shared runner secret; readable only by the Cloud Run runtime account. |

Cloud Run gets Direct VPC egress into `dayline-run-egress` with `--vpc-egress=private-ranges-only` (Supabase, Anthropic and Google traffic still go out the normal way), `SANDBOX_RUNNER_URL=http://10.90.0.10:8100`, and `SANDBOX_RUNNER_SECRET` from the secret above.

Rough monthly cost: e2-small about $12.25, disk $0.80, Cloud NAT about $1 plus $0.045/GB, Secret Manager a few cents - about $14.

## Security posture

- The runner port is reachable only from the Cloud Run egress subnet; the VM has no public address at all, and a new VPC denies every other inbound connection.
- SSH works only through IAP (`gcloud compute ssh dayline-runner --tunnel-through-iap`) with OS Login, so access follows project IAM.
- The VM has no service account, so code that escapes a sandbox finds no Google credentials, Secret Manager access or project data.
- Each session is a container with no network, a read-only root, no capabilities, a non-root user and CPU / memory / process limits (`sandbox/runner/src/dayline_runner/manager.py`), running under gVisor (`runsc`), so untrusted code never makes syscalls against the host kernel.
- The runner's Docker access is root-equivalent on the VM; that is why nothing else runs there.
  It runs as the `dayline-runner` system user under a hardened systemd unit (`dayline-runner.service`).
- Every runner request carries the shared bearer secret; it is stored root-only in `/etc/dayline-runner/env` and never in the repo or in command lines.
- `unattended-upgrades` keeps Debian (including Docker and gVisor packages) patched.

## Full-stack packs and previews

The `rails` and `next-nest` packs run dev servers inside the sandbox, and the browser sees them through the preview proxy (`sandbox/runner/src/dayline_runner/preview.py`).
Preview traffic reaches a dev server through a `docker exec` of `socat` inside the sandbox, so the containers keep `network_mode: none` and nothing new listens on the VM: no firewall change is needed.

Sizing, measured locally under runc with the runner's limits (1 CPU per sandbox), for the built-in templates:

| Pack | Image | Dev servers idle | Peak (servers + a test run) | Sandbox memory limit |
| --- | --- | --- | --- | --- |
| `next-nest` | about 1.3 GB | about 490-560 MiB | about 750 MiB | 1.5 GiB (`memory` in its `pack.toml`) |
| `rails` | about 0.4 GB | about 70-90 MiB | about 160 MiB | 1 GiB (the runner default) |

gVisor adds some memory per sandbox on top of this, and real projects grow (Next's compiler most of all).
An e2-small (2 GB) cannot hold a `next-nest` session next to the OS, Docker and the runner; e2-medium (4 GB) fits one comfortably and e2-standard-2 (8 GB) fits two (`SANDBOX_MAX_RUNNING` defaults to 2).
Choose with `VM_MACHINE_TYPE` in `config.sh`; changing an existing VM's machine type means stopping it (`gcloud compute instances set-machine-type`).

## Set up or update

As a project owner, from anywhere in the repo, with `sandbox/` and this folder committed:

```bash
deploy/sandbox-vm/setup.sh              # network, firewall, NAT, secret, VM, runner; waits for pack images
deploy/sandbox-vm/connect-cloud-run.sh  # Cloud Run: VPC egress + runner env, with automatic rollback
```

Both are idempotent.
Re-run `setup.sh` after changing `sandbox/` to redeploy the runner; it reinstalls from the committed `HEAD` and rebuilds only the pack images whose folders changed.

To rotate the secret:

```bash
openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add dayline-sandbox-runner-secret --data-file=-
deploy/sandbox-vm/setup.sh   # the runner picks up the new version
# Cloud Run resolves :latest when an instance starts; force fresh instances:
gcloud run services update dayline --region us-west1 --update-labels runner-secret-rotated="$(date +%s)"
gcloud run services update-traffic dayline --region us-west1 --to-latest
```

## Operate

```bash
gcloud compute ssh dayline-runner --zone us-west1-b --tunnel-through-iap
sudo journalctl -u dayline-runner -f          # runner logs
sudo docker ps --filter label=dayline.sandbox  # live sessions
```

## Tear down

```bash
deploy/sandbox-vm/teardown.sh
```

It disconnects Cloud Run first (live sessions then show "sandbox unavailable"), then deletes the VM, address, NAT, firewall rules, subnets, VPC and secret.
