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

Le RAG hybride, les profils d'agents et les actions confirmables ne sont pas
encore raccordés à la route de chat. Une absence d'Argon2id ou du runtime local
provoque un refus sûr ; aucun fournisseur distant n'est utilisé.

Le service ne doit jamais écouter directement sur le LAN. Un reverse proxy
HTTPS approuvé porte l'accès LAN ou tailnet, tandis que le processus Python
reste sur `127.0.0.1`.

