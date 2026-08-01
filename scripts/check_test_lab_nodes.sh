#!/usr/bin/env bash
set -u

# Read-only preflight for the three currently verified campus-network workers.
# It uses the dedicated zjl account and project key, and never prompts for passwords.

key_file="${MANAGE_DEPLOY_LAB_KEY:-$HOME/.ssh/manage_deploy_test_lab_ed25519}"
if [[ ! -f "$key_file" ]]; then
  printf 'missing SSH key: %s\n' "$key_file" >&2
  exit 1
fi

nodes=(
  "compute-1|10.112.38.25|2345|/data/hdd1"
  "compute-2|10.112.17.51|2345|/disk/sdb"
  "compute-3|10.112.59.209|22|/data"
)

for entry in "${nodes[@]}"; do
  IFS='|' read -r name host port data_root <<< "$entry"
  printf '\n=== %s (zjl@%s:%s) ===\n' "$name" "$host" "$port"
  if ! ssh -i "$key_file" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 -p "$port" "zjl@$host" \
    "printf 'hostname='; hostname; printf 'os='; . /etc/os-release 2>/dev/null && printf '%s' \"\$PRETTY_NAME\" || printf 'unknown'; printf '\npython='; python3 --version 2>&1; printf 'docker='; docker --version 2>&1; printf 'data='; df -h '$data_root' | tail -n 1; printf 'nvidia='; nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader 2>&1 || true; if docker info >/dev/null 2>&1; then printf 'docker-access=direct\n'; docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '\"nvidia\"' && printf 'nvidia-runtime=present\n' || printf 'nvidia-runtime=missing\n'; else printf 'docker-access=sudo-required\n'; printf 'nvidia-runtime=not-checked-without-sudo\n'; fi"; then
    printf 'status=UNREACHABLE_OR_KEY_REQUIRED\n'
  fi
done
