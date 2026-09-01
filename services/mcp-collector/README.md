# MCP Collector externe

Point de dépôt minimal pour les recherches externes. Le contrat V0 candidat expose une soumission atomique `submit_research_package` et renvoie uniquement son accusé de réception technique immédiat. Il n'expose ni consultation d'état différée, ni liste, ni lecture, ni modification. Un futur protocole fragmenté exigerait un ADR et les mêmes garanties d'absence de lecture.

Il ne fournit aucune recherche, lecture de document privé, mémoire d'agent, fichier de modèle, shell, chemin arbitraire ou accès au réseau interne.

## Collector de conversations

`conversation_http.py` fournit un premier endpoint HTTP en écriture seule : `POST /v1/conversations`. Il écoute par défaut uniquement sur `127.0.0.1:8787`; TLS et l'exposition publique sont confiés à un reverse proxy ou tunnel approuvé. `GET /healthz` ne retourne qu'un état technique sans donnée.

Le Collector impose un jeton Bearer d'au moins 32 caractères, `application/json`, une limite de 1 Mio et la validation stricte de l'export. Il ne journalise ni corps, ni en-tête, ni contenu. Une soumission acceptée reste `RAW` et ne devient jamais automatiquement une connaissance MCP.

## Synchronisation des conversations Codex

`tools/codex_conversation_sync.py` est le relais local destiné au hook Codex `SessionEnd`. Il extrait uniquement les messages utilisateur et assistant du transcript local, retire les secrets probables, découpe les conversations sous la limite d'ingress puis les place dans une file locale avant envoi HTTPS. Le hook ne bloque pas sur le réseau : un processus détaché expédie la file, et un hook `SessionStart` relance les envois différés.

Les URL HTTP ou HTTPS contenant une requête ou un fragment sont retirées sans
dépendre de la casse du schéma. Un accusé HTTP `202` qui n'est pas un objet JSON
valide est refusé ; la conversation reste alors dans la file pour une nouvelle
tentative.

L'adresse du Collector n'est jamais fournie par le dépôt. L'installation la
définit hors Git, soit avec la paire `SOVEREIGN_COLLECTOR_URL` et
`SOVEREIGN_COLLECTOR_ALLOWED_HOST`, soit dans le fichier local
`collector-endpoint.json` situé sous `SOVEREIGN_SYNC_HOME` (ou, par défaut,
`~/.codex/sovereign-sync`). Le fichier contient exactement deux chaînes :
`collector_url` et `allowed_host`. Sa taille est bornée et les liens, objets non
réguliers, champs supplémentaires, doublons et JSON non stricts sont refusés.
Si au moins une variable d'environnement est présente, cette source est
prioritaire ; une paire incomplète échoue sans repli silencieux vers le fichier.

```json
{
  "collector_url": "https://collector.example.test/v1/conversations",
  "allowed_host": "collector.example.test"
}
```

Les deux sources passent par la même validation. Le relais refuse une
configuration absente, HTTP, contenant des identifiants, une requête, un
fragment, un port non standard, un hôte non explicitement autorisé ou un chemin
différent de `/v1/conversations`. Un exemple de hooks sans chemin personnel se
trouve dans `configs/codex/hooks.windows.example.json`.

Le client HTTPS désactive les proxys ambiants et refuse les redirections HTTP
`301`, `302`, `303`, `307` et `308`. Le jeton d'autorisation n'est donc jamais
recopié vers une destination fournie par une réponse de redirection ; la
conversation reste en file pour une nouvelle tentative.

Avant tout envoi, chaque fichier de file est lu avec une limite de 1 Mio,
doit être un fichier régulier, un objet JSON UTF-8 strict et canonique, respecter
le schéma minimal d'une conversation et porter le même `conversation_id` que
son nom. Après un `202`, le relais exige `application/json` lorsque les en-têtes
sont accessibles puis un accusé composé exactement de `state`,
`conversation_id` et `sha256`. L'état doit être `raw_imported` ou
`already_imported`; l'identifiant et l'empreinte SHA-256 doivent correspondre
exactement aux octets envoyés.

Le reçu local ajoute uniquement `received_at`. Il est écrit atomiquement après
synchronisation du fichier, relu et validé contre le payload avant suppression
de la file. Un reçu absent, vide, corrompu, lié ou incohérent ne sert jamais à
dédupliquer : le relais régénère ou conserve alors la conversation pour une
nouvelle tentative.

Le jeton reste dans `~/.codex/sovereign-sync/collector.token`, hors du dépôt. Les reçus locaux ne contiennent pas le contenu des conversations. Un historique peut être préparé avec `--backfill`, en excluant par délai les sessions encore actives. L'acceptation par le Collector conserve les données en `RAW`; aucune promotion vers `VALIDATED` n'est automatique.

