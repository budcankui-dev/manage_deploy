#!/usr/bin/env bash
# Bootstrap terminal topology nodes listed in ops/inventory/topology_nodes.json.
#
# This script is intentionally conservative and password-free in the repo.
# Use SSH keys, or set SSHPASS locally when sshpass is installed.
#
# Examples:
#   ./scripts/bootstrap_terminal_nodes.sh --verify-only
#   SSHPASS='...' ./scripts/bootstrap_terminal_nodes.sh --configure-docker --deploy-agent
#
# Required on the operator machine for password mode: sshpass.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INVENTORY="${INVENTORY:-${ROOT}/ops/inventory/topology_nodes.json}"
NETWORK_PROFILE="${NETWORK_PROFILE:-acceptance}"
case "${NETWORK_PROFILE}" in
  current|dev|development|campus)
    PROFILE_REGISTRY="10.112.244.94:5000"
    ;;
  acceptance|accept|prod|production)
    NETWORK_PROFILE="acceptance"
    PROFILE_REGISTRY="172.16.0.254:5000"
    ;;
  *)
    echo "Unsupported NETWORK_PROFILE=${NETWORK_PROFILE}; expected current or acceptance" >&2
    exit 2
    ;;
esac
REGISTRY="${PRIVATE_REGISTRY:-${PROFILE_REGISTRY}}"
NODE_AGENT_IMAGE="${NODE_AGENT_IMAGE:-${REGISTRY}/node-agent:dev}"
ALIYUN_MIRROR="${ALIYUN_MIRROR:-}"

VERIFY_ONLY=0
CONFIGURE_DOCKER=0
DEPLOY_AGENT=0

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap_terminal_nodes.sh [options]

Options:
  --verify-only        Only verify SSH, Docker, and Node Agent health.
  --configure-docker   Configure Docker registry mirror and insecure registry.
  --deploy-agent       Pull and run Node Agent container.

Environment:
  INVENTORY            Inventory JSON path. Default: ops/inventory/topology_nodes.json
  NETWORK_PROFILE      acceptance -> 172.16 management addresses; current -> 10.112 fallback addresses.
  PRIVATE_REGISTRY     Private registry host:port. Default follows NETWORK_PROFILE.
  NODE_AGENT_IMAGE     Node Agent image. Default: $PRIVATE_REGISTRY/node-agent:dev
  ALIYUN_MIRROR        Optional Docker registry mirror URL.
  SSHPASS              Optional password for sshpass mode. Prefer SSH keys when possible.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-only) VERIFY_ONLY=1 ;;
    --configure-docker) CONFIGURE_DOCKER=1 ;;
    --deploy-agent) DEPLOY_AGENT=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

if [[ "${VERIFY_ONLY}" == "0" && "${CONFIGURE_DOCKER}" == "0" && "${DEPLOY_AGENT}" == "0" ]]; then
  VERIFY_ONLY=1
fi

mapfile -t NODES < <(
  python3 - "$INVENTORY" "$NETWORK_PROFILE" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
profile = sys.argv[2]
for item in data.get("terminal_nodes", []):
    management_ip = item.get("management_ip")
    if profile == "acceptance":
        management_ip = item.get("acceptance_management_ip") or management_ip
    if not management_ip:
        raise SystemExit(f"{item.get('hostname') or item!r} missing management_ip for {profile}")
    print("\t".join([
        item["hostname"],
        management_ip,
        str(item.get("ssh_port", 22)),
        item.get("ssh_user", "switchpc1"),
        str(item.get("agent_port", 8001)),
    ]))
PY
)

ssh_cmd() {
  local user="$1" host="$2" port="$3"
  shift 3
  if [[ -n "${SSHPASS:-}" ]]; then
    sshpass -e ssh -o StrictHostKeyChecking=accept-new -p "$port" "${user}@${host}" "$@"
  else
    ssh -o StrictHostKeyChecking=accept-new -p "$port" "${user}@${host}" "$@"
  fi
}

remote_script() {
  local agent_port="$1"
  cat <<EOF
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed; install Docker before deploying Node Agent."
  exit 20
fi

if [[ "${CONFIGURE_DOCKER}" == "1" ]]; then
  sudo mkdir -p /etc/docker
  cat >/tmp/manage_deploy_update_daemon.py <<'PY'
import json
import shutil
import time
import sys
from pathlib import Path

path = Path("/etc/docker/daemon.json")
data = {}
if path.exists():
    text = path.read_text().strip()
    if text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"Invalid {path}: {exc}. Refuse to overwrite Docker daemon config.", file=sys.stderr)
            raise SystemExit(21)
mirror = "${ALIYUN_MIRROR}"
registry = "${REGISTRY}"
if mirror:
    mirrors = data.setdefault("registry-mirrors", [])
    if mirror not in mirrors:
        mirrors.append(mirror)
insecure = data.setdefault("insecure-registries", [])
if registry not in insecure:
    insecure.append(registry)
if path.exists():
    backup = path.with_name(f"daemon.json.bak.{time.strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(path, backup)
tmp = path.with_name("daemon.json.tmp")
tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
tmp.replace(path)
PY
  sudo python3 /tmp/manage_deploy_update_daemon.py
  sudo systemctl restart docker
fi

if [[ "${DEPLOY_AGENT}" == "1" ]]; then
  docker pull "${NODE_AGENT_IMAGE}"
  docker rm -f manage-node-agent >/dev/null 2>&1 || true
  docker run -d --name manage-node-agent --restart unless-stopped \\
    --network host --privileged \\
    -e AGENT_PORT="${agent_port}" \\
    -e DOCKER_SOCKET=unix:///var/run/docker.sock \\
    -v /var/run/docker.sock:/var/run/docker.sock \\
    "${NODE_AGENT_IMAGE}"
fi

docker --version
curl -fsS "http://127.0.0.1:${agent_port}/health" || true
EOF
}

for row in "${NODES[@]}"; do
  IFS=$'\t' read -r alias host port user agent_port <<<"$row"
  echo "==> ${alias} ${user}@${host}:${port}"
  if [[ "${VERIFY_ONLY}" == "1" && "${CONFIGURE_DOCKER}" == "0" && "${DEPLOY_AGENT}" == "0" ]]; then
    ssh_cmd "$user" "$host" "$port" "hostname; docker --version || true; curl -fsS http://127.0.0.1:${agent_port}/health || true"
  else
    ssh_cmd "$user" "$host" "$port" "$(remote_script "$agent_port")"
  fi
done
