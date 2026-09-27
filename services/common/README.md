# Utilitaires communs

Ce dossier regroupe de petits modules sans état, dépendant de la seule
bibliothèque standard, partagés par plusieurs services sans créer de dépendance
entre leurs zones.

## Points de terminaison privés (D-036)

`private_endpoints.py` lit la configuration privée des points de terminaison
internes. Le dépôt public ne contient aucune adresse interne : chaque conteneur
qui en a besoin reçoit un fichier JSON installé hors Git, désigné par la
variable `SOVEREIGN_PRIVATE_ENDPOINTS_FILE` (chemin absolu). Le contrat est
`schemas/private-endpoints.schema.json` ; l'exemple
`configs/runtime/private-endpoints.example.json` utilise volontairement des
adresses de documentation RFC 5737 que le chargeur refuse : il ne peut pas être
installé tel quel.

Règles appliquées, toutes en échec fermé :

- noms fermés : `core_inference` et `qwen_coder` ; toute clé inconnue ou en
  trop est refusée ;
- `host` est une adresse IPv4 littérale et canonique dans une plage privée
  RFC 1918 ou de boucle locale ; nom d'hôte, IPv6, adresse publique, de
  documentation, partagée, joker, de réseau ou de diffusion sont refusés ;
- `port` est un entier de 1 à 65535 ; deux noms ne partagent jamais la même
  paire adresse/port ;
- fichier régulier (pas de lien symbolique), de 1 à 16 384 octets, JSON strict
  sans clé dupliquée ; sous POSIX, il n'est modifiable ni par le groupe ni par
  les autres et appartient à `root` ou au compte du service.

Les messages d'erreur nomment la règle violée, jamais le chemin du fichier ni
une valeur lue. Les clients (`CoreClient`, `QwenClient`, moteur Qwen de
l'arène) conservent un épinglage exact sur l'URL issue de ce fichier : les
anciennes variables `SOVEREIGN_CORE_ENDPOINT` et `SOVEREIGN_QWEN_ENDPOINT`
restent facultatives, mais si elles sont présentes elles doivent être
identiques, sinon le service refuse de démarrer. Le serveur CORE écoute sur
l'adresse configurée ; `SOVEREIGN_CORE_PORT`, si présent, doit égaler le port
configuré. Aucun repli vers `0.0.0.0` ni vers une ancienne valeur codée en dur.

Validation avant déploiement, sans afficher le contenu :

```sh
SOVEREIGN_PRIVATE_ENDPOINTS_FILE=/chemin/absolu/private-endpoints.json \
  python3 -B services/common/private_endpoints.py --check --require core_inference
```

La procédure complète est décrite dans
`docs/operations/private-endpoints-migration.md`.
