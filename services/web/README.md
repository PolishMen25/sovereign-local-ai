# Interface Web interne

L'interface fournit une première configuration locale, une authentification
Argon2id, des sessions avec cookie sécurisé et CSRF, un chat relié au runtime
BOOTSTRAP loopback, ainsi que la liste, l'export et la suppression des
conversations privées. Elle reste un sas distinct de CORE.

Le champ `engine` de chaque réponse vaut explicitement `BOOTSTRAP`,
`CORE-700M` ou `unavailable`. Il est interdit de présenter BOOTSTRAP comme CORE.
Les requêtes et réponses suivent les schémas `local-chat-request.v1` et
`local-assistant-response.v1`.

`app.py` force une écoute loopback. Le secret de première installation est
injecté hors dépôt par `SOVEREIGN_SETUP_TOKEN` et contient au moins 32
caractères. Les bases d'authentification et de mémoire sont placées sous le
répertoire opérateur `SOVEREIGN_WEB_STATE`. Le client BOOTSTRAP refuse toute URL
autre que loopback, tout proxy et toute redirection.

La route de chat interroge aussi, quand il est présent, un index SQLite/FTS5
local de documents explicitement approuvés. Les extraits sont bornés, leur
provenance est renvoyée dans `citations` et ils sont présentés au modèle comme
des données non exécutables. Ce premier niveau est lexical : aucun vecteur n'est
fabriqué et aucun moteur d'embeddings n'est encore installé. Les profils
d'agents et les actions confirmables ne sont pas raccordés. Une absence
d'Argon2id ou du runtime local provoque un refus sûr ; aucun fournisseur distant
n'est utilisé.

Le service ne doit jamais écouter directement sur le LAN. Un reverse proxy
HTTPS approuvé porte l'accès LAN ou tailnet, tandis que le processus Python
reste sur `127.0.0.1`.

## Interface disponible

Les fichiers statiques locaux de `services/web/static/` fournissent la première
configuration, la connexion, l'historique réouvrable, l'export et la
suppression. Ils n'utilisent ni bibliothèque distante, ni stockage de mot de
passe ou de conversation dans le navigateur.

Après connexion, le navigateur lit seulement :

- `GET /v1/session` pour l'identité de session, le CSRF et l'état du moteur ;
- `GET /v1/profiles`, qui n'expose actuellement que `coordination` ;
- les routes de conversation déjà authentifiées.

Les 60 profils versionnés restent `draft` et sont refusés par `/v1/chat`.
Une réponse de chat peut être demandée avec `Accept: text/event-stream` : le
serveur publie l'état de génération puis la réponse finale. BOOTSTRAP ne diffuse
pas encore les tokens individuellement.

## Actions du chat : `SOVEREIGN_ACTIONS_ENABLED` (D-035)

Les actions sont les outils à effet de bord : `run_python` (bac à sable hors
ligne) et `write_file` (dossier de travail de la passerelle). Elles sont
**désactivées par défaut**. La variable est lue une seule fois au démarrage :
seule la valeur exacte `1` les active ; absente, vide ou `0` les désactive ;
toute autre valeur (`true`, `yes`, ` 1`…) les désactive et journalise un
avertissement qui ne recopie pas la valeur.

Désactivées, les actions ne sont ni annoncées ni offertes au modèle ; toute
proposition, confirmation (`POST /v1/chat/confirm` répond `403
actions_disabled`, y compris pour une action en attente ou un identifiant
forgé) ou exécution est refusée et journalisée sans contenu. `GET /v1/session`
et `GET /v1/health` exposent le booléen `actions_enabled`. Les outils en lecture
seule (recherche, documents, heure, liste du dossier de travail) ne changent pas.
Activées, une action approuvée qui échoue côté système (erreur d'écriture, bac à
sable introuvable) renvoie au modèle un texte fixe, sans chemin du serveur ; le
journal n'en garde que la classe d'erreur (`event=action_failed`).

Déploiement : l'installation en service garde son comportement actuel tant que
ce code n'est pas déployé. Une fois déployé, les actions sont coupées ; les
conserver exige `SOVEREIGN_ACTIONS_ENABLED=1` dans l'environnement hors dépôt de
l'unité systemd de la passerelle, ce que D-035 soumet à une décision distincte.

## Reconstruction contrôlée de l'index

`tools.build_project_knowledge_index` n'indexe plus récursivement un dossier au
démarrage. La procédure requiert un manifeste candidat, son empreinte et une
référence de validation hors dépôt :

```bash
python3 -B -m tools.build_project_knowledge_index manifest \
  --source-directory docs \
  --document project/current-capabilities.md \
  --output /var/lib/sovereign-gateway/knowledge.candidate.json

# Après approbation humaine de l'empreinte affichée :
python3 -B -m tools.build_project_knowledge_index build \
  --source-directory docs \
  --manifest /var/lib/sovereign-gateway/knowledge.candidate.json \
  --approved-manifest-sha256 '<empreinte-approuvee>' \
  --approval-reference '<reference-audit>' \
  --database /var/lib/sovereign-gateway/knowledge.sqlite3
```

La seconde commande compare les octets de chaque source, puis remplace la base
SQLite atomiquement. Elle doit être exécutée lorsque la passerelle est arrêtée
proprement ; elle ne valide, ne télécharge ni ne promeut aucune donnée elle-même.
