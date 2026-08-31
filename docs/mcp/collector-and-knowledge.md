# MCP Collector et MCP Knowledge

Statut : architecture candidate avec deux prototypes étroits. Le Collector
write-only est exposé derrière un relais HTTPS ; le MCP Knowledge actuel est
uniquement `stdio`. Le choix final des frontières reste à confirmer par ADR.

## État du prototype actuel

- le Collector accepte des exports strictement validés en `RAW` et ne fournit
  aucune lecture interne ;
- le MCP Knowledge expose seulement `knowledge_status` et `search_validated` ;
- `search_validated` effectue une recherche lexicale dans les titres et résumés
  d'un catalogue JSONL borné, avec `provenance_id` ;
- le catalogue actif de démonstration contient trois notices synthétiques ;
- aucun index vectoriel, moteur d'embeddings, lecture documentaire complète,
  modèle génératif ou raccordement à l'interface Web n'est disponible.

## Option structurante candidate

Le candidat actuel expose deux frontières MCP distinctes. Il doit être comparé aux variantes compatibles avec les mêmes invariants pendant l'audit. Quelle que soit l'implémentation retenue, l'ingestion externe et la consultation interne ne partagent ni processus, ni identité de service, ni droits sur les données.

1. **MCP Collector (externe)** : point d’entrée minimal et en écriture seule. Il reçoit des paquets de recherche, les contrôle superficiellement, les dépose dans la zone d’ingestion et renvoie uniquement un accusé de réception non sensible.
2. **MCP Knowledge (interne)** : le prototype actuel est lancé à la demande en
   `stdio`, sans port réseau. Une éventuelle exposition à des clients internes
   demanderait une décision et des contrôles supplémentaires ; Internet reste
   interdit.

Le Collector ne possède aucun droit de lecture sur le stockage RAW, les index, les documents validés, les conversations, les journaux internes ou le MCP Knowledge. Il ne propose aucune opération de liste, recherche, lecture, modification, suppression ou suivi différé. Une réponse synchrone limitée à un identifiant de soumission, un horodatage et un résultat d’acceptation technique ne constitue pas un accès en lecture aux données internes.

## Architecture B : Research Gateway

L’architecture recommandée provisoirement est l’**architecture B**, dans laquelle les recherches futures passent par un Research Gateway contrôlé :

```text
Fournisseurs externes / Web
          |
          v
Research Gateway contrôlé
  - construit le paquet
  - retire les secrets
  - calcule les empreintes
  - conserve les citations
          |
          v
MCP Collector externe (write-only)
          |
          v
Zone d’ingestion isolée -> RAW immuable -> validation
                                         |
                                         v
                              connaissances validées
                                         |
                                         v
                              MCP Knowledge interne
```

Cette recommandation n’est pas une décision définitive. L’audit doit confirmer au minimum le système d’exploitation, la topologie réseau, les machines disponibles, les volumes attendus, les fournisseurs, les contraintes légales, la stratégie d’identité, les mécanismes de sauvegarde et la possibilité d’isoler réellement les services. L’architecture finale sera figée seulement après cet audit.

Le Gateway permet de maîtriser les recherches futures faites via API. Les conversations effectuées manuellement sur des interfaces tierces ne sont pas réputées récupérables automatiquement ; elles nécessitent un export ou un import explicite.

## Contrat minimal du Collector

Le Collector expose idéalement une seule capacité métier :

- `submit_research_package` reçoit un document conforme à `schemas/research-package.schema.json` et, si accepté, retourne `submission_id`, `received_at`, `ingress_payload_sha256` et un statut technique (`accepted` ou `rejected`). L'empreinte d'ingress est calculée par le Collector sur les octets effectivement reçus et conservée dans son reçu/journal, jamais à l'intérieur du paquet qu'elle couvre.

Le Collector réalise uniquement les contrôles nécessaires avant le dépôt : taille, type de contenu, version de schéma, structure, absence de champs inconnus, **nouveau contrôle de secrets exécuté côté serveur**, format des empreintes, unicité/idempotence et limites de débit. L'auto-attestation du Gateway n'est jamais une preuve. Un corps refusé pour secret n'est ni recopié dans les journaux ni placé dans l'archive RAW durable ; seul un événement d'échec assaini est conservé. Le Collector ne classe pas la connaissance et ne décide pas de sa vérité.

Un paquet accepté est écrit dans une file ou une zone d’ingestion à droits append-only. L’accusé de réception ne doit contenir ni extrait du paquet, ni résultat d’indexation, ni état interne ultérieur. Il n’existe pas d’outil `get`, `list`, `search`, `update`, `delete`, `status` ou équivalent sur cette frontière.

## Traitement interne

Après l’ingestion, un service interne distinct :

1. conserve les octets reçus dans le stockage RAW immuable ;
2. recalcule les empreintes et journalise la réception ;
3. place le paquet en `PENDING` ;
4. analyse les contenus comme des données non fiables ;
5. vérifie la provenance, les citations, les pièces jointes et les politiques ;
6. produit une décision `VALIDATED` ou `REJECTED` sans modifier le RAW ;
7. indexe uniquement les représentations autorisées et validées.

Les transitions d’état sont des événements append-only. Elles ne réécrivent pas le paquet RAW. Les règles détaillées sont décrites dans `docs/data/provenance-and-lifecycle.md`.

## Frontière du MCP Knowledge

La cible future du MCP Knowledge pourra fournir recherche, lecture ciblée,
comparaison de sources et traçabilité. Le prototype fournit seulement l'état et
la recherche lexicale de résumés. Toutes les capacités futures devront conserver
les identifiants de provenance et distinguer clairement texte source, résumé et
inférence.

Contraintes obligatoires :

- aucune route Internet entrante, aucune redirection depuis le Collector et aucun tunnel partagé ;
- identité de service et secrets séparés de ceux du Collector et du Gateway ;
- accès au seul corpus `VALIDATED`, sauf outil administratif isolé et explicitement autorisé ;
- contrôle d’accès par utilisateur/service, journalisation des requêtes et limitation des volumes exportables ;
- absence de droit d’écriture vers le RAW ;
- sortie réseau désactivée par défaut ; seules des destinations **internes** explicitement allowlistées peuvent être ouvertes si l'audit démontre un besoin. Internet et la DMZ restent toujours interdits au MCP Knowledge et à IA-CORE.

Une compromission du Collector ne doit donc offrir aucun chemin de lecture vers les connaissances internes.

## Données Web et prompt injection

Tout texte provenant du Web, d’un fournisseur, d’une pièce jointe ou d’une réponse de modèle est **non fiable**. Des phrases qui ressemblent à des instructions système, à des appels d’outil ou à des demandes d’exfiltration restent des données à analyser ; elles ne deviennent jamais des instructions de contrôle.

Les composants doivent :

- séparer physiquement ou logiquement les instructions de contrôle et le contenu collecté ;
- ne jamais exécuter de code, URL, outil ou commande suggéré par un contenu ingéré ;
- supprimer les secrets et assainir les URL avant l’envoi ;
- analyser les pièces jointes dans un environnement isolé, sans macros ni accès réseau par défaut ;
- limiter taille, profondeur d’archive, types MIME et temps de traitement ;
- conserver la source et les empreintes pour permettre une vérification indépendante ;
- exiger une validation explicite avant qu’un contenu influence un agent doté d’outils.

## Sécurité opérationnelle minimale

- chiffrement en transit et authentification forte entre Gateway et Collector ;
- identifiants courts, rotation des secrets et stockage hors des paquets de recherche ;
- protection contre le rejeu par identifiant idempotent, horodatage borné et empreinte ;
- quotas par identité, limitation de débit et taille maximale documentée ;
- journaux de sécurité sans contenu sensible, avec corrélation par identifiant ;
- sauvegardes chiffrées et tests de restauration du RAW et du journal d’événements ;
- dépendances épinglées, analyse de vulnérabilités et mises à jour contrôlées ;
- alertes sur échecs d’empreinte, schémas invalides, doublons anormaux et tentatives de lecture.

## Points à trancher pendant l’audit

- protocole d’exposition du Collector et mécanisme d’identité ;
- stockage immuable disponible et durée de conservation ;
- file d’ingestion, débit, taille maximale et stratégie de reprise ;
- règles d’import des historiques issus d’exports tiers ;
- modèle de validation humaine/automatique et critères de rejet ;
- emplacement exact du MCP Knowledge et liste de ses clients autorisés ;
- fournisseurs et champs de coût réellement disponibles ;
- politique juridique de conservation, d’effacement exceptionnel et de données personnelles.

