# Sas d'interface local

Le sas exécute l'interface authentifiée sur la boucle locale et relaie les
questions vers un moteur local explicitement identifié. Tant que CORE-700M ne
possède pas de poids approuvés, le seul moteur autorisé est BOOTSTRAP via
llama.cpp sur `127.0.0.1`.

Le paquet système `python3-argon2` est requis pour Argon2id. Aucun repli vers un
hachage plus faible n'est permis. Le fichier
`/opt/sovereign/credentials/gateway-web.env` est créé hors Git en mode `0600`
et contient un jeton de première installation aléatoire d'au moins 32
caractères. Le propriétaire saisit ce jeton et choisit son mot de passe dans le
navigateur ; le mot de passe n'est jamais envoyé dans Git ou un journal.

La mémoire SQLite reste active dans `/var/lib/sovereign-gateway`. Lorsqu'un
montage de sauvegarde dédié est fourni, `sovereign-memory-backup.timer` appelle
un outil local de copie SQLite cohérente toutes les quinze minutes. Le manifeste
de sauvegarde ne contient aucun message ; l'outil n'est exposé ni par HTTP ni
par MCP. Le service écoute uniquement sur loopback. L'accès HTTPS LAN
ou tailnet doit être réalisé par un reverse proxy approuvé ; ne jamais modifier
`SOVEREIGN_WEB_HOST` pour exposer directement le serveur Python.

`sovereign-knowledge-index.service` construit avant le démarrage de la
passerelle un index lexical local depuis les seuls documents Markdown livrés
avec la révision installée. Il ne lit pas RAW, VALIDATED, le partage Synology
ou les conversations. Toute extension vers un corpus personnel ou validé exige
un manifeste et une approbation distincts.

## Contrats disponibles

- `GET /healthz` et `GET /v1/setup-status` : état minimal sans secret ;
- `POST /v1/setup` : initialisation unique avec jeton d'installation ;
- `POST /v1/login` et `POST /v1/logout` : cookie sécurisé et CSRF ;
- `POST /v1/chat` : réponse du moteur local avec champ `engine` obligatoire ;
- `GET /v1/conversations` et export : mémoire privée authentifiée ;
- `DELETE /v1/conversations/{id}` : suppression avec reçu d'audit sans contenu.
