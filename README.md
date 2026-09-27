# Sovereign Local AI

Socle d'une intelligence artificielle locale, souveraine et **CPU-only**, construite progressivement sous contrôle du propriétaire. La V1 vise un modèle de langage créé localement, un RAG traçable, des agents logiques et une séparation stricte entre ingestion externe et connaissances internes, sans donner d'accès Internet à IA-CORE. Depuis D-034, deux voies sont distinctes : CORE-30M valide le pipeline d'entraînement CPU, sans objectif conversationnel, et l'agent de programmation repose sur un modèle tiers, Qwen2.5-Coder-7B, isolé sur un nœud physique séparé ; CORE-700M ne reçoit pas de palier long. Deux services MCP distincts constituent l'option candidate actuelle, encore soumise à audit.

> État documentaire au 2026-09-26, contre `main` à `db9414d` : **socle expérimental contrôlé**. Le serveur de calcul est hors ligne depuis le 2026-09-14 environ ; le dernier relevé en direct date du 2026-09-09 et le dernier relevé versionné du 2026-09-10. Ce README décrit le code de `main` et ces relevés, pas un état d'exécution présent. Ce dépôt ne prétend pas fournir une plateforme de production. La reprise technique par un autre agent est décrite dans le [handoff public](docs/project/claude-code-handoff.md), sans exposer de détail d'accès.

> **Au dernier relevé, l'interface privée servait le moteur BOOTSTRAP par
> défaut.** Il fournissait les réponses exploitables ; l'agent de programmation
> `QWEN-CODER` a été raccordé à la passerelle le 2026-09-09 (relevé
> `docs/operations/qwen-conversation-fix.md`) puis promu par le propriétaire le
> 2026-09-10 (relevé de promotion). CORE-700M reste raccordé en mode
> expérimental dans le code, mais ses 20 étapes de test ne produisent que du
> bruit : il ne doit pas être utilisé comme assistant. Chaque conversation
> indique le moteur employé. Le niveau de preuve de chaque capacité (vérifié
> en direct, relevé versionné, observation de commit ou code seul) figure dans
> la matrice [Capacités réellement disponibles](docs/project/current-capabilities.md).

## Dernier état vérifié

Relevés en direct jusqu'au 2026-09-09 et relevés versionnés jusqu'au
2026-09-10 ; rien n'a été revérifié depuis.

- l'interface privée, l'authentification locale et le chat **BOOTSTRAP**
  (Qwen2.5-1.5B) étaient disponibles sur le réseau privé/Tailscale ; BOOTSTRAP
  restait le défaut ;
- l'agent **Qwen2.5-Coder-7B** a été raccordé à la passerelle comme moteur
  `QWEN-CODER` le 2026-09-09, puis promu par le propriétaire le 2026-09-10,
  selon les relevés `docs/operations/qwen-conversation-fix.md` et
  `configs/runtime/qwen2.5-coder-7b-q4km.promotion.json` ;
- la lignée **CORE-30M** a atteint son palier final de 19 532 étapes avec une
  copie durable relue. Elle valide le pipeline, pas une qualité : la tentative
  E1 du 2026-09-09 a été refusée par le garde E0 sur une sortie répétitive ;
- la chaîne mécanique **CORE-700M** a été déployée en expérimental :
  chargement de checkpoint, API interne et sélection dans l'interface. Ses
  sorties ne sont pas linguistiquement exploitables et D-034 n'en prévoit
  aucun palier long ;
- le checkpoint expérimental CORE-700M de l'étape 20 est conservé sur le
  Synology avec une empreinte SHA-256 vérifiée après copie ;
- le catalogue bilingue de 10 sources permissives est acquis en **RAW** sur le
  Synology : 169 470 351 octets et 97 396 860 tokens estimés. Il n'est ni
  promu dans `VALIDATED`, ni approuvé, ni consommable par un entraînement ;
- l'acquisition a révélé que TypeScript et Kubernetes dépassent à eux seuls le
  format pilote. Un sous-échantillonnage déterministe d'environ 10 M tokens et
  une approbation propriétaire restent obligatoires ;
- depuis `6d959d7` (2026-09-08), le préflight tokenizer ne lit plus
  `configs/corpus/core-v1-source-policy.approved.json` : il exige un manifeste
  de corpus `VALIDATED` qui lie paquets, splits, empreintes et autorisations.
  Ce changement n'a pas d'entrée au registre : **ratification par le
  propriétaire en attente**.

Entre le 2026-09-10 et le 2026-09-13, `main` a reçu une arène d'agents, des
outils de chat, des profils sélectionnables, le dépôt de documents avec OCR et
une recherche hybride par embeddings. Aucun relevé versionné n'atteste leur
déploiement et plusieurs dépendent d'un choix absent du registre ; voir la
[matrice des capacités](docs/project/current-capabilities.md).

## Utiliser le système

L'interface est privée : elle est accessible depuis le LAN autorisé ou le
tailnet, jamais comme service public. Après connexion avec le compte local,
choisir **BOOTSTRAP** pour une conversation courante ou **QWEN-CODER** pour la
programmation. L'interface conserve le moteur associé à chaque conversation,
permet de créer une conversation, d'afficher l'historique, d'exporter ou de
supprimer explicitement une conversation.

Les conversations restent des données de mémoire : elles ne réentraînent
jamais automatiquement un moteur. D-032 autorise la mise en file locale et
supprimable des messages déjà assainis ; un manifeste, ses empreintes et le
gate d'entraînement restent requis avant toute modification des poids. Une
conversation ne donne aucun accès implicite aux fichiers du Synology, à un
shell, à Proxmox ou à des outils MCP larges. Le code de `main` raccorde au chat
des outils en lecture seule et des actions (`run_python` en bac à sable,
`write_file` dans un espace de travail) soumises à une confirmation humaine à
usage unique ; ces capacités n'ont pas d'entrée au registre et leur
déploiement n'est pas consigné. Toute action sensible doit être proposée
précisément puis confirmée par un humain.

### Moteurs de l'interface

Le tableau suit `engines()` de `services/web/app.py` et les libellés de
`services/web/static/app.js`.

| Moteur (`engine`) | Libellé affiché | État dans le code et preuves | Usage à retenir |
| --- | --- | --- | --- |
| `BOOTSTRAP` | « CHAT-14B · Qwen2.5-14B local » | Moteur par défaut. Le dépôt ne verrouille que Qwen2.5-1.5B (`configs/runtime/bootstrap-qwen2.5-1.5b-q4km.lock.json`, unité `infra/bootstrap-chat/` avec `--no-agent`), vérifié en direct au 2026-09-09. Le libellé 14B (`9b31b41`) n'a ni lock, ni licence, ni unité versionnée, ni entrée au registre : **décision du propriétaire en attente**. D-024 exclut outil, agent et RAG pour BOOTSTRAP, alors que le code y raccorde la boucle d'outils. | Conversation courante. Modèle tiers, jamais présenté comme CORE. |
| `QWEN-CODER` | « Qwen Coder · programmation locale » | Promu par le propriétaire le 2026-09-10 (D-034, ADR-0005) ; relevés `configs/runtime/qwen2.5-coder-7b-q4km.promotion.json` et `docs/operations/qwen-conversation-fix.md`. Disponible seulement si `SOVEREIGN_QWEN_TOKEN` est configuré ; sinon la passerelle répond 503. | Programmation ; moteur des profils de la famille `development`. |
| `CORE-700M` | « CORE-700M expérimental » | Raccordé en expérimental ; disponible seulement si son checkpoint et sa provenance sont validés. Voie archivée par D-034 : aucun palier long. | Diagnostic de raccordement uniquement ; ne pas l'employer pour des réponses utiles. |

CORE-MINI et CORE-30M ne sont pas des moteurs de l'interface : ils servent à
valider l'entraînement, les checkpoints et les reprises. Le choix explicite de
CORE-700M ne vaut pas promotion : le moteur conserve son étiquette
expérimentale. Dans le code, un moteur indisponible ou une sortie refusée
produit une erreur explicite (réponse 503, ou événement `error` en flux), sans
bascule silencieuse vers un autre moteur ; BOOTSTRAP reste le choix par
défaut.

## Corpus : état et frontière de confiance

Les dix archives permissives du catalogue sont conservées **telles que reçues
dans RAW**, avec l'URL de tag, la licence vérifiée, l'empreinte SHA-256, la
taille et les mesures de texte. Les archives ne sont ni réécrites, ni déplacées
vers `VALIDATED`, ni ajoutées aux poids.

```text
Internet autorisé (acquisition ponctuelle)
        -> RAW Synology : 10 archives, 169.47 MB
        -> revue propriétaire + sous-échantillon déterministe
        -> manifeste approuvé avec SHA-256
        -> VALIDATED
        -> tokenizer / entraînement CORE
```

Le premier relevé dépasse volontairement le plafond pilote : 97.4 M tokens
estimés au lieu d'environ 10 M, dont seulement 0.42 % de français. Ce constat
est utile : il interdit de présenter ce lot comme le corpus final ou comme un
corpus français-technique équilibré. TypeScript et Kubernetes devront être
bornés par une règle de sélection reproductible avant toute approbation.

## Ce qui bloque volontairement la suite

1. Le propriétaire choisit et approuve un sous-échantillon déterministe proche
   de 10 M tokens, avec une proportion FR/EN cible explicite.
2. Le changement de gate `6d959d7` attend une décision du propriétaire :
   ratification ou retour à `approved.json`. Depuis `6d959d7`, le préflight
   exige un manifeste `VALIDATED` avec empreintes
   ([gate corpus et tokenizer](docs/model/corpus-and-tokenizer-gate.md)) et ne
   lit plus `core-v1-source-policy.approved.json`, que seul le propriétaire
   pourrait commiter. Ce remplacement n'a pas d'entrée au registre. Ce README
   ne tranche pas si le catalogue de 10 sources et les incréments
   synthétiques de l'arène exigent encore ce fichier, comme l'indique le §4 de
   la [spécification d'auto-entraînement](docs/model/self-training-loop-spec.md).
3. Le gate G4, benchmark CPU/NUMA reproductible, reste ouvert : aucune durée
   d'entraînement n'est annoncée. Son périmètre après D-034 reste à préciser
   par le propriétaire.

Il n'existe ni drapeau `--force`, ni variable d'environnement permettant de
contourner le préflight. Un refus de gate est le comportement attendu.

## Invariants déjà décidés

- aucun GPU, CUDA, ROCm ou TPU dans le chemin V1 ;
- calcul principal sur le **HPE ProLiant ML350 Gen9**, CPU-only, sous Proxmox ; l'inventaire mesuré et les divergences avec la fiche initiale restent suivis séparément ;
- **Synology RS3617xs+** : stockage long terme, archives, datasets, modèles validés, checkpoints importants, connaissances et sauvegardes — pas d'entraînement principal ;
- **DL380p Gen8** : D-006, qui l'excluait de la V1, est SUPERSEDED par D-034. Aucune fonction CORE ni aucun entraînement ne lui est confié ; le relevé de promotion du 2026-09-10 y place l'agent de programmation Qwen-Coder, nœud physique séparé au sens de D-034. `AGENTS.md` indique encore « Le DL380p Gen8 ne reçoit aucun service V1 » : cette ligne contredit D-034 et attend sa modification par le propriétaire, seul à éditer ce fichier ;
- la future zone **IA-CORE ne doit avoir aucun accès Internet direct** ; le blocage réseau et son test négatif restent un gate obligatoire, distinct des refus applicatifs déjà codés ;
- toute donnée externe est non fiable et entre par un collecteur, une quarantaine, une validation, puis un import contrôlé ;
- une recherche brute n'est jamais automatiquement une connaissance validée ;
- les originaux RAW et leur provenance sont conservés ;
- environ 60 agents sont des profils logiques partageant un petit nombre de moteurs, et non 60 copies du modèle ;
- aucune durée d'entraînement ne sera annoncée avant benchmark sur le matériel réel.

Le registre complet se trouve dans [docs/project/decisions.md](docs/project/decisions.md).

## Architecture cible candidate — pas l'état actuel

Le schéma suivant décrit la destination. Les blocs ne sont pas tous déployés ou
reliés ; la page des capacités indique l'état réel de chacun.

```text
Internet / fournisseurs externes
              |
              v
     RESEARCH-GATEWAY (DMZ)
       appels API contrôlés
              |
              v
     MCP COLLECTOR EXTERNE
      dépôt à privilèges minimes
              |
              v
    QUARANTAINE + VALIDATION
              |
       import autorisé
              v
  STOCKAGE / CONNAISSANCES VALIDÉES
       Synology RS3617xs+
              |
        réseau IA privé
              v
           IA-CORE
       HPE ML350 Gen9
  modèle + RAG + orchestrateur
              |
              v
      MCP KNOWLEDGE INTERNE

IA-CORE -X-> Internet
Internet -X-> MCP Knowledge interne
Collector externe -X-> lecture des données privées
```

L'option Research Gateway est la direction recommandée pour l'étude, car elle centralise les clés, les coûts, les fournisseurs et l'audit. Elle reste une **décision provisoire** jusqu'à validation de la topologie, des usages et des politiques de sortie.

## Lignées CORE

D-034 sépare deux voies. **CORE-30M** (29 990 784 paramètres entraînables,
`configs/models/core-30m.candidate.json`) valide le pipeline d'entraînement CPU
jusqu'à son budget de 600 M tokens, sans objectif conversationnel ni
fine-tuning de dialogue. Voir la
[proposition d'évaluation CORE-30M](docs/model/core-30m-evaluation-proposal.md).

**CORE-700M** reste une définition exacte avec des preuves mécaniques
archivées : Transformer decoder-only de **691 160 320 paramètres
entraînables**, vocabulaire 32 000, dimension 1 280, 32 blocs, 20 têtes, MLP
SwiGLU 3 584, RoPE, RMSNorm, matrice d'embedding de tokens et tête de sortie
liées, sans biais, contexte candidat de 2 048 tokens. D-026, qui en faisait le
candidat principal, est SUPERSEDED par D-034 : aucun palier long n'est prévu et
son checkpoint expérimental de 20 étapes ne constitue pas un modèle linguistique
utile. CORE-80M reste une référence historique. Voir
[docs/model/core-700m.md](docs/model/core-700m.md).

Vérifier les calculs avec :

Sous Windows :

```powershell
py -3 -B tools/count_core_parameters.py
py -3 -B tools/count_core_parameters.py --config configs/models/core-30m.candidate.json
```

Sous Linux :

```bash
python3 -B tools/count_core_parameters.py
python3 -B tools/count_core_parameters.py --config configs/models/core-30m.candidate.json
```

Sans `--config`, l'outil compte la définition CORE-700M.

## Structure du dépôt

```text
.
├── AGENTS.md                         règles de travail pour les agents
├── SECURITY.md                       signalement et principes de sécurité
├── configs/
│   ├── models/                       configurations CORE candidates, non validées
│   ├── corpus/                       catalogue et politique des sources du corpus
│   ├── tokenizers/                   artefact tokenizer candidat
│   ├── runtime/                      locks et reçus de promotion des runtimes et modèles tiers
│   ├── evaluation/                   suites candidates E1 et E2
│   ├── arena/                        suite d'entraînement de l'arène
│   ├── agents/                       registre des 60 profils, tous draft
│   ├── knowledge/                    catalogue synthétique du MCP Knowledge
│   └── security/                     rôles
├── docs/
│   ├── architecture/                 architecture logique, déploiement et ADR
│   ├── security/                     menaces, frontières et gates
│   ├── mcp/                          collecteur externe et MCP interne
│   ├── data/                         provenance et cycle de vie
│   ├── model/                        lignées CORE, corpus, tokenizer, évaluation, arène
│   ├── agents/                       agents logiques et permissions
│   ├── operations/                   relevés d'exploitation versionnés
│   ├── project/                      décisions, capacités, handoff et questionnaire
│   └── ROADMAP.md                    phases et critères de sortie
├── schemas/                          contrats de données versionnés
├── services/                         passerelle Web, arène, inférence, connaissances, collecteur
├── infra/                            unités et scripts d'hôte versionnés ; leur présence n'atteste aucun déploiement
├── tools/                            outils locaux sans dépendances lourdes
└── tests/                            vérifications du socle
```

## Configuration

Les variables `SOVEREIGN_*` lues par la passerelle Web sont décrites, avec
leurs valeurs par défaut, dans [services/web/README.md](services/web/README.md) ;
celles des composants de connaissance dans
[services/knowledge/README.md](services/knowledge/README.md). La variable
`SOVEREIGN_ACTIONS_ENABLED`, annoncée par un message de commit, n'existe pas
dans le code. Les approbations de paquets, de profils et d'incréments de corpus
sont des fichiers JSON non signés.

## Commencer correctement

1. Lire [AGENTS.md](AGENTS.md) et le [registre des décisions](docs/project/decisions.md).
   Pour reprendre avec un autre agent, consulter aussi le
   [handoff Claude Code](docs/project/claude-code-handoff.md).
2. Consulter la [matrice des capacités](docs/project/current-capabilities.md) et le niveau de preuve de chaque ligne ; au retour du serveur, relever l'état installé avant toute nouvelle affirmation.
3. Revoir le catalogue RAW et approuver explicitement un sous-échantillon ; la forme de l'approbation d'entraînement attend la ratification du propriétaire.
4. Valider la topologie réseau, les flux, le stockage, l'identité, les sauvegardes et les politiques de données.
5. Mesurer le ML350 : CPU, RAM, NUMA, disque, threads et tokens/seconde sur un mini-modèle.
6. Produire les ADR et figer une pile minimale avant toute implémentation de production.

Le projet n'adopte pas encore de base vectorielle, de framework Web définitif
ni de système de queue. Pour les embeddings, D-028 autorise un petit moteur
pré-entraîné séparé de CORE, sous réserve de licence et d'empreinte vérifiées.
Le code de `main` contient un client en boucle locale pour
Qwen3-Embedding-0.6B et une recherche hybride SQLite avec repli lexical
(`d7cc78c`) : **code présent, déploiement non vérifié**. Aucun lock, licence ni
empreinte de ce modèle n'est versionné et aucune entrée du registre ne le
désigne : décision du propriétaire en attente. Le reranker et le moteur d'index
restent à valider par benchmark (P-004). SMB est utilisé pour les essais de
stockage actuels ; son rôle définitif reste soumis à décision. Les options
devront être comparées sur les contraintes réelles, puis consignées dans le
registre.

## Principes de sécurité

- deny-by-default entre les zones ;
- aucun secret dans Git, les prompts, les archives de recherche ou les logs ;
- formats d'entrée explicitement autorisés, limites de taille et validation stricte ;
- contenu externe traité comme données, jamais comme instructions ;
- RAW immuable et promotion vers `VALIDATED` traçable ;
- outils MCP à portée minimale, sans fichier arbitraire, shell ou exploration réseau ;
- approbation explicite pour toute donnée autorisée à sortir ;
- tests des flux interdits, pas seulement des flux autorisés.

Consulter [SECURITY.md](SECURITY.md) et [docs/security/threat-model.md](docs/security/threat-model.md).

## Roadmap

La progression suit des gates mesurables : découverte, architecture sécurisée, ingestion contrôlée, corpus/tokenizer/RAG, mini-modèle et benchmark CPU/NUMA, pilote de montée en échelle, entraînement progressif CORE, Knowledge/RAG/MCP interne, puis profils d'agents et durcissement. Des prototypes de jalons ultérieurs peuvent exister sans que leur gate soit franchi. La génération d'images est hors périmètre V1 ; le DL380p ne reçoit ni fonction CORE ni entraînement (D-034).

Voir [docs/ROADMAP.md](docs/ROADMAP.md).

## Licence

Aucune licence n'est ajoutée tant que le propriétaire n'a pas choisi les droits
de réutilisation. L'absence de licence signifie qu'aucun droit de réutilisation
n'est accordé implicitement ; ce choix reste à traiter pendant la découverte.
