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
- fichier régulier (pas de lien symbolique), au plus 16 384 octets, non
  modifiable par le groupe ni par les autres, appartenant à `root` ou au compte
  du service.

Les messages de refus nomment la règle violée, jamais le chemin ni une valeur.

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

## Étape 2 — valider avec le chargeur de la nouvelle révision

Le chargeur ne dépend que de la bibliothèque standard et s'exécute seul. Copier
`services/common/private_endpoints.py` de la nouvelle révision dans un
répertoire temporaire du conteneur, lisible par les comptes de service (par
exemple avec `pct push ... --perms 0644` depuis l'hôte), puis valider **sous
le compte de chaque service** pour éprouver aussi les droits de lecture :

```sh
F=/etc/sovereign-endpoints/private-endpoints.json
runuser -u sovereign -- env SOVEREIGN_PRIVATE_ENDPOINTS_FILE="$F" \
  python3 -B /tmp/private_endpoints.py --check --require core_inference --require qwen_coder
runuser -u sovereign-arena -- env SOVEREIGN_PRIVATE_ENDPOINTS_FILE="$F" \
  python3 -B /tmp/private_endpoints.py --check --require qwen_coder
```

Dans le conteneur CORE, en `root` : `--check --require core_inference`.
Résultat attendu : `valid: ...` suivi des seuls noms, code de sortie 0. Tout
`refused: ...` (code 2) arrête la migration : corriger le fichier et relancer.
`private endpoint file is unavailable` alors que le fichier existe signale en
général un répertoire non traversable ou un fichier illisible par le compte.
Supprimer ensuite la copie temporaire du module.

## Étape 3 — déclarer le fichier dans les unités

Ajouter la variable par un fichier de surcharge, sans toucher aux unités
existantes. L'ancien code ignore cette variable : l'étape est sans effet tant
que le nouveau code n'est pas déployé.

```sh
for unit in sovereign-gateway-web sovereign-arena; do   # conteneur du sas
  mkdir -p "/etc/systemd/system/$unit.service.d"
  printf '[Service]\nEnvironment=SOVEREIGN_PRIVATE_ENDPOINTS_FILE=/etc/sovereign-endpoints/private-endpoints.json\n' \
    > "/etc/systemd/system/$unit.service.d/30-private-endpoints.conf"
done
systemctl daemon-reload
```

Même opération dans le conteneur CORE pour `sovereign-core-inference`. Les
modèles d'unités du dépôt (`infra/gateway`, `infra/arena`) portent déjà cette
ligne ; la surcharge est alors redondante mais sans conflit.

Les anciennes variables restent tolérées à une condition :
`SOVEREIGN_CORE_ENDPOINT` et `SOVEREIGN_QWEN_ENDPOINT`, si elles sont définies,
doivent être strictement identiques à l'URL `http://<host>:<port>` du fichier
privé (sans barre finale) ; `SOVEREIGN_CORE_PORT` doit égaler le port
configuré. Sinon le service refuse de démarrer.

## Étape 4 — déployer le code puis vérifier

Déployer la révision selon la procédure habituelle, puis redémarrer les
services concernés un par un et vérifier chacun avant de passer au suivant :

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

Créer ce fichier **avant** de mettre à jour la copie du dépôt vers laquelle
pointe la commande installée sur l'hôte. Vérifier ensuite avec
`sovereign-fast-chat status` : l'état s'affiche sans ligne `refus :`.

## Retour arrière

- **Service qui refuse de démarrer** : lire la raison dans le journal (elle ne
  contient ni chemin ni valeur), corriger le fichier privé, relancer
  `--check`, puis redémarrer. Ne jamais contourner en réintroduisant une
  adresse dans le code ou une valeur par défaut.
- **Retour à la révision précédente** : redéployer l'ancienne révision et
  redémarrer. L'ancien code ignore le fichier privé et la variable
  `SOVEREIGN_PRIVATE_ENDPOINTS_FILE` ; comme la migration ne change aucune
  adresse, il retrouve immédiatement ses anciennes valeurs. Le fichier privé
  et les surcharges peuvent rester en place pour la tentative suivante.
- **Interrupteur « chat rapide »** : revenir à l'ancienne version du script
  dans la copie du dépôt de l'hôte ; `/etc/sovereign/fast-chat.conf` peut
  rester.

## Après la migration

- Retirer, quand tout fonctionne, les anciennes variables
  `SOVEREIGN_CORE_ENDPOINT` et `SOVEREIGN_QWEN_ENDPOINT` pour garder une seule
  source de vérité (facultatif, elles restent vérifiées tant qu'elles existent).
- Changer une adresse revient à modifier le fichier privé, relancer `--check`
  et redémarrer : aucune modification de code.
- Ne jamais copier le fichier privé ni ses valeurs dans Git, une issue, une PR
  ou un journal. `tests/test_no_private_infrastructure_identifiers.py` refuse
  tout littéral IPv4 privé ou partagé, IPv6 unique-local, chemin d'hyperviseur
  par invité ou identifiant de conteneur dans les fichiers suivis. Les noms
  d'hôte ne sont pas détectables automatiquement : les relire à la revue.
- L'historique Git conserve les anciennes valeurs, qui sont des adresses
  privées non routables ; D-036 ne décide aucune réécriture d'historique.
