#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Read-only, local-on-target W4-09 inventory. It writes only to stdout/stderr.

set -u
set -o pipefail

usage() {
  printf '%s\n' \
    'usage: bash preflight-readonly.sh --expected-host persvati --role collector' \
    '       bash preflight-readonly.sh --expected-host hbox --role replica' >&2
}

expected_host=''
role=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --expected-host)
      [ "$#" -ge 2 ] || { usage; exit 64; }
      expected_host=$2
      shift 2
      ;;
    --role)
      [ "$#" -ge 2 ] || { usage; exit 64; }
      role=$2
      shift 2
      ;;
    *)
      usage
      exit 64
      ;;
  esac
done

case "$expected_host:$role" in
  persvati:collector)
    state_root='/var/lib/joshi/collector'
    probe_root='/var/lib'
    ;;
  hbox:replica)
    state_root='/tank/joshi/spool/replicas/hbox-ciphertext-01/s0-canary-001'
    probe_root='/tank'
    ;;
  *)
    usage
    exit 64
    ;;
esac

clean() {
  printf '%s' "$1" | tr '\n\r\t' '   '
}

emit() {
  printf '%s=%s\n' "$1" "$(clean "${2:-unknown}")"
}

command_state() {
  if command -v "$1" >/dev/null 2>&1; then
    emit "command_$1" present
  else
    emit "command_$1" absent
  fi
}

os_value() {
  key=$1
  awk -F= -v wanted="$key" '
    $1 == wanted {
      value = substr($0, index($0, "=") + 1)
      gsub(/^"|"$/, "", value)
      print value
      exit
    }
  ' /etc/os-release 2>/dev/null
}

path_fact() {
  path=$1
  label=$2
  if [ -e "$path" ]; then
    emit "${label}_exists" yes
    if command -v stat >/dev/null 2>&1; then
      emit "${label}_mode_owner_group" "$(stat -c '%a:%U:%G' "$path" 2>/dev/null || printf unknown)"
    fi
    if command -v findmnt >/dev/null 2>&1; then
      emit "${label}_fstype" "$(findmnt -n -o FSTYPE -T "$path" 2>/dev/null || printf unknown)"
      emit "${label}_mount_options" "$(findmnt -n -o OPTIONS -T "$path" 2>/dev/null || printf unknown)"
    fi
  else
    emit "${label}_exists" no
  fi
}

disk_fact() {
  path=$1
  if ! command -v df >/dev/null 2>&1 || [ ! -e "$path" ]; then
    emit disk_probe unavailable
    return
  fi
  values=$(df -P -B1 "$path" 2>/dev/null | awk 'NR == 2 {print $2 " " $4}')
  total=$(printf '%s\n' "$values" | awk '{print $1}')
  available=$(printf '%s\n' "$values" | awk '{print $2}')
  if [ -z "$total" ] || [ -z "$available" ]; then
    emit disk_probe unavailable
    return
  fi
  twenty_percent=$((total / 5))
  hundred_gib=107374182400
  if [ "$twenty_percent" -gt "$hundred_gib" ]; then
    required=$twenty_percent
  else
    required=$hundred_gib
  fi
  emit disk_total_bytes "$total"
  emit disk_available_bytes "$available"
  emit disk_required_reserve_bytes "$required"
  if [ "$available" -ge "$required" ]; then
    emit disk_stop_floor pass
  else
    emit disk_stop_floor fail
  fi
  inode_values=$(df -P -i "$path" 2>/dev/null | awk 'NR == 2 {print $2 " " $4}')
  emit disk_inodes_total "$(printf '%s\n' "$inode_values" | awk '{print $1}')"
  emit disk_inodes_available "$(printf '%s\n' "$inode_values" | awk '{print $2}')"
}

emit contract joshi.wave4.host_preflight_readonly.v1
emit mutation_authority none
emit network_probe none
emit expected_host "$expected_host"
emit role "$role"
emit state_root "$state_root"

actual_host=$(hostname -s 2>/dev/null || printf unknown)
emit actual_host "$actual_host"
if [ "$actual_host" = "$expected_host" ]; then
  emit hostname_gate pass
else
  emit hostname_gate fail
fi

emit os_id "$(os_value ID)"
emit os_version_id "$(os_value VERSION_ID)"
emit os_pretty_name "$(os_value PRETTY_NAME)"
emit os_support_gate requires_action_time_canonical_release_table_evidence
emit kernel_release "$(uname -r 2>/dev/null || printf unknown)"
emit architecture "$(uname -m 2>/dev/null || printf unknown)"
emit boot_id "$(sed -n '1p' /proc/sys/kernel/random/boot_id 2>/dev/null || printf unknown)"
emit uptime_seconds "$(awk '{printf "%.0f", $1}' /proc/uptime 2>/dev/null || printf unknown)"

if command -v timedatectl >/dev/null 2>&1; then
  emit ntp_synchronized "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || printf unknown)"
else
  emit ntp_synchronized unknown
fi

if getent passwd joshi >/dev/null 2>&1; then
  joshi_entry=$(getent passwd joshi)
  emit service_user present
  emit service_user_uid "$(printf '%s\n' "$joshi_entry" | awk -F: '{print $3}')"
  emit service_user_home "$(printf '%s\n' "$joshi_entry" | awk -F: '{print $6}')"
  emit service_user_shell "$(printf '%s\n' "$joshi_entry" | awk -F: '{print $7}')"
else
  emit service_user absent
fi
if getent group joshi >/dev/null 2>&1; then
  emit service_group present
  emit service_group_gid "$(getent group joshi | awk -F: '{print $3}')"
else
  emit service_group absent
fi

path_fact /etc/joshi etc_joshi
path_fact /usr/local/libexec/joshi binary_parent
path_fact "$state_root" state_root
disk_fact "$probe_root"

mem_available_kib=$(awk '$1 == "MemAvailable:" {print $2}' /proc/meminfo 2>/dev/null)
swap_total_kib=$(awk '$1 == "SwapTotal:" {print $2}' /proc/meminfo 2>/dev/null)
swap_free_kib=$(awk '$1 == "SwapFree:" {print $2}' /proc/meminfo 2>/dev/null)
emit memory_available_kib "${mem_available_kib:-unknown}"
emit swap_total_kib "${swap_total_kib:-unknown}"
emit swap_used_kib "$(( ${swap_total_kib:-0} - ${swap_free_kib:-0} ))"
if [ "$role" = replica ] && [ "${mem_available_kib:-0}" -ge 16777216 ]; then
  emit replica_memory_16gib_gate pass_at_sample
elif [ "$role" = replica ]; then
  emit replica_memory_16gib_gate fail_at_sample
fi
emit memory_psi "$(sed -n '1,2p' /proc/pressure/memory 2>/dev/null | paste -sd ';' - || printf unknown)"
emit io_psi "$(sed -n '1,2p' /proc/pressure/io 2>/dev/null | paste -sd ';' - || printf unknown)"

if command -v systemctl >/dev/null 2>&1; then
  emit systemd_system_state "$(systemctl is-system-running 2>/dev/null || true)"
  emit ufw_unit_state "$(systemctl is-active ufw.service 2>/dev/null || true)"
  emit tailscaled_unit_state "$(systemctl is-active tailscaled.service 2>/dev/null || true)"
  emit joshi_collector_unit_file "$(systemctl is-enabled joshi-collector.service 2>/dev/null || true)"
  emit joshi_replica_unit_file "$(systemctl is-enabled joshi-replica.service 2>/dev/null || true)"
else
  emit systemd_system_state unavailable
fi

if command -v ss >/dev/null 2>&1; then
  wildcard_ports=$(ss -H -ltn 2>/dev/null | awk '
    {
      address = $4
      if (address ~ /^\*:/ || address ~ /^0[.]0[.]0[.]0:/ || address ~ /^\[::\]:/) {
        sub(/^.*:/, "", address)
        print address
      }
    }
  ' | sort -n -u | paste -sd, -)
  emit wildcard_tcp_listener_ports "${wildcard_ports:-none}"
else
  emit wildcard_tcp_listener_ports unavailable
fi

emit tailscale_peer_canary not_run
emit firewall_effective_rules not_read_without_separate_authority
emit listener_change_default none
emit firewall_change_default none
emit tailscale_change_default none

if [ "$role" = replica ]; then
  command_state zpool
  command_state zfs
  if command -v zpool >/dev/null 2>&1; then
    emit tank_health "$(zpool list -H -o health tank 2>/dev/null || printf unavailable)"
    emit tank_capacity "$(zpool list -H -o size,alloc,free tank 2>/dev/null || printf unavailable)"
  fi
  if command -v zfs >/dev/null 2>&1; then
    emit tank_native_encryption "$(zfs get -H -o value encryption tank 2>/dev/null || printf unavailable)"
  fi
  emit tank_special_vdev_redundancy requires_separate_topology_revalidation_and_acceptance
fi

for needed in sha256sum findmnt stat df ss systemctl; do
  command_state "$needed"
done

emit result inventory_only_not_deployment_qualification
