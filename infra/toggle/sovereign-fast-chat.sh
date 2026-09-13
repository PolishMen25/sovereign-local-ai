#!/bin/bash
# Mode "chat rapide" (turbo) pour le 14B, à lancer sur l'hôte pve-ml-master.
#
#   sovereign-fast-chat on      -> met l'entraînement CORE-30M en pause (SIGSTOP,
#                                  run conservé) et donne les 2 sockets au 14B
#                                  (--numa distribute, 40 threads) => ~9-11 tok/s
#   sovereign-fast-chat off     -> rebascule le 14B en isolé (socket 0) et reprend
#                                  l'entraînement (SIGCONT) => état normal ~6 tok/s
#   sovereign-fast-chat status  -> état courant + petit bench
#
# Ne tue jamais l'entraînement (SIGSTOP/SIGCONT uniquement). Réversible.
set -euo pipefail

CONF=/etc/pve/lxc/101.conf
SVC=/etc/systemd/system/sovereign-chat-14b.service
TRAIN_PATTERN='train_core'   # process d'entraînement dans CT 102
CT_TRAIN=102
CT_CHAT=101

usage() { echo "usage: $0 {on|off|status}"; exit 1; }
[ $# -eq 1 ] || usage

cg_chat() {
  for p in "/sys/fs/cgroup/lxc/${CT_CHAT}" "/sys/fs/cgroup/lxc/${CT_CHAT}/ns"; do
    [ -w "$p/cpuset.cpus" ] && { echo "$p"; return 0; }
  done
  return 1
}

apply_cpuset() {  # $1=cpus $2=mems ; live si possible, sinon conf+reboot
  local cpus="$1" mems="$2" cg
  sed -i "s/^lxc.cgroup2.cpuset.cpus:.*/lxc.cgroup2.cpuset.cpus: ${cpus}/" "$CONF"
  sed -i "s/^lxc.cgroup2.cpuset.mems:.*/lxc.cgroup2.cpuset.mems: ${mems}/" "$CONF"
  if cg=$(cg_chat); then
    echo "$cpus" > "$cg/cpuset.cpus"; echo "$mems" > "$cg/cpuset.mems"
    echo "  cpuset live: $cpus / mems $mems"; return 0
  fi
  echo "  cgroup live indisponible -> pct reboot ${CT_CHAT} pour appliquer"; pct reboot "$CT_CHAT"; NEED_REBOOTED=1
}

restart_14b() {  # ne redémarre que le service 14B si le conteneur n'a pas été rebooté
  [ "${NEED_REBOOTED:-0}" = 1 ] && return 0
  pct exec "$CT_CHAT" -- systemctl daemon-reload
  pct exec "$CT_CHAT" -- systemctl restart sovereign-chat-14b
}

wait_14b() {
  for _ in $(seq 1 30); do
    if pct exec "$CT_CHAT" -- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/health 2>/dev/null | grep -q 200; then
      echo "  14B prêt"; return 0
    fi
    sleep 4
  done
  echo "  14B pas encore prêt (chargement du modèle)"
}

set_service_turbo() {  # distribute + 40 threads
  pct exec "$CT_CHAT" -- sed -i \
    -e 's/--numa numactl/--numa distribute/' \
    -e 's/--threads 16 /--threads 40 /' \
    -e 's/--threads-batch 20/--threads-batch 40/' "$SVC"
}
set_service_normal() {  # numactl + 16 threads
  pct exec "$CT_CHAT" -- sed -i \
    -e 's/--numa distribute/--numa numactl/' \
    -e 's/--threads 40 /--threads 16 /' \
    -e 's/--threads-batch 40/--threads-batch 20/' "$SVC"
}

bench_14b() {
  pct exec "$CT_CHAT" -- bash -c 'curl -s http://127.0.0.1:8081/completion -H "Content-Type: application/json" -d "{\"prompt\":\"Explique en detail le protocole TCP.\",\"n_predict\":96,\"cache_prompt\":false}"' \
    | grep -oE '"predicted_per_second":[0-9.]+' || echo "(bench indisponible)"
}

training_state() {
  pct exec "$CT_TRAIN" -- bash -c "ps -o state= -C python 2>/dev/null | grep -q T && echo 'PAUSÉ' || (pgrep -f '$TRAIN_PATTERN' >/dev/null && echo 'EN COURS' || echo 'ABSENT')"
}

case "$1" in
  on)
    echo "== TURBO ON =="
    echo "- pause entraînement CORE-30M"
    pct exec "$CT_TRAIN" -- bash -c "pkill -STOP -f '$TRAIN_PATTERN' && echo '  training STOPPED' || echo '  aucun process training'"
    echo "- 14B sur les 2 sockets"
    apply_cpuset "0-79" "0-1"
    set_service_turbo
    restart_14b
    wait_14b
    echo "- débit :"; bench_14b
    echo "== turbo actif (fais 'off' quand tu as fini pour reprendre l'entraînement) =="
    ;;
  off)
    echo "== TURBO OFF =="
    echo "- 14B en isolé (socket 0)"
    set_service_normal
    apply_cpuset "0-19,40-59" "0"
    restart_14b
    wait_14b
    echo "- reprise entraînement CORE-30M"
    pct exec "$CT_TRAIN" -- bash -c "pkill -CONT -f '$TRAIN_PATTERN' && echo '  training RESUMED' || echo '  aucun process training'"
    echo "- débit :"; bench_14b
    echo "== état normal rétabli =="
    ;;
  status)
    echo "== ÉTAT =="
    echo -n "entraînement CORE-30M : "; training_state
    echo -n "cpuset CT101 : "; { grep -E '^lxc.cgroup2.cpuset' "$CONF" || true; } | tr '\n' ' '; echo
    echo -n "service 14B : "; { pct exec "$CT_CHAT" -- grep -oE '\-\-numa [a-z]+|\-\-threads [0-9]+' "$SVC" || true; } | tr '\n' ' '; echo
    echo -n "débit 14B : "; bench_14b
    ;;
  *) usage ;;
esac
