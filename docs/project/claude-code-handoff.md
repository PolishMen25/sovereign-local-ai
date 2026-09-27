# Reprise Claude Code

Dernière mise à jour : 2026-09-27, documentaire seulement : serveur de calcul
hors ligne, aucun relevé en direct depuis le 2026-09-10 ; registre des
décisions jusqu'à D-045 et `AGENTS.md` en phase 1 (D-038).

Ce document est le point de reprise public et expurgé. Il ne contient ni
adresse privée, compte, secret, chemin d'administration ou inventaire détaillé.
Lire d'abord `AGENTS.md`, `docs/project/decisions.md`,
`docs/project/current-capabilities.md`, `docs/architecture/overview.md` et
`docs/security/threat-model.md`.

## Mise à jour 2026-09-26 (serveur hors ligne)

Cette section prime sur toutes les sections plus bas, conservées pour la
traçabilité. Elle couvre les 43 commits intégrés sur `main` entre `8ec82e0`,
dernière mise à jour de ce fichier, et `db9414d` du 2026-09-13, puis les cinq
commits qui mènent `main` à `c0b169e` : `8eb9c07` et `5e28408` consignent
D-035 à D-042, `4775afb` réécrit `AGENTS.md` pour la phase 1, `1cf5daf` ajoute
le contrôleur de disponibilité du NAS et `c0b169e` l'interrupteur de D-035,
puis les neuf commits qui mènent `main` à `eea75b5`, résumés sous « Depuis
`c0b169e` » ci-dessous.
Elle a été rédigée sans accès au serveur de calcul et ne décrit **aucun état
d'exécution actuel**.

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
propriétaire absent de `docs/project/decisions.md`. « À régulariser » reprend
la liste de `AGENTS.md` des composants en service sans décision au registre ou
au-delà de leur décision : aucun agent ne les étend. Cette section ne tranche
aucun de ces choix.

### Registre et règles depuis `db9414d`

Décisions consignées par le propriétaire, avec l'état du code de `main` au
2026-09-27 :

- **D-035** : `run_python` et `write_file` derrière l'interrupteur
  `SOVEREIGN_ACTIONS_ENABLED`, désactivé par défaut, refus sûr et journalisé ;
  réactivation par décision distincte. Code sur `main` depuis `c0b169e`
  (#23) **[C]**, non déployé ; D-035 accepte l'écart de l'installation en
  service jusqu'au déploiement.
- **D-036** : adresses, noms d'hôte, identifiants de conteneurs et chemins
  d'hyperviseur internes sortent du dépôt public vers une configuration
  privée hors Git, avec échec fermé ; la configuration privée précède le
  déploiement du code ; historique Git non réécrit. Code sur `main` depuis
  `6a79309` (#24) **[C]**, non déployé : chargeur
  `services/common/private_endpoints.py`, fichier désigné par
  `SOVEREIGN_PRIVATE_ENDPOINTS_FILE`, épinglage exact conservé ; procédure
  dans `docs/operations/private-endpoints-migration.md`.
- **D-037** : intégration continue sur un runner Linux hébergé, sans secret ni
  déploiement automatique. Workflow `.github/workflows/tests.yml` sur `main`
  depuis `ad1ed68` (#19), sous Python 3.11 et 3.13.
- **D-038** : phase 1, socle expérimental en service ; `AGENTS.md` liste les
  composants rattachés à une décision et ceux à régulariser, et fixe ce qu'un
  agent peut modifier.
- **D-039** : une version de corpus est autorisée dès qu'une politique
  automatique versionnée et auditée produit son manifeste `VALIDATED` ; ratifie
  `6d959d7`. Cette politique n'est pas désignée dans le dépôt.
- **D-040** : code synthétique de l'arène admissible, généré par
  Qwen2.5-Coder, validé par ses tests, sans recouvrement avec les jeux
  d'évaluation, plafonné à 20 % des tokens d'une version de corpus ; sorties de
  BOOTSTRAP exclues. Validateurs pas encore alignés (voir le pont paquets) ;
  depuis `eea75b5` (#31), le constructeur d'incréments refuse les tâches E2.
- **D-041** : environ 40 % de français technique dans le corpus cible, par
  acquisition contrôlée de sources sous licence admise.
- **D-042** : tokenizer réentraîné sur le corpus final (vocabulaire 32 000,
  4 tokens spéciaux, contexte 2 048), accepté sur métriques mesurées ; la
  lignée CORE-30M garde l'ancien tokenizer.
- **D-043** : révocation de l'autorisation d'entraînement des incréments
  arena `0001` et `0002`, promus en `VALIDATED` le 2026-09-11 (tâches E2 et
  code de BOOTSTRAP) ; révocation append-only, originaux conservés ; les
  outils qui construisent un corpus doivent refuser un incrément révoqué. Non
  implémenté sur `main`.
- **D-044** : évaluation de code sur une suite E2-v2 scellée hors dépôt, dont
  seule l'empreinte est versionnée ; E2 étiquetée « contaminée ». Empreinte de
  E2-v2 non versionnée au 2026-09-27.
- **D-045** : approbation automatique réelle des paquets arena selon D-039 et
  D-040, acteur `policy:auto-v1`, chaîne d'audit, interrupteur d'arrêt et
  révocation. Non implémenté sur `main`. Son articulation avec la
  régularisation de l'arène demandée par `AGENTS.md` reste **OUVERT**.

### Depuis `c0b169e`

Neuf commits fusionnés par PR, tous **[C]** et sans relevé de déploiement :

- `6a79309` (#24) : points d'accès et identifiants privés hors Git (D-036).
- `485fd72` (#25) : connexion SQLite fermée dans `tests/test_arena.py`, D-025
  verrouillé sur la documentation publique, surface V0 du collecteur figée
  par des tests, Etalab-2.0 accepté par l'audit d'approbation.
- `ad1ed68` (#19) : CI de D-037.
- `654b730` (#26) : comparateur NUMA durci, contrat de sortie v2, vérificateur
  de distinction des placements, protocole G4 étendu PROVISOIRE.
- `367f48a` (#28) : D-043 à D-045 au registre.
- `48fc63f` (#27) : matrice des flux interzones, évaluation du tokenizer et
  évaluation de la recherche hors ligne.
- `30f5e8e` (#29) : contrats candidats d'ingestion et de quarantaine.
- `c7d1510` (#30) : ADR-0006 et ADR-0007 PROPOSÉS, note de décision G3,
  inventaire du corpus, lock candidat du modèle d'embeddings.
- `eea75b5` (#31) : grille d'évaluation V1 et suites candidates proposées ;
  E2 tenue hors du corpus par défaut.

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
- Le relevé de promotion place l'agent sur le DL380p Gen8, nœud physique
  séparé au sens de D-034. Le conflit avec l'ancienne ligne d'`AGENTS.md` est
  levé depuis `4775afb` : le DL380p Gen8 ne reçoit ni fonction CORE ni
  entraînement (D-006, remplacée par D-034), et l'agent Qwen s'exécute sur un
  nœud physique séparé, sans privilège d'administration du cluster.

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
- Activation : sans décision au registre ; `AGENTS.md` range l'arène et la
  boucle d'auto-entraînement parmi les composants à régulariser.
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
- D-040 admet ces données pour l'entraînement de CORE dans ses limites
  (Qwen2.5-Coder seulement, sans recouvrement avec les jeux d'évaluation, 20 %
  des tokens d'une version de corpus) et demande l'alignement des validateurs.
  Constats de code : `tools/validate_training_corpus_manifest.py` refuse
  encore un matériau `synthetic` autorisé `approved` ; les paquets enregistrent
  le moteur de chaque solution (`engine`), les profils `author-bootstrap` de
  `services/arena/league.py` sont servis par BOOTSTRAP, dont D-040 exclut les
  sorties, et les outils d'incrément ne lisent pas ce champ. Le modèle de
  confiance des approbations relève de la régularisation de l'arène ; le
  détail reste hors dépôt.
- D-043 révoque l'autorisation d'entraînement des incréments `0001` et
  `0002` ; D-045 active l'approbation automatique réelle des paquets. Ni l'une
  ni l'autre n'est implémentée sur `main`.

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
  `draft`. Sans décision au registre ; `AGENTS.md` range l'activation des
  profils du catalogue parmi les composants à régulariser.

**Documents partagés, OCR et analyse**

- `010706c`, `5c917de`, `a8151e7` : dépôt de document limité à 25 Mo,
  extraction hors ligne (texte, docx, PDF via poppler, OCR Tesseract), analyse
  map-reduce bornée à 30 passages, rappel RAG porté de 2 à 6 extraits, rendu
  Markdown. **[C]** La présence de poppler et Tesseract sur le serveur n'est
  pas consignée.
- Constats de code : les passages déposés passent par
  `HybridKnowledgeIndex.upsert_validated`
  (`services/knowledge/document_ingest.py`) et rejoignent la table du
  manifeste approuvé. Une reconstruction de l'index approuvé crée une base
  neuve limitée au manifeste, sans embeddings, puis remplace le fichier : sur
  la base de la passerelle, elle effacerait passages déposés et embeddings.
  Sans décision au registre ; `AGENTS.md` range l'analyse et le téléversement
  de documents parmi les composants à régulariser. Niveau de confiance des
  passages et isolement des extracteurs relèvent du propriétaire ; le détail
  reste hors dépôt.

**Outils du chat**

- `a133659` : boucle d'outils en lecture seule (`search_knowledge`,
  `list_documents`, `read_document`, `current_time`) sur l'emplacement
  `BOOTSTRAP`, enclenchée par défaut dans le code via
  `SOVEREIGN_TOOLS_ENABLED`. **[C]** Elle exige un serveur 14B lancé avec
  `--jinja`, dont l'unité n'est pas versionnée.
- `04473fe`, `3410b36` : actions `run_python` dans le bac à sable bwrap et
  `write_file` dans un espace de travail lisible par `GET /v1/workspace`,
  chacune derrière une confirmation humaine à usage unique. **[C]**
- `c0b169e` (#23) : interrupteur `SOVEREIGN_ACTIONS_ENABLED` de D-035. **[C]**
  Seule la valeur exacte `1`, lue au démarrage, active ces deux actions ;
  sinon elles ne sont pas offertes et toute proposition, confirmation ou
  exécution est refusée et journalisée sans contenu. Aucun déploiement n'est
  consigné ; D-035 accepte que l'installation en service garde son
  comportement antérieur jusqu'à ce déploiement, et leur réactivation exige
  une décision distincte. L'unité versionnée de la passerelle garde
  `PrivateDevices=yes` et n'autorise pas `AF_NETLINK`, contrairement à
  l'unité de l'arène qui les écarte pour bwrap. **HYPOTHÈSE** à vérifier sur
  le serveur : interrupteur activé, l'auto-test du bac à sable échouerait sous
  l'unité du dépôt et `run_python` ne serait pas proposé.
- Ces outils contredisent D-024, qui exclut « outil, agent, RAG » pour
  BOOTSTRAP. Boucle d'outils sans décision au registre, à régulariser selon
  `AGENTS.md`.

**Emplacement BOOTSTRAP libellé « CHAT-14B »**

- `9b31b41` : l'interface affiche l'emplacement `BOOTSTRAP` comme
  « CHAT-14B · Qwen2.5-14B local » ; `017e79f` : `/sante` l'affiche comme
  « Conversation (Qwen2.5-14B) ». **[C]**
- Le dépôt ne verrouille pourtant que Qwen2.5-1.5B
  (`configs/runtime/bootstrap-qwen2.5-1.5b-q4km.lock.json`, unité
  `infra/bootstrap-chat/` avec `--no-agent`). Aucun lock, licence, unité ni
  entrée du registre n'existe pour un 14B. Sans décision au registre ;
  `AGENTS.md` range le moteur 14B parmi les composants à régulariser.

**RAG hybride**

- `d7cc78c` : recherche vectorielle hybride via Qwen3-Embedding-0.6B servi en
  boucle locale (`infra/embed/sovereign-embed.service`) et
  `tools/reembed_validated_chunks.py`. **[C]** Code présent, déploiement non
  vérifié. D-028 autorise un petit moteur d'embeddings sous réserve de licence
  et d'empreinte vérifiées ; depuis `c7d1510`, un lock candidat
  (`configs/runtime/qwen3-embedding-0.6b-q8_0.lock.candidate.json`) attend la
  relecture RAW de l'empreinte et de la licence, et l'ADR-0007 est PROPOSÉ.
  `AGENTS.md` range ce moteur parmi les composants à régulariser.

**Santé de la pile**

- `017e79f` : page `/sante` et `GET /v1/health`, session requise. **[C]**

**Stockage durable avant relance du calcul**

- `1cf5daf` (#20) : contrôleur en lecture seule
  `tools/check_synology_readiness.py` et runbook PROVISOIRE
  `docs/operations/synology-restart-readiness.md`, que cite `AGENTS.md` avant
  toute relance du calcul. **[C]** Aucune exécution sur le NAS n'est consignée.

**Bascule « chat rapide »**

- `aec81e3` : script hôte `infra/toggle/sovereign-fast-chat.sh`. **[C]** pour
  le script ; **[O]** pour les débits rapportés, environ 6 contre 9 à 11
  jetons/s. Voir les écarts ci-dessous. Depuis `6a79309`, ses identifiants de
  conteneurs viennent d'une configuration privée hors Git (D-036).

**Refactorisations et tests sans changement de capacité**

- `d5ebe5d`, `63457d2`, `d2ad588`, `2858499`, `233a577` ; `ec56b30` fait
  répondre la passerelle par une erreur 503 au lieu de couper la connexion
  quand Qwen-Coder n'est pas configuré. **[C]**

### Tests

- Messages de commit : 470 tests verts à `dbca0c6`. **[O]**
- Exécution locale Windows du 2026-09-26 sur `db9414d`, Python 3.14 avec
  `-B` : 484 tests, 7 échecs, 6 erreurs, 2 sautés, liés à l'environnement
  Windows (API POSIX, modes de fichiers, séparateurs de chemin, fins de ligne)
  et à une connexion SQLite non fermée dans `tests/test_arena.py`, corrigée
  depuis par `485fd72`. Cette exécution n'est pas une référence.
- D-037 décide une intégration continue sur un runner Linux hébergé ;
  `ad1ed68` versionne son workflow et `485fd72` rapporte la suite Linux verte
  **[O]**. Aucune exécution sur le nœud de calcul n'est consignée ; les
  comptes de 254 et 271 tests plus bas sont historiques.

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
- Le comparateur employé pour ces paires (`d13b4cf`) ne vérifiait pas que A
  et B reposaient sur deux contrats de placement distincts ; l'engagement
  public étant salé à chaque run, cette distinction ne se contrôle pas depuis
  les preuves publiques. Depuis `654b730` (#26) **[C]**, le comparateur refuse
  deux preuves de même engagement et produit une sortie v2 fermée, et
  `tools/verify_core_mini_placement_distinctness.py` établit la distinction
  hors ligne à partir des contrats privés ; rien n'a été rejoué sur les
  preuves réelles.
- PR #16 : comparateur concurrent basé sur `codex/cpu-offline-harness`, qui
  n'acceptait que l'évidence `0.1.0` et exprimait le ratio en B/A. Fermée sans
  fusion le 2026-09-26 ; son commentaire de fermeture la rattache à une
  décision du propriétaire, et ses champs descriptifs sont repris par le
  contrat v2 de `654b730`.

### Écarts aux règles constatés

1. **Déploiement ciblé hors archive.** La règle « les déploiements sont des
   archives versionnées », sans modification directe d'une release installée
   (section du 2026-09-08, reprise par `AGENTS.md`, « Exploitation »), n'a pas
   été suivie pour le correctif Qwen :
   `docs/operations/qwen-conversation-fix.md` consigne un déploiement ciblé de
   deux fichiers. **[R]** L'état installé ne se déduit donc plus du HEAD de
   `main`, et les commits suivants n'ont aucun relevé de déploiement.
2. **Suspension d'un entraînement pour le confort du chat.**
   `infra/toggle/sovereign-fast-chat.sh` (`aec81e3`) suspend l'entraînement
   CORE-30M par `SIGSTOP` et donne les deux sockets au moteur 14B, contre la
   règle « ne jamais interrompre un entraînement actif pour une opération de
   confort », reprise par `AGENTS.md`, « Exploitation ». Le script vise une unité 14B absente du dépôt ; son usage réel et
   son état ne sont pas consignés. Décision du propriétaire requise.
3. **Suite par défaut de l'arène : le benchmark E2 scellé.** Jusqu'à
   `eea75b5`, `services/arena/runner.py` (`SOVEREIGN_ARENA_SUITE`) et
   `tools/build_core_increment_from_arena.py` (`--suite`) désignaient par
   défaut `configs/evaluation/core-python-e2.candidate.json`, alors que
   `1857089` pose que l'arène ne doit pas s'entraîner sur E2. Depuis
   `eea75b5` (#31) **[C]**, les deux prennent la suite d'entraînement par
   défaut et le constructeur refuse les tâches E2 ; les 14 noms de fonction
   communs aux deux suites restent listés en attente d'une décision du
   propriétaire. D-044 consigne que l'arène a joué sur E2 le 2026-09-11,
   étiquette E2 « contaminée » et la remplace par une suite E2-v2 scellée ;
   D-043 révoque l'autorisation d'entraînement des incréments `0001` et
   `0002`. La suite effectivement installée sur le serveur reste à relever.

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
  ont été intégrés directement sur `main` ; `codex/cpu-offline-harness`
  appartient à Codex et porte la PR #17. Partir de `main` à jour, une branche
  par lot (`AGENTS.md`, « Travail à plusieurs agents »).
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

- régularisation de l'emplacement BOOTSTRAP libellé CHAT-14B face à D-024 ;
- régularisation des profils sélectionnables sans gates d'évaluation ;
- réactivation éventuelle des actions après D-035, décision distincte, et
  unité de passerelle qu'exigerait bwrap ;
- documents partagés : niveau de confiance, isolement des extracteurs, effet
  d'une reconstruction de l'index ;
- régularisation de l'arène et de la boucle, et son articulation avec D-045,
  qui active l'approbation automatique réelle des paquets (**OUVERT**) ;
- traitement des 14 tâches communes à E2 et à la suite d'entraînement ;
- ratification du modèle d'embeddings au titre de D-028 (lock candidat depuis
  `c7d1510`, ADR-0007 PROPOSÉ) ;
- bascule « chat rapide » face à la règle de non-interruption.

Ne sont plus en attente : l'interrupteur des actions (D-035, code sur `main`
depuis `c0b169e`, non déployé), les identifiants d'infrastructure privés
(D-036, code sur `main` depuis `6a79309`, non déployé), la CI (D-037,
`ad1ed68`), la phase (D-038), la ratification de `6d959d7` et l'approbation
par version de corpus (D-039), l'admissibilité des incréments synthétiques
(D-040), la part de français (D-041), le tokenizer (D-042), la révocation des
incréments `0001` et `0002` (D-043), le remplacement de E2 par E2-v2 (D-044),
l'approbation automatique des paquets (D-045), la ligne d'`AGENTS.md` sur le
DL380p Gen8 (`4775afb`) et la PR #16, fermée sans fusion le 2026-09-26.

### Travail possible pendant l'indisponibilité

- seulement du travail de dépôt permis par la table de la phase 1 d'`AGENTS.md`
  (D-038) : documentation, schémas, ADR proposés, modèles de menace, outils
  locaux et tests, par PR avec tests et CI verts ; aucun déploiement tant que
  le serveur est hors ligne, aucun nouveau port, appel fournisseur ni réseau
  dans les tests, et aucune extension d'un composant à régulariser ;
- partir de `main` à jour et ne toucher ni `codex/cpu-offline-harness` ni les
  fichiers de la PR #17 ;
- `docs/project/current-capabilities.md` fait partie du manifeste RAG approuvé
  `project-internal-v1` : après sa modification, le chat cite l'ancien texte
  jusqu'à une nouvelle approbation du propriétaire et une reconstruction sur le
  serveur ;
- au retour du serveur, commencer par un relevé de l'état installé (commit ou
  fichiers par composant, présence de bwrap, poppler et Tesseract, suite de
  l'arène, état de la bascule, intégrité du checkpoint CORE-30M) et par une
  exécution Linux de la suite de tests, consignés dans `docs/operations/`,
  selon la séquence proposée par `docs/operations/ml350-return-runbook.md`.

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
