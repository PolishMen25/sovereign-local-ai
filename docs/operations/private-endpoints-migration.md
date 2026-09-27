# Migration vers les points de terminaison privés hors Git (D-036)

D-036 sort du dépôt public les adresses, noms d'hôte, identifiants de
conteneurs et chemins d'hyperviseur internes. L'épinglage exact des points de
terminaison reste un contrôle de sécurité : la valeur épinglée vient désormais
d'un fichier privé installé hors Git sur chaque machine concernée.

Le nouveau code **refuse de démarrer** un moteur configuré (jeton présent) sans
fichier privé valide. Il n'existe aucune valeur par défaut, aucun repli vers
`0.0.0.0` ni vers les anciennes adresses. Le fichier privé doit donc être
installé et validé **avant** le déploiement du code. Les valeurs à y placer
sont celles déjà en service : la migration ne change aucune adresse, aucun port
et aucune règle de pare-feu.

Ce document ne contient aucune valeur réelle. Les brouillons de configuration
du propriétaire sont conservés hors de tout dépôt.

## Qui est concerné

| Emplacement | Composant | Fichier privé | Contenu |
|---|---|---|---|
| Conteneur du sas | `sovereign-gateway-web`, `sovereign-arena` | `/etc/sovereign-endpoints/private-endpoints.json`, `root:sovereign`, `0640` | `core_inference` si `SOVEREIGN_CORE_TOKEN` est défini ; `qwen_coder` si `SOVEREIGN_QWEN_TOKEN` est défini |
| Conteneur CORE | `sovereign-core-inference` | `/etc/sovereign-endpoints/private-endpoints.json`, `root:root`, `0600` | `core_inference` (adresse et port d'écoute) |
| Conteneur Qwen | `llama-server` | aucun | l'adresse d'écoute reste dans l'unité locale, déjà hors Git |
| Hôte Proxmox du nœud de calcul | `sovereign-fast-chat` | `/etc/sovereign/fast-chat.conf`, `root:root`, `0600` | identifiants du conteneur du 14B et du conteneur d'entraînement |

Le contrat JSON est `schemas/private-endpoints.schema.json`. L'exemple
`configs/runtime/private-endpoints.example.json` utilise des adresses de
documentation RFC 5737 que le chargeur refuse : il sert de modèle, jamais de
fichier installé.

## Règles du fichier JSON

- exactement `schema_version` (`private-endpoints.v1`) et `endpoints` ;
- noms autorisés : `core_inference`, `qwen_coder` ; chaque entrée contient
  exactement `host` et `port` ;
- `host` : adresse IPv4 littérale canonique, privée RFC 1918 ou de boucle
  locale ; un nom d'hôte, une adresse IPv6, publique, de documentation,
  partagée ou joker est refusé ;
- `port` : entier de 1 à 65535 ; deux noms ne partagent jamais la même paire ;
- fichier régulier (pas de lien symbolique), au plus 16 384 octets,
  appartenant à `root` et non modifiable par le groupe ni par les autres ;
- répertoire parent appartenant à `root` et non modifiable par le groupe ni
  par les autres : un compte de service ne peut ni réécrire son propre
  épinglage ni remplacer le fichier.

Les messages de refus nomment la règle violée, jamais le chemin ni une valeur.
Un service qui refuse sa configuration s'arrête avec le code 78 (`EX_CONFIG`) ;
les unités déclarent `RestartPreventExitStatus=78` et restent en échec au lieu
de redémarrer en boucle sur une faute statique.

## Étape 1 — créer le fichier privé sur chaque conteneur concerné

Le fichier ne contient aucun secret, seulement des adresses privées : il est
placé dans un répertoire dédié, `/etc/sovereign-endpoints`, traversable par les
comptes de service, plutôt que dans `/opt/sovereign/credentials` dont les
droits sont réservés aux secrets et ne doivent pas être élargis.

Dans le conteneur du sas, en `root`, en remplaçant les marqueurs par les
valeurs en service (celles de `SOVEREIGN_CORE_ENDPOINT` et de l'écoute de
`llama-server` dans le conteneur Qwen) :

```sh
install -d -m 0755 -o root -g root /etc/sovereign-endpoints
umask 077
cat > /etc/sovereign-endpoints/private-endpoints.json <<'EOF'
{
  "schema_version": "private-endpoints.v1",
  "endpoints": {
    "core_inference": { "host": "<IPv4 privée du conteneur CORE>", "port": <port CORE> },
    "qwen_coder": { "host": "<IPv4 privée du conteneur Qwen>", "port": <port Qwen> }
  }
}
EOF
chown root:sovereign /etc/sovereign-endpoints/private-endpoints.json
chmod 0640 /etc/sovereign-endpoints/private-endpoints.json
```

Le groupe `sovereign` permet la lecture par la passerelle (`sovereign`) et par
l'arène (`sovereign-arena`, groupe `sovereign`). Dans le conteneur CORE, créer
le même répertoire dédié ; le fichier n'y contient que `core_inference`, avec
`chown root:root` et `chmod 0600` (le service s'exécute en `root`).

## Étape 2 — valider avec la nouvelle révision, dans l'environnement de chaque unité

Le contrôle doit reproduire ce que chaque service vérifiera au démarrage : le
fichier privé **et** les anciennes variables `SOVEREIGN_CORE_ENDPOINT`,
`SOVEREIGN_QWEN_ENDPOINT` et `SOVEREIGN_CORE_PORT`, telles que les chargent les
`EnvironmentFile=` et `Environment=` de l'unité, surcharges comprises.
L'ancien code acceptait des formes approchées (préfixe d'adresse, barre
finale) ; le nouveau exige l'égalité stricte. Un contrôle limité au fichier
JSON laisserait passer une barre finale dans un fichier d'environnement, et le
service refuserait de démarrer juste après la bascule.

1. Préparer la nouvelle révision dans son propre répertoire de version, comme
   pour tout déploiement, **sans basculer** le lien `/opt/sovereign/app` qui
   désigne la révision en service. Ce répertoire appartient à `root` et n'est
   modifiable ni par le groupe ni par les autres.
2. Exécuter le chargeur de cette révision par son chemin, en mode isolé
   (`python3 -I -B`) : `-I` retire le répertoire du script et le répertoire
   courant de `sys.path` et ignore les variables `PYTHON*`, si bien qu'aucun
   module homonyme déposé ailleurs ne remplace la bibliothèque standard. Ne
   jamais copier le module dans `/tmp` ni dans un répertoire modifiable par un
   compte de service : il s'y exécuterait sous le compte du service, voire en
   `root`.
3. Lancer le contrôle par `systemd-run` avec l'utilisateur, le groupe, les
   fichiers d'environnement et les variables de l'unité elle-même, relus par
   `systemctl show`. systemd lit les fichiers d'environnement en `root`, comme
   au démarrage du service : leurs secrets ne passent jamais par la ligne de
   commande et rien de leur contenu n'est affiché.

En `root`, dans le conteneur concerné (bash) :

```bash
F=/etc/sovereign-endpoints/private-endpoints.json
R='<répertoire de la nouvelle révision préparée>'

check_unit() {  # $1 : unité ; $2 : interpréteur de son ExecStart ; puis les --require
  local unit=$1 python=$2 file flag value
  shift 2
  local -a props=()
  value=$(systemctl show -P User "$unit"); [ -n "$value" ] && props+=(-p "User=$value")
  value=$(systemctl show -P Group "$unit"); [ -n "$value" ] && props+=(-p "Group=$value")
  while read -r file flag; do
    [ -n "$file" ] || continue
    [ "$flag" = "(ignore_errors=yes)" ] && file="-$file"
    props+=(-p "EnvironmentFile=$file")
  done < <(systemctl show -P EnvironmentFiles "$unit")
  value=$(systemctl show -P Environment "$unit"); [ -n "$value" ] && props+=(-p "Environment=$value")
  systemd-run --quiet --wait --pipe --collect "${props[@]}" \
    -p "Environment=SOVEREIGN_PRIVATE_ENDPOINTS_FILE=$F" \
    "$python" -I -B "$R/services/common/private_endpoints.py" --check --legacy-env "$@"
}

# Conteneur du sas (un --require par jeton défini, voir le tableau) :
check_unit sovereign-gateway-web /usr/bin/python3 --require core_inference --require qwen_coder
check_unit sovereign-arena /usr/bin/python3 --require qwen_coder
```

Dans le conteneur CORE : `check_unit sovereign-core-inference '<interpréteur
de son ExecStart>' --require core_inference` (le premier mot de `ExecStart=`
dans `systemctl cat sovereign-core-inference`).

Résultat attendu, code de sortie 0 : `valid: ...` puis
`legacy variables matching: ...`, qui ne citent que des noms. Tout
`refused: ...` (code 2) arrête la migration :

- `SOVEREIGN_..._ENDPOINT does not match the pinned endpoint` : dans le
  fichier d'environnement ou la surcharge qui la définit, écrire exactement
  `http://<host>:<port>` du fichier privé, ou supprimer la variable ;
- `SOVEREIGN_CORE_PORT does not match the pinned endpoint` : même correction
  pour le port ;
- `private endpoint file is unavailable` alors que le fichier existe : en
  général un répertoire non traversable ou un fichier illisible par le compte ;
- `must be owned by root` ou `must not be group- or world-writable` : corriger
  le propriétaire ou les droits du fichier ou de son répertoire.

Relancer le contrôle après chaque correction, et de nouveau juste avant la
bascule si un fichier d'environnement a changé entre-temps.

## Étape 3 — déclarer le fichier dans les unités

Ajouter la variable par un fichier de surcharge, sans toucher aux unités
existantes. L'ancien code ignore cette variable : l'étape est sans effet tant
que le nouveau code n'est pas déployé.

```sh
for unit in sovereign-gateway-web sovereign-arena; do   # conteneur du sas
  mkdir -p "/etc/systemd/system/$unit.service.d"
  printf '[Service]\nEnvironment=SOVEREIGN_PRIVATE_ENDPOINTS_FILE=/etc/sovereign-endpoints/private-endpoints.json\nRestartPreventExitStatus=78\n' \
    > "/etc/systemd/system/$unit.service.d/30-private-endpoints.conf"
done
systemctl daemon-reload
```

Même opération dans le conteneur CORE pour `sovereign-core-inference`. Les
modèles d'unités du dépôt (`infra/gateway`, `infra/arena`) portent déjà ces
deux lignes ; la surcharge est alors redondante mais sans conflit.
`RestartPreventExitStatus=78` évite la boucle de redémarrage (toutes les 5 s
pour la passerelle, toutes les 30 s pour l'arène, qui réécrirait chaque fois
son état « arrêtée ») quand la configuration est refusée : l'unité reste en
échec jusqu'à correction.

Les anciennes variables restent tolérées à une condition :
`SOVEREIGN_CORE_ENDPOINT` et `SOVEREIGN_QWEN_ENDPOINT`, si elles sont définies,
doivent être strictement identiques à l'URL `http://<host>:<port>` du fichier
privé (sans barre finale) ; `SOVEREIGN_CORE_PORT` doit égaler le port
configuré. Sinon le service refuse de démarrer.

## Étape 4 — déployer le code puis vérifier

Basculer vers la révision contrôlée à l'étape 2 selon la procédure habituelle,
puis redémarrer les services concernés un par un et vérifier chacun avant de
passer au suivant :

```sh
systemctl restart sovereign-gateway-web
systemctl is-active sovereign-gateway-web
journalctl -u sovereign-gateway-web -n 20 --no-pager   # aucun « refusing to start »
systemctl restart sovereign-arena
journalctl -u sovereign-arena -n 20 --no-pager         # aucun « arena refused to start »
```

Puis, depuis le navigateur : la page de santé montre les moteurs attendus
disponibles, la page de l'arène n'affiche pas « configuration des moteurs
refusée », et une question envoyée à Qwen Coder reçoit une réponse. Le service
CORE, s'il est réactivé, doit écouter sur l'adresse configurée
(`ss -ltn` dans son conteneur) et nulle part ailleurs.

## Étape 5 — hôte Proxmox : interrupteur « chat rapide »

`sovereign-fast-chat` lit désormais les identifiants des conteneurs dans
`/etc/sovereign/fast-chat.conf` (chemin modifiable par
`SOVEREIGN_FAST_CHAT_CONFIG`). Le fichier n'est jamais exécuté ; il contient
exactement deux lignes, sans commentaire ni ligne vide :

```sh
install -d -m 0700 /etc/sovereign
umask 077
printf 'SOVEREIGN_CT_CHAT=<id du conteneur du 14B>\nSOVEREIGN_CT_TRAIN=<id du conteneur d entraînement>\n' \
  > /etc/sovereign/fast-chat.conf
chmod 0600 /etc/sovereign/fast-chat.conf
```

Précondition, **avant toute mise à jour** de la copie du dépôt vers laquelle
pointe la commande installée sur l'hôte : lancer `sovereign-fast-chat status`
avec l'ancienne version et vérifier que l'entraînement est `EN COURS` (mode
turbo inactif) ; sinon lancer d'abord `sovereign-fast-chat off`. La nouvelle
version refuse toute commande, `off` compris, tant que
`/etc/sovereign/fast-chat.conf` manque ou est invalide : mise à jour en mode
turbo, elle laisserait l'entraînement suspendu (SIGSTOP) sans moyen simple de
le reprendre.

Ordre : ramener le mode normal, créer le fichier ci-dessus, mettre à jour la
copie du dépôt, puis vérifier avec `sovereign-fast-chat status` que l'état
s'affiche sans ligne `refus :` avant tout nouveau `on`.

## Retour arrière

- **Service qui refuse de démarrer** : l'unité reste en échec (code 78, sans
  boucle de redémarrage). Lire la raison dans le journal (elle ne contient ni
  chemin ni valeur), corriger le fichier privé ou la variable en cause,
  relancer le contrôle de l'étape 2, puis `systemctl reset-failed <unité>` et
  redémarrer. Ne jamais contourner en réintroduisant une adresse dans le code
  ou une valeur par défaut.
- **Retour à la révision précédente** : redéployer l'ancienne révision et
  redémarrer. L'ancien code ignore le fichier privé et la variable
  `SOVEREIGN_PRIVATE_ENDPOINTS_FILE` ; comme la migration ne change aucune
  adresse, il retrouve immédiatement ses anciennes valeurs. Le fichier privé
  et les surcharges peuvent rester en place pour la tentative suivante.
- **Interrupteur « chat rapide »** : revenir à l'ancienne version du script
  dans la copie du dépôt de l'hôte ; `/etc/sovereign/fast-chat.conf` peut
  rester.
- **Entraînement resté suspendu** (la nouvelle version refuse `off` alors que
  le mode turbo était actif) : de préférence, créer ou corriger
  `/etc/sovereign/fast-chat.conf` puis relancer `sovereign-fast-chat off`, ou
  revenir à l'ancienne version du script et lancer `off`. En dernier recours,
  reprendre l'entraînement à la main, en `root` sur l'hôte :
  `pct exec <id du conteneur d'entraînement> -- pkill -CONT -f train_core` ;
  le 14B reste alors sur les deux sockets jusqu'au prochain `off` réussi.

## Après la migration

- Retirer, quand tout fonctionne, les anciennes variables
  `SOVEREIGN_CORE_ENDPOINT` et `SOVEREIGN_QWEN_ENDPOINT` pour garder une seule
  source de vérité (facultatif, elles restent vérifiées tant qu'elles existent).
- Changer une adresse revient à modifier le fichier privé, relancer le
  contrôle de l'étape 2 et redémarrer : aucune modification de code.
- Ne jamais copier le fichier privé ni ses valeurs dans Git, une issue, une PR
  ou un journal. `.gitignore` écarte `private-endpoints.json`,
  `*.private-endpoints.json` et `fast-chat.conf` déposés par erreur dans une
  copie du dépôt. `tests/test_no_private_infrastructure_identifiers.py` refuse
  tout littéral IPv4 privé ou partagé (formes à zéros de tête comprises), IPv6
  unique-local, chemin d'hyperviseur par invité ou identifiant de conteneur
  (`CT <id>`, `ct-<id>`, `vmid <id>`, `conteneur <id>`, arguments de
  `pct`/`qm`) dans les fichiers suivis ; les quatre exceptions documentées sont
  épinglées sur leur nombre exact de littéraux. Les noms d'hôte ne sont pas
  détectables automatiquement : les relire à la revue.
- L'historique Git conserve les anciennes valeurs, qui sont des adresses
  privées non routables ; D-036 ne décide aucune réécriture d'historique.
