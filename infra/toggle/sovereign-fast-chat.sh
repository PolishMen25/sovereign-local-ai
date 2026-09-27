#!/bin/bash
# Mode "chat rapide" (turbo) pour le 14B, à lancer en root sur l'hôte Proxmox
# du nœud de calcul.
#
#   sovereign-fast-chat on      -> met l'entraînement CORE-30M en pause (SIGSTOP,
#                                  run conservé) et donne les 2 sockets au 14B
#                                  (--numa distribute, 40 threads) => ~9-11 tok/s
#   sovereign-fast-chat off     -> rebascule le 14B en isolé (socket 0) et reprend
#                                  l'entraînement (SIGCONT) => état normal ~6 tok/s
#   sovereign-fast-chat status  -> état courant + petit bench
#
# Ne tue jamais l'entraînement (SIGSTOP/SIGCONT uniquement). Réversible.
#
# D-036 : les identifiants des conteneurs ne sont pas dans le dépôt. Ils sont lus
# dans un fichier privé hors Git (par défaut /etc/sovereign/fast-chat.conf,
# modifiable par SOVEREIGN_FAST_CHAT_CONFIG), appartenant à root, non modifiable
# par le groupe ni par les autres, et contenant exactement deux lignes :
#   SOVEREIGN_CT_CHAT=<identifiant du conteneur du 14B>
#   SOVEREIGN_CT_TRAIN=<identifiant du conteneur d'entraînement>
# Le fichier n'est jamais exécuté (pas de `source`). Sans fichier valide : refus.
set -euo pipefail

SVC=/etc/systemd/system/sovereign-chat-14b.service
TRAIN_PATTERN='train_core'   # process d'entraînement dans le conteneur d'entraînement
PRIVATE_CONFIG=${SOVEREIGN_FAST_CHAT_CONFIG:-/etc/sovereign/fast-chat.conf}

usage() { echo "usage: $0 {on|off|status}"; exit 1; }
[ $# -eq 1 ] || usage

refuse() { echo "refus : $1 (voir docs/operations/private-endpoints-migration.md)" >&2; exit 2; }

load_private_ids() {  # lecture stricte, sans afficher le contenu
  local line key value seen=""
  [ -f "$PRIVATE_CONFIG" ] && [ ! -L "$PRIVATE_CONFIG" ] || refuse "configuration privée absente ou non régulière"
  [ "$(stat -c '%u' "$PRIVATE_CONFIG")" = 0 ] || refuse "la configuration privée doit appartenir à root"
  (( (8#$(stat -c '%a' "$PRIVATE_CONFIG") & 8#022) == 0 )) || refuse "configuration privée modifiable par le groupe ou les autres"
  CT_CHAT=""; CT_TRAIN=""
  while IFS= read -r line || [ -n "$line" ]; do
    key=${line%%=*}; value=${line#*=}
    [ "$key" != "$line" ] || refuse "ligne inattendue dans la configuration privée"
    [[ "$value" =~ ^[1-9][0-9]{2,8}$ ]] || refuse "identifiant de conteneur invalide"
    case " $seen " in *" $key "*) refuse "clé dupliquée dans la configuration privée" ;; esac
    seen="$seen $key"
    case "$key" in
      SOVEREIGN_CT_CHAT) CT_CHAT=$value ;;
      SOVEREIGN_CT_TRAIN) CT_TRAIN=$value ;;
      *) refuse "clé inattendue dans la configuration privée" ;;
    esac
  done < "$PRIVATE_CONFIG"
  [ -n "$CT_CHAT" ] && [ -n "$CT_TRAIN" ] || refuse "identifiants de conteneurs manquants"
  [ "$CT_CHAT" != "$CT_TRAIN" ] || refuse "les deux conteneurs doivent être distincts"
}

load_private_ids
CONF="/etc/pve/lxc/${CT_CHAT}.conf"
[ -f "$CONF" ] || refuse "configuration Proxmox du conteneur du 14B introuvable"

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
    echo -n "cpuset conteneur 14B : "; { grep -E '^lxc.cgroup2.cpuset' "$CONF" || true; } | tr '\n' ' '; echo
    echo -n "service 14B : "; { pct exec "$CT_CHAT" -- grep -oE '\-\-numa [a-z]+|\-\-threads [0-9]+' "$SVC" || true; } | tr '\n' ' '; echo
    echo -n "débit 14B : "; bench_14b
    ;;
  *) usage ;;
esac
