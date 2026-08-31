# MCP Collector externe

Point de dépôt minimal pour les recherches externes. Le contrat V0 candidat expose une soumission atomique `submit_research_package` et renvoie uniquement son accusé de réception technique immédiat. Il n'expose ni consultation d'état différée, ni liste, ni lecture, ni modification. Un futur protocole fragmenté exigerait un ADR et les mêmes garanties d'absence de lecture.

Il ne fournit aucune recherche, lecture de document privé, mémoire d'agent, fichier de modèle, shell, chemin arbitraire ou accès au réseau interne.

## Collector de conversations

`conversation_http.py` fournit un premier endpoint HTTP en écriture seule : `POST /v1/conversations`. Il écoute par défaut uniquement sur `127.0.0.1:8787`; TLS et l'exposition publique sont confiés à un reverse proxy ou tunnel approuvé. `GET /healthz` ne retourne qu'un état technique sans donnée.

Le Collector impose un jeton Bearer d'au moins 32 caractères, `application/json`, une limite de 1 Mio et la validation stricte de l'export. Il ne journalise ni corps, ni en-tête, ni contenu. Une soumission acceptée reste `RAW` et ne devient jamais automatiquement une connaissance MCP.

## Synchronisation des conversations Codex

`tools/codex_conversation_sync.py` est le relais local destiné au hook Codex `SessionEnd`. Il extrait uniquement les messages utilisateur et assistant du transcript local, retire les secrets probables, découpe les conversations sous la limite d'ingress puis les place dans une file locale avant envoi HTTPS. Le hook ne bloque pas sur le réseau : un processus détaché expédie la file, et un hook `SessionStart` relance les envois différés.

Le jeton reste dans `~/.codex/sovereign-sync/collector.token`, hors du dépôt. Les reçus locaux ne contiennent pas le contenu des conversations. Un historique peut être préparé avec `--backfill`, en excluant par délai les sessions encore actives. L'acceptation par le Collector conserve les données en `RAW`; aucune promotion vers `VALIDATED` n'est automatique.

