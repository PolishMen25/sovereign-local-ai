# Reprise Claude Code

Dernière mise à jour : 2026-09-26, documentaire seulement : serveur de calcul
hors ligne, aucun relevé en direct depuis le 2026-09-10.

Ce document est le point de reprise public et expurgé. Il ne contient ni
adresse privée, compte, secret, chemin d'administration ou inventaire détaillé.
Lire d'abord `AGENTS.md`, `docs/project/decisions.md`,
`docs/project/current-capabilities.md`, `docs/architecture/overview.md` et
`docs/security/threat-model.md`.

## Mise à jour 2026-09-26 (serveur hors ligne)

Cette section prime sur toutes les sections plus bas, conservées pour la
traçabilité. Elle couvre les 43 commits intégrés sur `main` entre `8ec82e0`,
dernière mise à jour de ce fichier, et `db9414d` du 2026-09-13. Elle a été
rédigée sans accès au serveur de calcul et ne décrit **aucun état d'exécution
actuel**.

### Vérification

- Le serveur de calcul est hors ligne depuis le 2026-09-14 environ. Rien n'a
  été revérifié en direct après le 2026-09-09, hormis les relevés versionnés
  cités ci-dessous ; le plus récent date du 2026-09-10.
- Un relevé versionné décrit l'état à sa date, pas l'état présent. Au retour
  du serveur, relever composant par composant ce qui est réellement installé
  avant toute nouvelle affirmation.

### Niveaux de preuve

- **[R] relevé versionné** : un relevé de déploiement ou d'exploitation est
  versionné dans le dépôt ; son chemin est cité.
- **[O] observation de commit** : le constat figure seulement dans le message
  du commit cité ; il n'a été ni relu ni consigné ailleurs.
- **[C] code seul** : code et tests présents sur `main`, sans aucune preuve de
  déploiement.

« Sans décision au registre » signale une capacité qui dépend d'un choix du
propriétaire absent de `docs/project/decisions.md`. Cette section ne tranche
aucun de ces choix.

### Commits par thème

**Agent de programmation Qwen2.5-Coder-7B (moteur `QWEN-CODER`)**

- `ac05afc`, `7b2111b`, `a2e40ea`, `1ba28b6` : lock RAW gelé, moteur
  `QWEN-CODER` exposé par la passerelle, qui lui transmet les 20 derniers
  messages et les références lexicales. **[R]**
  `docs/operations/qwen-conversation-fix.md` : déploiement ciblé de fichiers de
  la passerelle et un appel réel, à la date du relevé.
- `bf13670` : promotion par le propriétaire le 2026-09-10, dans le cadre de
  D-034, avec empreintes SHA-256 relues en RAW, en VALIDATED et sur le nœud
  d'exécution. **[R]** `configs/runtime/qwen2.5-coder-7b-q4km.promotion.json`.
  Mesures E2 consignées au même endroit : Qwen2.5-1.5B 23/50,
  Qwen2.5-Coder-7B 38/50, puis 45/50 avec une passe de réparation qui montre
  l'assertion échouée.
- `e09c521` : générateur hors ligne `tools/generate_code_candidates.py`
  **[C]**. Le même commit consigne l'isolation réseau du conteneur de l'agent :
  seule entrée admise depuis la passerelle vers le port du moteur, sortie
  refusée. **[R]** même relevé de promotion.
- Conflit signalé, non tranché : le relevé de promotion place l'agent sur le
  DL380p Gen8, nœud physique séparé au sens de D-034, alors qu'`AGENTS.md`
  indique encore « Le DL380p Gen8 ne reçoit aucun service V1 ». Seul le
  propriétaire modifie `AGENTS.md`.

**Évaluation de code et réparation**

- `0a1c2ee` : budget de tâches du bac à sable et auto-test du harness. **[O]**
  le message rapporte que l'ancien plafond rejetait chaque tâche avant
  exécution, puis 23/50 une fois corrigé.
- `e292451` : boucle écrire, tester, corriger `tools/run_code_agent_loop.py`,
  une réparation par défaut, `first_pass` et `final_pass` rapportés côte à
  côte. **[C]**
- `58c26c9` : réparation d'un projet depuis ses propres tests,
  `tools/run_project_repair.py` : copie de travail, fichiers de test jamais
  modifiés, diff remis à un humain. **[C]** ; démonstration sur un projet de
  deux fichiers **[O]**.

**Arène d'agents**

- `0dcbe8c`, `b5f0227`, `015b815` : arène arbitrée par le bac à sable hors
  ligne, page `/arena` avec approbations du propriétaire, résumé en terminal.
  **[C]**
- `9b31b41`, `8ef2f8a` : relecteur sur le moteur 14B et paquets robustes à un
  changement de suite. **[O]** `8ef2f8a` rapporte un redémarrage en boucle du
  démon, corrigé par ce commit.
- Paquets : les messages rapportent 41 paquets (`dbca0c6`) puis 28 « paquets
  réels » mesurés (`b486851`). **[O]** Les deux populations ne sont pas
  définies de la même façon et aucun relevé ne les confirme.
- Activation : sans décision au registre.
  `docs/model/self-training-loop-spec.md` porte encore le statut `INACTIVE`, et
  ses critères d'activation (approbation explicite, au moins 60 % sur 100
  tâches) ne sont consignés nulle part comme atteints ou levés.

**Suite d'entraînement de l'arène**

- `1857089`, `0655d42`, `db9414d` : `configs/arena/practice-suite.v1.json`
  passe de 52 à 100 puis 182 tâches, séparée du benchmark scellé E2. **[C]**
  Aucun relevé n'indique que la version à 182 tâches ait été chargée. Suite par
  défaut : voir les écarts ci-dessous.

**Pont paquets vers incréments de corpus, et promotion**

- `229ffe0`, `689fa70`, `75d234a`, `0655d42`, `5f59591`, `dbca0c6` : un
  paquet approuvé devient un incrément RAW synthétique ; une approbation dans
  l'interface est appliquée par un service périodique, toutes les deux
  minutes, qui promeut RAW vers VALIDATED. **[O]** `5f59591` rapporte la panne
  de la page corpus et sa cause, des chemins de partage divergents ;
  `dbca0c6` rapporte que 2 paquets seulement étaient devenus des incréments.
- Constats de code : `services/web/app.py` qualifie l'approbation de
  « signée », mais c'est un JSON sans signature ni HMAC ; l'unité de
  l'applicateur ne fixe pas `User=` et s'exécute donc en root. Sans décision
  au registre.

**Santé des paquets**

- `cd68960`, `d9c0e42`, `b486851` : santé mesurée sur l'ensemble retenu,
  `distinct_tasks`, `max_task_share` borné à 0,25 et
  `tools/recheck_packet_health.py`. **[O]** mesures rapportées sur 22, 25 puis
  28 paquets ; le déploiement de ce code n'est pas consigné.

**Profils de chat**

- `5891fff`, `91ff285`, `9ac11cd` : agents d'arène approuvés et profils du
  catalogue sélectionnables dans le chat, groupés par famille. Selon `91ff285`,
  59 profils du catalogue deviennent sélectionnables : 49 sur le moteur 14B
  avec outils, 10 de la famille `development` sur Qwen-Coder. **[C]**
- Les gates d'évaluation par profil ne sont pas appliqués ; seul un
  commentaire de `services/web/catalog_profiles.py` l'attribue à un choix du
  propriétaire. `configs/agents/registry.json` garde les 60 profils en
  `draft`. Sans décision au registre.

**Documents partagés, OCR et analyse**

- `010706c`, `5c917de`, `a8151e7` : dépôt de document limité à 25 Mo,
  extraction hors ligne (texte, docx, PDF via poppler, OCR Tesseract), analyse
  map-reduce bornée à 30 passages, rappel RAG porté de 2 à 6 extraits, rendu
  Markdown. **[C]** La présence de poppler et Tesseract sur le serveur n'est
  pas consignée.
- Constats de code : les passages déposés passent par
  `HybridKnowledgeIndex.upsert_validated`
  (`services/knowledge/document_ingest.py`) et rejoignent la table du
  manifeste approuvé sans trace d'approbation ; les extracteurs s'exécutent
  sans bac à sable dans la passerelle. Une reconstruction de l'index approuvé
  crée une base neuve limitée au manifeste, sans embeddings, puis remplace le
  fichier : sur la base de la passerelle, elle effacerait passages déposés et
  embeddings. En tension avec « `RAW` n'est pas `VALIDATED` » ; sans décision
  au registre.

**Outils du chat**

- `a133659` : boucle d'outils en lecture seule (`search_knowledge`,
  `list_documents`, `read_document`, `current_time`) sur l'emplacement
  `BOOTSTRAP`, enclenchée par défaut dans le code via
  `SOVEREIGN_TOOLS_ENABLED`. **[C]** Elle exige un serveur 14B lancé avec
  `--jinja`, dont l'unité n'est pas versionnée.
- `04473fe`, `3410b36` : actions `run_python` dans le bac à sable bwrap et
  `write_file` dans un espace de travail lisible par `GET /v1/workspace`,
  chacune derrière une confirmation humaine à usage unique. **[C]**
- Constats de code : la variable `SOVEREIGN_ACTIONS_ENABLED` annoncée par
  `04473fe` n'existe pas ; `actions_enabled` est une valeur par défaut codée en
  dur. L'unité versionnée de la passerelle garde `PrivateDevices=yes` et
  n'autorise pas `AF_NETLINK`, contrairement à l'unité de l'arène qui les
  écarte pour bwrap. **HYPOTHÈSE** à vérifier sur le serveur : sous l'unité du
  dépôt, l'auto-test du bac à sable échoue et `run_python` n'est pas proposé.
- Ces outils contredisent D-024, qui exclut « outil, agent, RAG » pour
  BOOTSTRAP. Sans décision au registre.

**Emplacement BOOTSTRAP libellé « CHAT-14B »**

- `9b31b41` : l'interface affiche l'emplacement `BOOTSTRAP` comme
  « CHAT-14B · Qwen2.5-14B local » ; `017e79f` : `/sante` l'affiche comme
  « Conversation (Qwen2.5-14B) ». **[C]**
- Le dépôt ne verrouille pourtant que Qwen2.5-1.5B
  (`configs/runtime/bootstrap-qwen2.5-1.5b-q4km.lock.json`, unité
  `infra/bootstrap-chat/` avec `--no-agent`). Aucun lock, licence, unité ni
  entrée du registre n'existe pour un 14B. Sans décision au registre.

**RAG hybride**

- `d7cc78c` : recherche vectorielle hybride via Qwen3-Embedding-0.6B servi en
  boucle locale (`infra/embed/sovereign-embed.service`) et
  `tools/reembed_validated_chunks.py`. **[C]** Code présent, déploiement non
  vérifié. D-028 autorise un petit moteur d'embeddings sous réserve de licence
  et d'empreinte vérifiées, mais `configs/runtime/` ne contient aucun lock pour
  ce modèle.

**Santé de la pile**

- `017e79f` : page `/sante` et `GET /v1/health`, session requise. **[C]**

**Bascule « chat rapide »**

- `aec81e3` : script hôte `infra/toggle/sovereign-fast-chat.sh`. **[C]** pour
  le script ; **[O]** pour les débits rapportés, environ 6 contre 9 à 11
  jetons/s. Voir les écarts ci-dessous.

**Refactorisations et tests sans changement de capacité**

- `d5ebe5d`, `63457d2`, `d2ad588`, `2858499`, `233a577` ; `ec56b30` fait
  répondre la passerelle par une erreur 503 au lieu de couper la connexion
  quand Qwen-Coder n'est pas configuré. **[C]**

### Tests

- Messages de commit : 470 tests verts à `dbca0c6`. **[O]**
- Exécution locale Windows du 2026-09-26 sur `db9414d`, Python 3.14 avec
  `-B` : 484 tests, 7 échecs, 6 erreurs, 2 sautés, liés à l'environnement
  Windows (API POSIX, modes de fichiers, séparateurs de chemin, fins de ligne)
  et à une connexion SQLite non fermée dans `tests/test_arena.py`. Cette
  exécution n'est pas une référence.
- Aucune CI n'est versionnée et aucune exécution Linux n'est consignée pour
  cette révision ; les comptes de 254 et 271 tests plus bas sont historiques.

### NUMA : deux paires A/B de sens opposé

- 2026-09-06 (`4e174a0`, `3775b3e`) : la médiane de A est 3,8 % au-dessus de
  celle de B.
- 2026-09-07, révision `6cebad1` (`docs/model/core-mini-numa-protocol.md`) : le
  comparateur v1 donne un ratio A/B de 0,9497, soit B environ 5,3 % au-dessus
  de A ; la médiane de B, 906,51 tokens/s, se situe dans la plage observée de
  A, de 751,45 à 926,16 tokens/s.
- Le sens s'inverse d'une paire à l'autre et les plages se recouvrent :
  l'observation est **non concluante**. Aucun placement n'est désigné, le gate
  G4 reste ouvert et la paire qui ferait foi reste **OUVERT**.
- Le comparateur de `main` (`d13b4cf`) ne vérifie pas que A et B reposent sur
  deux contrats de placement distincts ; l'engagement public étant salé à
  chaque run, cette distinction ne se contrôle pas depuis les preuves
  publiques.
- PR #16 : comparateur concurrent basé sur `codex/cpu-offline-harness`, qui
  n'accepte que l'évidence `0.1.0` et exprime le ratio en B/A.
  Recommandation, soumise au propriétaire : la fermer sans fusion ni rebase,
  ne pas la fusionner dans `codex/cpu-offline-harness`, et porter ses contrôles
  utiles sur le comparateur de `main`.

### Écarts aux règles constatés

1. **Déploiement ciblé hors archive.** La règle « les déploiements sont des
   archives versionnées », sans modification directe d'une release installée
   (section du 2026-09-08), n'a pas été suivie pour le correctif Qwen :
   `docs/operations/qwen-conversation-fix.md` consigne un déploiement ciblé de
   deux fichiers. **[R]** L'état installé ne se déduit donc plus du HEAD de
   `main`, et les commits suivants n'ont aucun relevé de déploiement.
2. **Suspension d'un entraînement pour le confort du chat.**
   `infra/toggle/sovereign-fast-chat.sh` (`aec81e3`) suspend l'entraînement
   CORE-30M par `SIGSTOP` et donne les deux sockets au moteur 14B, contre la
   règle « ne jamais interrompre un entraînement actif pour une opération de
   confort ». Le script vise une unité 14B absente du dépôt ; son usage réel et
   son état ne sont pas consignés. Décision du propriétaire requise.
3. **Suite par défaut de l'arène : le benchmark E2 scellé.**
   `services/arena/runner.py` (`SOVEREIGN_ARENA_SUITE`) et
   `tools/build_core_increment_from_arena.py` (`--suite`) désignent par défaut
   `configs/evaluation/core-python-e2.candidate.json`, alors que `1857089`
   pose que l'arène ne doit pas s'entraîner sur E2 ; `infra/arena/README.md`
   décrit aussi E2. Seul `tools/build_increments_for_approved_packets.py`
   pointe par défaut vers une copie de la suite d'entraînement. La suite
   utilisée par l'arène sur le serveur, si elle y a tourné, n'est consignée
   nulle part : **OUVERT**. Changer la valeur par défaut ne suffira pas :
   14 noms de fonction sont communs à E2 et à la suite d'entraînement. Si E2 a
   servi, la contamination des scores E2 et des incréments promus relève du
   propriétaire.

### Passages remplacés plus bas

Chaque passage concerné porte la mention « Remplacé le 2026-09-26, Rn ».

- **R1** : acquisition Qwen « aucune promotion ni chargement du modèle ». Voir
  la promotion du 2026-09-10 (`bf13670`, **[R]**).
- **R2** : conteneur de l'agent « sans interface réseau ». Une seule entrée est
  admise depuis la passerelle et la sortie est refusée (**[R]**, relevé de
  promotion).
- **R3** : runner E2 « prêt à être exécuté ». Il a été exécuté : 23/50, 38/50
  et 45/50 (**[R]**).
- **R4** : BOOTSTRAP « seul moteur quotidien » et « seul chat présenté comme
  exploitable ». Voir `QWEN-CODER` (**[R]**) et l'emplacement BOOTSTRAP libellé
  CHAT-14B (**[C]**, sans décision au registre).
- **R5** : branche d'intégration `codex/cpu-offline-harness`. Les 43 commits
  ont été intégrés directement sur `main` ; au 2026-09-26,
  `codex/cpu-offline-harness` vaut `main` plus un commit et porte la PR #17
  ouverte de Codex. Partir de `main` à jour.
- **R6** : RAG sémantique et agents actifs « pas terminés », comptes de 254 et
  271 tests. Voir RAG hybride, Profils de chat et Tests.
- **R7** : les 60 profils « désactivés », en « préparation fail-closed
  seulement », seul `coordination` exposé. Voir Profils de chat.
- **R8** : chat BOOTSTRAP 1.5B « sans outil, agent ou proxy MCP ». Voir Outils
  du chat et Emplacement BOOTSTRAP libellé « CHAT-14B ».
- **R9** : NUMA « A est 3,8 % au-dessus de B », paire du 2026-09-06. La paire
  du 2026-09-07 donne B environ 5,3 % au-dessus de A : résultat non
  concluant, voir NUMA.
- **R10** : index sans moteur d'embeddings, « aucun RAG sémantique ». Voir RAG
  hybride et Documents partagés.
- **R11** : runner et lock NumPy « committés et déployés ». État non
  revérifiable ; voir Vérification.

Les passages sur le Collector de conversations, l'export et la reprise des
conversations restent inchangés jusqu'à la fusion de la PR #17.

### Décisions du propriétaire en attente

Rien n'est tranché ici :

- emplacement BOOTSTRAP libellé CHAT-14B face à D-024 ;
- profils sélectionnables sans gates d'évaluation ;
- outils d'action : interrupteur réel, unité de la passerelle et bwrap ;
- documents partagés : niveau de confiance, isolation des extracteurs, effet
  d'une reconstruction de l'index ;
- activation de l'arène et de la boucle, suite utilisée, contamination E2,
  promotion en un clic appliquée en root sur une approbation non signée ;
- lock, licence et empreinte du modèle d'embeddings ;
- ligne d'`AGENTS.md` sur le DL380p Gen8 face à D-034 ;
- bascule « chat rapide » face à la règle de non-interruption ;
- identifiants d'infrastructure privés déjà présents dans le dépôt public ;
- sort de la PR #16.

### Travail possible pendant l'indisponibilité

- seulement du travail de dépôt conforme à la phase 0 d'`AGENTS.md` :
  documentation, schémas, ADR, outils statiques et tests, sans déploiement,
  port, appel fournisseur ni réseau dans les tests ;
- partir de `main` à jour et ne toucher ni `codex/cpu-offline-harness` ni les
  fichiers de la PR #17 ;
- `docs/project/current-capabilities.md` fait partie du manifeste RAG approuvé
  `project-internal-v1` : après sa modification, le chat cite l'ancien texte
  jusqu'à une nouvelle approbation du propriétaire et une reconstruction sur le
  serveur ;
- au retour du serveur, commencer par un relevé de l'état installé (commit ou
  fichiers par composant, présence de bwrap, poppler et Tesseract, suite de
  l'arène, état de la bascule, intégrité du checkpoint CORE-30M) et par une
  exécution Linux de la suite de tests, consignés dans `docs/operations/`.

## Mise à jour vérifiée — 2026-09-09

- le palier CORE-30M batch 8 de l'étape 500 à l'étape 1 000 est terminé.
  Le checkpoint final a été relu côté calcul et stockage durable avec la même
  empreinte SHA-256 ; ce palier valide la lignée batch 8 et ne mesure pas une
  capacité conversationnelle ou de programmation ;
- le corpus étendu a été redécoupé dans un dérivé RAW candidat par un outil du
  dépôt. Les 1 531 documents présents dans les holdouts pilote-v3 ont été
  retirés ; les nouveaux splits contiennent 166 421 en entraînement, 1 690 en
  validation et 1 771 en test, avec intersection holdout vérifiée à zéro. Ce
  dérivé reste en attente de revue et de promotion explicite ; aucun
  entraînement ne l'utilise encore ;
- la stratégie est désormais séparée : CORE-30M valide le pipeline CPU jusqu'à
  600 M tokens, sans cible de chat ; Qwen2.5-Coder-7B-Instruct Q4_K_M devient
  l'agent de programmation après acquisition RAW, contrôle de licence et
  empreintes, sur un nœud physique séparé ;
- l'artefact Qwen2.5-Coder-7B-Instruct Q4_K_M a été acquis dans RAW à la
  révision `13fb94bfda8c8cf22497dc57b78f391a9acb426a`, avec sa licence Apache-2.0
  de la même révision. La copie RAW relue fait 4 683 073 536 octets et son
  SHA-256 est `509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c`.
  Elle reste RAW : aucune promotion ni chargement du modèle n'a été effectué ;
  *[Remplacé le 2026-09-26, R1.]*
- un conteneur non privilégié distinct a été créé pour l'agent de programmation.
  Son runtime llama.cpp b10537 et sa dépendance CPU ont été transférés et
  vérifiés hors ligne ; `llama-server --version` démarre avec succès. Le
  conteneur ne possède aucune interface réseau ni outil d'administration du
  cluster ; *[Remplacé le 2026-09-26, R2.]*
- le split d'entraînement pilote-v3 a été pré-tokenisé intégralement en artefact
  persistant et lié par empreintes au manifeste, au split, au tokenizer et aux
  fichiers de tokens. Le runner vérifie ce contrat avant chaque démarrage et
  utilise le cache seulement s'il est identique au chemin autorisé ;
- l'équivalence a été testée structurellement sur 630 cas et vérifiée sur le
  corpus réel par 120 comparaisons de fenêtres. Le palier CORE-30M 1 110→2 110
  a mesuré environ 0,47 s par étape avec ce cache, contre environ 2,3 s avant ;
  ce gain de débit ne constitue pas une mesure de qualité ;
- le checkpoint CORE-30M de l'étape 2 110 a été archivé avec empreinte identique
  puis rechargé depuis sa copie durable. Les paliers ultérieurs doivent conserver
  cette règle : checkpoint atomique, destination absente, comparaison SHA-256,
  source conservée ;
- la lignée pré-tokenisée a ensuite franchi les étapes 3 110, 4 110 et 5 110.
  Les checkpoints 4 110 et 5 110 ont chacun une copie durable relue dont
  l'empreinte est identique à la source. Le calcul actif reste local au nœud de
  calcul et le stockage durable complet reste sur le NAS ;
- la lignée CORE-30M pré-tokenisée a atteint son palier final de 19 532 étapes.
  Son checkpoint final possède une copie durable relue avec une empreinte
  identique à la source. Ce résultat valide la reprise et l'archivage du pilote,
  sans démontrer une qualité conversationnelle ;
- le runner E1 reproductible charge le checkpoint seulement si ses empreintes
  de configuration, tokenizer, manifeste et préflight correspondent, puis
  prépare 50 réponses bornées pour une revue propriétaire séparée. Le checkpoint
  final a échoué ce garde sur une sortie répétitive : aucun paquet E1 n'a été
  créé et CORE-30M ne doit pas être présenté comme chat ou assistant de code ;
- le runner E2 contient cinquante tâches Python et retient uniquement des verdicts
  produits par leurs tests dans un bac à sable offline. Il est prêt à être
  exécuté lorsqu'un environnement Linux avec Bubblewrap est disponible ; il ne
  remplace pas E1 et ne transforme aucune réponse en donnée d'entraînement ;
  *[Remplacé le 2026-09-26, R3.]*
- la mémoire privée peut désormais exporter les paires complètes
  `user`/`assistant` déjà assainies en paquet candidat déterministe. Le paquet
  contient un manifeste, une empreinte relue après écriture et le compte des
  exclusions ; il reste `pending_owner_approval` et ne déclenche aucune
  promotion ni aucun entraînement ;
- une reprise opérateur des conversations antérieures est disponible. Elle
  refuse toute entrée non assainie ou dont l'empreinte ne correspond plus, et
  ne reprend jamais les rôles `system` ou `tool`. La base privée observée lors
  du déploiement ne contenait encore aucune paire complète à exporter ;
- le checkpoint CORE-30M de l'étape 1 110 a une copie durable dont l'empreinte
  est identique à la source. Son contrôle E0 est positif : contrat complet,
  chargement CPU et génération bornée déterministe ; cela ne constitue pas une
  évaluation de qualité et la réponse obtenue à ce palier est vide ;
- le runtime accepte une enveloppe de checkpoint seulement lorsqu'elle est
  liée au candidat demandé. Le format historique d'inférence demeure limité à
  CORE-700M ; cette correction est couverte par les tests ;
- l'audit du corpus étendu encore en RAW a relevé des recouvrements avec les
  splits pilote-v3 de test et validation. Toute promotion et tout entraînement
  sur ce corpus restent bloqués jusqu'à reconstruction des splits au niveau des
  paquets, sans fuite ;
- le reçu hors entraînement est une observation, non un seuil de qualité : la
  comparaison avec la perte d'entraînement et une évaluation propriétaire E1
  restent nécessaires. BOOTSTRAP demeure le seul moteur quotidien.
  *[Remplacé le 2026-09-26, R4.]*

## Mise à jour consolidée — 2026-09-08

Cette section **remplace les instantanés historiques plus bas dans ce fichier**.
Ils sont conservés uniquement pour la traçabilité de la tranche du 7 septembre.

### Point de départ

- dépôt : `PolishMen25/sovereign-local-ai` ; branche de travail :
  `codex/cpu-offline-harness` ; *[Remplacé le 2026-09-26, R5.]*
- actualiser le HEAD distant et vérifier le diff avant toute modification ;
- les déploiements sont des archives versionnées : préparer, tester, committer
  puis déployer une archive vérifiée ; ne jamais modifier directement une
  release installée ;
- aucun secret, artefact réel, checkpoint, corpus, identifiant ou détail
  d'exploitation privé ne doit rejoindre Git.

### État vérifié et limites

- l'interface privée, l'authentification et BOOTSTRAP fonctionnent ; BOOTSTRAP
  reste le moteur par défaut et le seul chat présenté comme exploitable ;
  *[Remplacé le 2026-09-26, R4.]*
- l'interface vérifie la santé locale de BOOTSTRAP avant de l'activer. Elle ne
  bascule jamais automatiquement vers CORE-700M si BOOTSTRAP est indisponible ;
  l'utilisateur doit choisir explicitement CORE pour un essai expérimental ;
- BOOTSTRAP transmet maintenant ses réponses locales progressivement à
  l'interface. Ce flux ne sort pas de la machine et une interruption conserve
  le message utilisateur dans l'historique sans inventer de réponse assistant ;
- CORE-700M est raccordé en expérimental. Ses premiers paliers démontrent
  chargement, génération bornée, checkpoint et reprise, mais pas une qualité
  linguistique : il ne doit jamais être présenté comme assistant utile ;
- le candidat CORE-30M compte 29 990 784 paramètres. Il permet de valider un
  apprentissage adapté au corpus disponible avant toute promesse sur CORE-700M ;
- les correctifs d'initialisation des embeddings et d'encodage BPE sont dans
  `ccb7c7f`, avec tests. Le runner accepte explicitement son nom de modèle et
  sa configuration, sans confondre CORE-30M et CORE-700M ;
- le tokenizer pilote 32k, le manifeste et le split pilote-v3 sont liés par
  empreintes et préflight ;
- le catalogue FR/EN est acquis uniquement en RAW. Il dépasse le pilote initial
  et contient trop peu de français pour être présenté comme corpus final ;
- mémoire SQLite, index lexical RAG, exports/suppressions de conversation et
  sauvegardes durables existent. RAG sémantique, agents actifs et RBAC final
  ne sont pas terminés ; *[Remplacé le 2026-09-26, R6.]*
- l'interface expose un état RAG sans contenu : au relevé, l'index lexical
  contenait quatre documents VALIDATED. Cet état ne rend ni RAW ni les
  conversations consultables par le RAG ;
- sur cette lignée, la suite complète compte 254 tests verts et un ignoré.
  Après l'ajout de l'export conversationnel et de sa reprise contrôlée, la
  suite compte 271 tests verts et un ignoré. *[Remplacé le 2026-09-26, R6.]*

### Invariants à préserver

- CPU-only ; aucun CUDA, ROCm, GPU ou TPU ; IA-CORE sans Internet ;
- RAW, quarantaine et VALIDATED restent séparés, sans promotion automatique ;
- les conversations assainies ne deviennent jamais des poids sans manifeste
  validé et empreintes ;
- `CC-BY-4.0` et `Etalab-2.0` sont admises avec attribution/provenance ;
  `CC-BY-SA`, `CC-BY-NC` et `CC-BY-ND` restent refusées ;
- MCP n'expose ni shell, ni chemin arbitraire, ni accès réseau arbitraire ;
  une sortie du modèle ne s'auto-confirme jamais pour une action durable.

### Calculs autonomes et reprise sûre

Avant toute action, détecter les calculs autonomes et les laisser finir. Ne
jamais interrompre un entraînement actif pour une opération de confort. Les
checkpoints sont nommés sans collision, archivés seulement si la destination
n'existe pas, puis relus et comparés par SHA-256 côté source et destination ;
la copie source est toujours conservée.

Le relevé du 8 septembre indique une lignée CORE-700M autonome ayant produit
un checkpoint durable à l'étape 1 000 et une lignée CORE-30M reprenant l'étape
110 vers 1 110 avec un archivage serveur vérifié en attente. Ce sont des
données opérationnelles volatiles : les recontrôler en direct, sans les
présenter comme mesure de qualité ou de durée.

### Ordre de travail

1. Observer les entraînements actifs ; à leur fin, contrôler métriques,
   checkpoint et restauration avant tout palier suivant.
2. Construire une évaluation versionnée pour CORE-30M ; distinguer perte,
   stabilité et qualité linguistique.
3. Préparer un corpus français-technique additionnel avec licence, provenance,
   empreintes et mesure FR/EN ; aucune promotion sans validation propriétaire.
4. Étendre le RAG seulement à des paquets VALIDATED avec provenance et test de
   restauration ; ne jamais indexer RAW ou les conversations par défaut.
5. N'activer un profil ou un outil que lorsque sa politique, ses limites,
   son audit et sa confirmation humaine sont testés.

En attendant un palier, un agent peut améliorer les tests, la documentation,
les runbooks, les vérifications de sauvegarde et la grille d'évaluation. Il ne
peut ni entraîner sans contrat validé, ni contourner un préflight, ni écraser
un checkpoint, ni acquérir/promouvoir implicitement du contenu.

### Commits de cette reprise interface

- `97ce24d` : disponibilité BOOTSTRAP vérifiée par l'interface et délai court
  pour l'état CORE ;
- `1758172` : réponses BOOTSTRAP progressives via le flux local SSE.
- `4362468` : état content-free de l'index lexical affiché dans le chat.
- `64ae6f0` : proposition E0/E1/E2 qui sépare intégrité, qualité bilingue et
  code vérifié avant toute utilité déclarée pour CORE.
- `0a5e98b` : suite E1 candidate de 50 prompts français/anglais, équilibrée et
  validée structurellement ; elle attend encore la revue propriétaire.
- `090dd6e` : lecture vérifiée du corpus pré-tokenisé, équivalente au chemin
  autorisé non mis en cache.
- `46541e3` : borne explicite du pilote CORE-30M jusqu'à 20 000 étapes.
- `9663a52` : export déterministe des conversations assainies en paquet
  candidat non approuvé.
- `fd743c6` : reprise explicite des anciens messages assainis avec refus sur
  contenu ou empreinte incohérents.
- `50192f5` : ADR et lock candidat de l'agent Qwen-Coder, avec séparation de
  CORE-30M et de l'agent de programmation ; `0f11e9d` : splitter du corpus
  étendu qui bloque toute fuite depuis les holdouts pilote.
- `0607f1a` : runner E1 CORE-30M atomique, reproductible et destiné à la revue
  propriétaire ; `ff16ad9` consigne le refus E0 du checkpoint final.
- `de71ef9` : suite E2 Python hors ligne, limites de ressources et verdicts de
  tests externes sans auto-évaluation du modèle ; `1f87ecb` porte la suite à
  cinquante tâches distinctes avant la mesure de l'agent Qwen.

## Branche de travail

- dépôt : `PolishMen25/sovereign-local-ai` ;
- branche d'intégration : `codex/cpu-offline-harness` ;
  *[Remplacé le 2026-09-26, R5.]*
- phase : découverte et prototypes bornés, aucun service n'est qualifié de
  production ;
- le dossier de travail d'un agent ne doit pas être supposé synchronisé : lire
  le HEAD distant et vérifier l'état Git avant toute modification.

## Invariants à préserver

- CPU-only, sans CUDA, ROCm, GPU ou téléchargement à l'exécution ;
- IA-CORE sans accès Internet ;
- BOOTSTRAP est un modèle tiers temporaire, jamais CORE ;
- RAW, quarantaine et VALIDATED restent séparés ;
- aucune promotion automatique de contenu externe ;
- Collector externe write-only, MCP Knowledge interne séparé ;
- aucun shell, chemin arbitraire ou accès réseau arbitraire via MCP ;
- le runner NUMA n'applique jamais un placement et ne publie jamais le contrat
  privé, l'identité de la machine, les listes CPU/NUMA, une commande ou un
  chemin ;
- les 60 agents sont des profils logiques partagés et restent désactivés tant
  que leurs gates ne sont pas franchis ; *[Remplacé le 2026-09-26, R7.]*
- aucun secret, poids, checkpoint, corpus réel ou détail interne dans Git.

## Ce qui fonctionne réellement

- chat BOOTSTRAP Qwen2.5-1.5B-Instruct en CLI locale CPU ; la passerelle Web du
  projet l'appelle sur la boucle locale et est exposée en HTTPS privé dans le
  tailnet, sans outil, agent ou proxy MCP ; *[Remplacé le 2026-09-26, R8.]*
- instanciation CPU historique et comptage exact de CORE-80M, conservé comme
  référence sans poids ;
- entraînement synthétique strict de CORE-MINI sur 20 étapes, checkpoint
  atomique puis reprise de 5 étapes jusqu'à l'étape 25 ; la compatibilité d'un
  ancien checkpoint historique reste à confirmer séparément sur Linux ;
- runner de preuve CORE-MINI NUMA implémenté avec contrat de placement externe,
  archive source et runtime offline vérifiés, contrôle INET flux/datagrammes
  fail-closed et répétitions bornées ; le doublon d'option a été corrigé,
  déployé et testé. Les preuves A/B ont produit trois répétitions chacune sur
  le même commit et workload ; un comparateur strict les a vérifiées. Le
  2026-09-06, A est 3,8 % au-dessus de B en médiane ; la paire du 2026-09-07
  (révision `6cebad1`) donne au contraire un ratio A/B de 0,9497, soit B
  environ 5,3 % au-dessus, avec des plages observées qui se recouvrent.
  L'observation est non concluante, sans décision de placement ;
  *[Remplacé le 2026-09-26, R9.]*
- prototype MCP Knowledge `stdio` sur trois notices synthétiques ;
- Collector de conversations write-only vers RAW ;
- stockage durable Synology monté par SMB 3.1.1 chiffré sur l'hôte de calcul,
  activé au démarrage et fourni à CORE par un point de montage contrôlé ; une
  écriture temporaire suivie de sa suppression et un aller-retour synthétique
  vérifié par empreinte ont réussi depuis CORE ; CORE ne conserve pas le secret
  SMB ;
- passerelle Web authentifiée déployée avec Argon2id, CSRF, `/v1/chat` réel vers
  BOOTSTRAP et mémoire SQLite locale exportable/supprimable ; première
  configuration propriétaire encore requise ;
- registre de 60 profils, orchestrateur et autorisations en préparation
  fail-closed seulement. *[Remplacé le 2026-09-26, R7.]*

## Tranche technique intégrée le 2026-09-01

- définition commune du decoder dans `services/inference/model.py`, partagée
  entre entraînement et future inférence, strictement CPU-only ;
- tokenizer Byte-BPE expérimental `0.2.0` avec NFC commun, fusions ordonnées,
  IDs spéciaux fixes, état runtime immuable, encode/decode et limites ;
- manifeste corpus `0.2.0` avec taille, empreinte et compte propres à chaque
  split ;
- chargeur `authorized_text_bundle.py` limité au split `train`, avec lignée
  contenu-free du corpus et du tokenizer ;
- producteur du tokenizer lié à l'empreinte exacte du split `train` ;
- mode `authorized-text` explicite dans `train_core_mini.py`, sans repli vers le
  générateur synthétique : il exige le manifeste autorisé, le JSONL `train` et
  le tokenizer correspondant, puis refuse un vocabulaire différent de celui du
  modèle ;
- contrat d'entraînement `0.2.0` sans contenu brut dans le checkpoint et journal
  de métriques strict lié à son SHA-256, avec étapes contiguës ; le checkpoint
  conserve l'empreinte du préfixe exact du journal exigé à la reprise ;
- chargement commun de la configuration CORE-MINI depuis une seule copie
  bornée : JSON strict, architecture et comptage exacts, SHA-256 calculé sur les
  mêmes octets ; parseurs CLI publics qui n'exposent pas les chemins reçus ;
- primitives partagées de checkpoint dans `services/inference/checkpoint.py` :
  chargement CPU `weights_only=True`, clés, formes, types et état AdamW
  stricts avant reprise, avec refus des strides, stockages et alias anormaux ;
- vérificateur offline des checkpoints historiques construit sur ces mêmes
  primitives ;
- summarizer de métriques `core-mini-metrics-summary.v2` : journal strict et
  borné, empreinte exacte des octets source, chauffe explicite, moyenne,
  médiane, écart-type de population, MAD et débit ; cette capacité porte sur
  un journal commençant à l'étape 1, ne recompose pas une reprise et ne ferme
  pas le gate du benchmark NUMA ;
- runner `tools/core_mini_numa_benchmark.py` Linux-only : CLI obligatoire
  `--run-root`, `--placement-contract`, `--benchmark-session-id` et
  `--source-archive`, paramètres bornés, configuration CORE-MINI fixe et contrat
  privé conforme à `schemas/core-mini-private-placement.schema.json` ;
- vérification exacte de l'affinité et de la politique mémoire dans chaque
  phase enfant, refus préalable des sockets flux/datagrammes `AF_INET`/`AF_INET6`,
  sonde enfant CPU-only, 3 à 10
  répétitions fraîches, résumé relu et checkpoint repris une étape sans
  modification ;
- artefact public fermé par `schemas/core-mini-numa-evidence.schema.json`, avec
  empreintes exactes et statistiques inter-répétitions, sans détail matériel,
  commande ou chemin ; son contrat `0.2.0` lie séparément les locks PyTorch et
  NumPy à l'observation réelle ; le commit est une déclaration au format strict,
  pas une lecture de Git par le runner ;
- candidat CORE-700M versionné avec comptage exact de 691 160 320 paramètres,
  CORE-80M conservé comme référence historique ;
- passerelle Web mono-utilisateur, authentification Argon2id, sessions, CSRF,
  mémoire conversationnelle masquée, export et suppression explicite ;
- index RAG lexical SQLite/FTS5 alimentable depuis les documents Markdown
  explicitement approuvés de la révision installée ; la route de chat BOOTSTRAP
  peut recevoir des extraits bornés et renvoyer les citations avec provenance.
  Aucun vecteur synthétique, moteur d'embeddings, document RAW, VALIDATED ou
  conversation ne rejoint cet index ; *[Remplacé le 2026-09-26, R10.]*
- Collector forcé sur loopback et relais Codex sans URL d'installation codée
  en dur ;
- relais Codex refusant toute redirection HTTP et validant le payload en file,
  l'état, l'identifiant et le SHA-256 du reçu avant d'enregistrer ce reçu puis
  de supprimer la file ;
- configuration Windows personnelle exclue, exemple générique versionné.

## Ce qui ne fonctionne pas encore

- aucun poids linguistique CORE utile ;
- le runtime PyTorch/NumPy CPU a été vérifié puis réinjecté hors ligne dans
  CORE ; CUDA est indisponible et non compilé. Aucun entraînement long n'est
  autorisé sans les gates corpus, tokenizer et benchmark ;
- aucun tokenizer ou corpus final approuvé ;
- aucun entraînement `authorized-text` n'a été exécuté de bout en bout avec
  PyTorch et un bundle réel approuvé : le chemin est implémenté et couvert par
  des tests unitaires et structurels, pas autorisé à produire des poids ;
- aucun runtime de génération CORE actif ;
- `/v1/chat` appelle réellement BOOTSTRAP et nomme le moteur ; l'interface
  reçoit un flux d'état puis la réponse finale, mais aucun token CORE n'est
  généré et BOOTSTRAP ne doit pas être confondu avec CORE ;
- aucun RAG sémantique, agent actif, RBAC final ou streaming de réponse ;
  *[Remplacé le 2026-09-26, R10.]*
- aucun choix de placement ni décision G4 n'est encore accepté ; les deux
  preuves et leur comparaison servent seulement d'observation descriptive ;
- l'isolation réseau complète et les restaurations de production restent des
  gates à prouver.
- mémoire et index lexical ont été sauvegardés, vérifiés et restaurés dans des
  fichiers de contrôle supprimés ensuite ; un checkpoint CORE-MINI synthétique
  est copié sur le stockage durable, restauré dans un fichier de contrôle puis
  repris offline avec succès. Le remplacement d'une base active, la restauration
  d'un checkpoint CORE-700M, les droits négatifs et la persistance après
  redémarrage intégral restent à terminer ;
- la mémoire active reste locale, mais une sauvegarde SQLite périodique
  vérifiée est déposée sur le NAS ; une restauration de remplacement reste
  manuelle et doit arrêter proprement la passerelle.

## Tranche interface et RAG du 2026-09-07

- `services/web/static/` remplace la page prototype par une interface française
  sans dépendance externe : première configuration, connexion, historique
  réouvrable, export, suppression, profil `coordination` et citations ;
- `GET /v1/session` rend uniquement les données nécessaires à la session
  same-origin ; le cookie reste `HttpOnly` et le jeton CSRF est contrôlé sur les
  écritures ;
- seuls le profil `coordination` est exposé et accepté par le chat. Les 60
  profils du registre sont toujours `draft` ; *[Remplacé le 2026-09-26, R7.]*
- `tools/build_project_knowledge_index.py` sépare désormais `manifest` et
  `build`. La construction exige le manifeste exact, son SHA-256 approuvé et
  une référence d'audit ; elle remplace l'index atomiquement après vérification
  des octets. Le service de reconstruction automatique a été désactivé ;
- ne jamais faire approuver automatiquement le manifeste. Préparer un candidat
  précis, faire valider son empreinte par le propriétaire, puis reconstruire
  hors de la passerelle et vérifier/restaurer sa sauvegarde.

## Ordre de reprise recommandé

1. tester la persistance du montage après redémarrage contrôlé, les droits
   négatifs et une restauration depuis le stockage durable ;
2. terminer la première configuration du compte propriétaire dans l'interface ;
3. confirmer la compatibilité d'un checkpoint CORE-MINI historique sur le
   nœud CPU avec le vérificateur offline ;
4. définir puis approuver les sources, licences, langues et exclusions du
   corpus ;
5. produire un tokenizer expérimental depuis le seul split `train`, évaluer sa
   qualité, puis faire approuver séparément son SHA-256 exact ;
6. exécuter le premier mini-entraînement `authorized-text` avec le bundle exact
   approuvé et conserver checkpoint, journal de métriques et lignée ;
7. évaluer ce run, vérifier sa reprise hors ligne, puis exporter un bundle
   d'inférence borné et vérifié ;
8. seulement après les gates, raccorder génération CORE, RAG, authentification,
   interface et profils d'agents.

## État de travail à vérifier avant reprise

Au moment de cette mise à jour, la correction du runner et le lock NumPy sont
committés et déployés. Toujours relire le HEAD distant et `git status` : cet
état est informatif et peut devenir obsolète. *[Remplacé le 2026-09-26, R11.]*

## Refus attendus

Un changement doit être refusé s'il introduit un téléchargement depuis CORE,
un build GPU, un tokenizer auto-approuvé, un corpus autre que `train`, une
promotion RAW automatique, un endpoint MCP générique, un secret dans Git ou une
revendication de capacité non mesurée.
