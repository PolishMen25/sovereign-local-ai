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
