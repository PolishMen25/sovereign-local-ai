# Capacités réellement disponibles

Dernière vérification en direct : 2026-09-09. Dernier relevé versionné :
2026-09-10. Mise à jour documentaire : 2026-09-27, contre `main` à `eea75b5` :
registre des décisions jusqu'à D-045, `AGENTS.md` réécrit pour la phase 1
(D-038) ; depuis `db9414d`, le code a reçu l'interrupteur D-035, le contrôleur
de disponibilité du NAS, les points d'accès privés hors Git (D-036), la CI
(D-037), le comparateur NUMA durci, des contrats et outils candidats hors
ligne et la séparation par défaut entre E2 et l'arène, sans aucun relevé de
déploiement.

Ce document est la source de vérité publique sur l'état exécutable du projet.
Il distingue ce qui fonctionne de l'architecture visée, et ce qui a été relevé
de ce qui n'existe que dans le code.

## Vérification

- Le serveur de calcul ML350 est hors ligne depuis le 2026-09-14 environ. Rien
  n'a été revérifié en direct après le 2026-09-09, hormis les relevés
  versionnés cités ; le plus récent date du 2026-09-10.
- Chaque ligne décrit le code de `main` et le dernier relevé disponible, pas un
  état d'exécution présent. Au retour du serveur, l'état installé doit être
  relevé composant par composant avant toute nouvelle affirmation.
- Ce fichier fait partie du manifeste RAG approuvé `project-internal-v1`. Sa
  modification exige une nouvelle approbation du propriétaire puis une
  reconstruction de l'index ; d'ici là, le chat cite l'ancienne version.

## Niveaux de preuve

- **Vérifié en direct** : contrôle consigné dans ce document lors d'un relevé
  antérieur ou égal au 2026-09-09.
- **Relevé** : relevé de déploiement ou d'exploitation versionné dans le dépôt,
  dont le chemin est cité.
- **Observation de commit** : constat rapporté seulement par le message du
  commit cité, ni relu ni consigné ailleurs.
- **Code seul** : code et tests présents sur `main`, sans preuve de
  déploiement.

« Sans décision au registre » signale une capacité qui dépend d'un choix du
propriétaire absent de `docs/project/decisions.md`. « À régulariser » désigne
un composant que `AGENTS.md` range, depuis le passage en phase 1 (D-038),
parmi ceux en service sans décision au registre ou au-delà de leur décision :
aucun agent ne l'étend avant sa régularisation. Cette mention reprend
`AGENTS.md` ; elle n'est pas un relevé. « Décidé au registre, pas dans le
code » sépare une décision consignée de son implémentation sur `main`. Ce
document décrit l'état du code et des relevés ; il ne tranche aucun choix.

## Réponse courte

Au dernier relevé en direct, le 2026-09-09, il était possible de poser une
question à BOOTSTRAP depuis une CLI SSH ou une interface HTTPS privée de
tailnet et d'obtenir une réponse réellement générée. Le serveur étant hors
ligne, cet accès n'est pas revérifié.

L'agent de programmation Qwen2.5-Coder-7B a été promu par le propriétaire le
2026-09-10 et déployé sur un nœud physique séparé selon le relevé
`configs/runtime/qwen2.5-coder-7b-q4km.promotion.json`. La passerelle l'expose
comme moteur `QWEN-CODER` selon le relevé
`docs/operations/qwen-conversation-fix.md`.

Entre le 2026-09-10 et le 2026-09-13, `main` a reçu une arène d'agents, des
outils de chat, des profils sélectionnables, le dépôt de documents avec OCR et
une recherche hybride par embeddings. Aucun relevé versionné n'atteste leur
déploiement. `AGENTS.md` range le moteur 14B, la boucle d'outils, les profils
du catalogue, le moteur d'embeddings, les documents et l'arène parmi les
composants à régulariser. D-035 place les actions du chat derrière un
interrupteur désactivé par défaut, que le code de `main` implémente depuis
`c0b169e`, sans déploiement consigné.

CORE-30M valide l'entraînement CPU ; il n'est pas un chat. Ni CORE-MINI, ni
CORE-30M, ni CORE-700M ne sont présentés comme moteur conversationnel ou de
programmation utilisable. Conformément à D-034, CORE-700M ne reçoit pas de
palier long.

Le runner CPU/NUMA synthétique a produit deux paires A/B de sens opposé : le
2026-09-06, la médiane de A était 3,8 % au-dessus de B ; le 2026-09-07,
révision `6cebad1`, le ratio A/B vaut 0,9497, soit B environ 5,3 % au-dessus de
A, et les plages observées se recouvrent. L'observation est non concluante,
aucun placement n'est désigné et le gate G4 reste ouvert.

Le chemin `authorized-text` a servi à un entraînement CORE-MINI de 50 étapes
repris jusqu'à l'étape 60 ; ces étapes prouvent la reprise technique, pas une
capacité linguistique.

Le MCP Knowledge est utilisable séparément comme recherche lexicale dans un
petit catalogue synthétique. Il retourne des résumés et leur provenance ; il ne
génère pas une réponse d'IA.

## Matrice des composants

| Composant | État exact | Preuve | Ce qui fonctionne | Limite actuelle |
| --- | --- | --- | --- | --- |
| Runtime tensoriel CPU hors ligne | Installé et vérifié dans le conteneur CORE | Vérifié en direct | PyTorch `2.13.0+cpu` et NumPy `2.5.2` ont été réinjectés depuis des wheels vérifiés ; CUDA est indisponible et non compilé | Runtime technique isolé, pas un assistant ni des poids CORE |
| Emplacement de chat `BOOTSTRAP` | Qwen2.5-1.5B vérifié au relevé ; libellé « CHAT-14B » dans l'interface, sans décision au registre | Vérifié en direct pour le 1.5B ; code seul pour le libellé 14B (`9b31b41` pour l'interface, `017e79f` pour `/sante`) | Qwen2.5-1.5B-Instruct Q4_K_M générait réellement sur CPU avec llama.cpp en boucle locale ; la passerelle authentifiée nomme le moteur, conserve localement les échanges masqués et peut joindre des références avec provenance | Modèle tiers temporaire, pas CORE. L'interface et `/sante` présentent cet emplacement comme Qwen2.5-14B, alors que le dépôt ne verrouille que le 1.5B (lock et unité avec `--no-agent`) : aucun lock, licence, unité ni entrée du registre pour un 14B ; `AGENTS.md` range le moteur 14B parmi les composants à régulariser. D-024 exclut outil, agent et RAG pour BOOTSTRAP ; voir les outils de chat plus bas |
| Agent Qwen2.5-Coder-7B (`QWEN-CODER`) | Promu par le propriétaire le 2026-09-10 et déployé sur un nœud physique séparé selon le relevé | Relevés : `configs/runtime/qwen2.5-coder-7b-q4km.promotion.json` (`bf13670`, `e09c521`) et `docs/operations/qwen-conversation-fix.md` (`ac05afc`, `7b2111b`, `a2e40ea`, `1ba28b6`) | Empreintes SHA-256 relues en RAW, en VALIDATED et sur le nœud d'exécution ; E2 : 38/50 en un essai et 45/50 avec une passe de réparation, contre 23/50 pour Qwen2.5-1.5B ; la passerelle transmet les 20 derniers messages et les références lexicales ; une seule entrée réseau admise depuis la passerelle, sortie refusée ; réponse 503 quand le moteur n'est pas configuré (`ec56b30`, code seul) | État présent non revérifié. Le correctif de la passerelle a été déployé par fichiers ciblés, hors archive versionnée. La passe de réparation montre l'assertion échouée : elle mesure un agent qui lit ses erreurs |
| Évaluation de code et réparation | Outils hors ligne versionnés | Code seul : `e09c521`, `e292451`, `58c26c9` ; observation de commit : `0a1c2ee`, `58c26c9` | Générateur de candidats sans nouvel essai ; boucle écrire, tester, corriger avec `first_pass` et `final_pass` ; réparation de projet sur copie, fichiers de test jamais modifiés, diff remis à un humain ; budget de tâches et auto-test du bac à sable | Aucune exécution postérieure au 2026-09-10 consignée. `0a1c2ee` rapporte un bac à sable qui rejetait chaque tâche avant correction. D-044 étiquette E2 « contaminée » et la remplace, pour l'évaluation, par une suite E2-v2 scellée hors dépôt dont l'empreinte n'est pas encore versionnée ; les scores E2 cités restent historiques |
| CORE-MINI-1M | Entraînement `authorized-text` borné et reprise vérifiés | Vérifié en direct | Modèle de 1 328 256 paramètres ; 50 étapes sur le corpus approuvé, checkpoint durable, puis reprise contrôlée de 10 étapes jusqu'à 60 avec journal continu et empreintes ; modes explicitement séparés | 60 étapes ne produisent pas un assistant : aucune évaluation linguistique ni question CORE possible |
| CORE-30M | Pilote de pipeline, palier final de 19 532 étapes atteint | Relevé : section du 2026-09-09 de `docs/project/claude-code-handoff.md` | Checkpoint final avec copie durable relue et empreinte identique ; lecture pré-tokenisée liée par empreintes au manifeste, au split et au tokenizer | Pas un chat ni un assistant de code (D-034) : la tentative E1 du 2026-09-09 sur le checkpoint final a été refusée par le garde E0 sur une sortie répétitive (`ff16ad9`) ; aucun paquet E1 n'a été créé. Aucun entraînement postérieur au 2026-09-09 n'est consigné |
| Runner CORE-MINI NUMA | Deux paires A/B répétées, résultat non concluant | Vérifié en direct ; détail dans `docs/model/core-mini-numa-protocol.md` | Contrats privés hors Git, archive source et runtimes offline vérifiés, placement externe, sockets INET refusées, trois répétitions fraîches par placement et comparaison fermée | Paire du 2026-09-06 : A 3,8 % au-dessus de B. Paire du 2026-09-07, révision `6cebad1` : ratio A/B 0,9497, soit B environ 5,3 % au-dessus, plages observées qui se recouvrent. Non concluant, aucun placement désigné. Le comparateur employé pour ces paires ne vérifiait pas que les deux contrats de placement étaient distincts ; depuis `654b730` (code seul), il refuse deux preuves de même engagement et produit une sortie v2 fermée avec le recouvrement des plages, et `tools/verify_core_mini_placement_distinctness.py` établit la distinction à partir des contrats privés, sans exécution consignée sur ces preuves. Mesures mémoire/NUMA élargies et décision G4 absentes |
| Zone de calcul CORE | Invité non privilégié au relevé | Vérifié en direct | Runtime CPU hors ligne isolé, stockage de travail local et accès borné au stockage durable ; aucun téléchargement à l'exécution ; deux paliers CORE-700M exécutés | Aucun poids CORE utile ; preuve d'isolation après redémarrage reste à compléter |
| CORE-700M | Preuves mécaniques archivées | Vérifié en direct | Configuration, tokenizer et checkpoints techniques sont conservés pour traçabilité | Aucun entraînement long ni objectif de chat ou code ; cette voie est remplacée par D-034 |
| Corpus / tokenizer | Candidat 32k traçable | Vérifié en direct ; changement de gate `6d959d7`, ratifié par D-039 | Manifeste `0.2.0`, split `train` lié par taille/compte/SHA, Byte-BPE ordonné, NFC partagé, encode/decode et promotion `experimental` → `candidate_core` avec reçu | Depuis `6d959d7`, un manifeste `VALIDATED` suffit au préflight ; D-039 ratifie ce changement et autorise une version de corpus dès qu'une politique automatique versionnée et auditée produit ce manifeste. Cette politique n'est pas désignée dans le dépôt. D-041 vise environ 40 % de français technique, contre 0,42 % dans le catalogue RAW actuel. D-042 décide de réentraîner le tokenizer sur le corpus final (vocabulaire 32 000, 4 tokens spéciaux, contexte 2 048) ; le candidat actuel, entraîné sur 44 documents, reste celui de la lignée CORE-30M |
| Moteur d'inférence CORE | Runtime expérimental CPU au relevé | Vérifié en direct | Checkpoint d'inférence compact validé, contrat configuration/tokenizer/manifeste/préflight vérifié, API privée authentifiée sur une adresse privée configurée hors Git (D-036), génération gloutonne bornée et déterministe | Vingt étapes ne constituent pas une qualité linguistique ; aucune promesse d'assistant général. Le runtime ne reçoit ni Internet ni outil arbitraire |
| MCP Knowledge | Prototype `stdio` fonctionnel | Vérifié en direct | Handshake MCP, état, recherche lexicale et récupération bornée d'une provenance exacte | Trois notices synthétiques ; non raccordé au chat |
| RAG | Index lexical approuvé vérifié au relevé ; recherche hybride et documents partagés dans le code | Vérifié en direct pour l'index lexical ; code seul : `d7cc78c`, `010706c`, `5c917de` | L'index SQLite/FTS5 fournit des extraits bornés et des citations depuis quatre documents internes approuvés ; toute reconstruction exige un manifeste exact, son empreinte et une référence d'audit ; le rappel passe de 2 à 6 extraits (`5c917de`) | Conversations et RAW restent hors index. Les documents partagés y entrent aussi (voir plus bas). Ce fichier appartient au manifeste `project-internal-v1`, à réapprouver puis reconstruire |
| Moteur d'embeddings RAG | Code présent (`d7cc78c`), déploiement non vérifié | Code seul : `d7cc78c` | Client en boucle locale pour Qwen3-Embedding-0.6B servi par llama.cpp, recherche hybride avec repli lexical, `tools/reembed_validated_chunks.py` | D-028 autorise un petit moteur d'embeddings. Depuis `c7d1510`, un lock candidat `configs/runtime/qwen3-embedding-0.6b-q8_0.lock.candidate.json` attend la relecture RAW de l'empreinte, de la taille, de la révision et de la licence, et l'ADR-0007 est PROPOSÉ ; aucun service ne lit ce lock et le modèle n'est pas ratifié ; à régulariser selon `AGENTS.md` |
| Documents partagés et analyse | Code sur `main`, sans décision au registre ; à régulariser selon `AGENTS.md` | Code seul : `010706c`, `5c917de`, `a8151e7` | Dépôt jusqu'à 25 Mo, extraction hors ligne (texte, docx, PDF via poppler, OCR Tesseract), analyse map-reduce bornée à 30 passages, rendu Markdown des réponses | Les passages déposés sont écrits dans la table de l'index approuvé, par `upsert_validated` ; leur niveau de confiance et l'isolement des extracteurs relèvent de la régularisation par le propriétaire. Présence de poppler et Tesseract non consignée. Une reconstruction de l'index approuvé effacerait ces passages avec les embeddings |
| Outils de chat en lecture seule | Code sur `main`, sans décision au registre ; à régulariser selon `AGENTS.md` | Code seul : `a133659` | `search_knowledge`, `list_documents`, `read_document` et `current_time`, sans système de fichiers, shell ni réseau ; enclenchés par défaut dans le code via `SOVEREIGN_TOOLS_ENABLED` | Contredit D-024 pour BOOTSTRAP. Exige un serveur 14B lancé avec `--jinja`, dont l'unité n'est pas versionnée |
| Outils d'action | Code sur `main`, désactivé par défaut depuis `c0b169e` (D-035) ; non déployé | Code seul : `04473fe`, `3410b36`, `c0b169e` | `run_python` dans le bac à sable bwrap et `write_file` dans un espace de travail, chacun après une confirmation humaine à usage unique ; fichiers produits listés par `GET /v1/workspace` | Depuis `c0b169e`, seule la valeur exacte `SOVEREIGN_ACTIONS_ENABLED=1`, lue au démarrage, active ces actions ; sinon elles ne sont pas offertes et toute proposition, confirmation ou exécution est refusée et journalisée sans contenu. Aucun déploiement de ce code n'est consigné : D-035 accepte que l'installation en service garde son comportement antérieur jusqu'à ce déploiement, et toute réactivation exige une décision distincte. L'unité versionnée de la passerelle garde `PrivateDevices=yes` sans `AF_NETLINK`. **HYPOTHÈSE** : interrupteur activé, l'auto-test du bac à sable échouerait sous cette unité et `run_python` ne serait pas proposé |
| Collector de conversations | Ingress write-only fonctionnel | Vérifié en direct | Endpoint HTTPS de santé et dépôt authentifié vers RAW | Aucune lecture interne ni promotion automatique vers `VALIDATED` |
| Synology | Stockage durable monté et persistant sur l'hôte de calcul | Vérifié en direct | SMB 3.1.1 chiffré, compte de service limité, montage activé au démarrage, lecture/écriture CORE et aller-retour synthétique vérifiés via un point de montage contrôlé ; mémoire, index lexical et checkpoint CORE-MINI sont sauvegardés et restaurés avec empreintes vérifiées | Le remplacement d'une base utilisée, la restauration d'un checkpoint CORE-700M et le test de droits négatifs restent à faire. Depuis `1cf5daf`, `tools/check_synology_readiness.py`, en lecture seule, et le runbook PROVISOIRE `docs/operations/synology-restart-readiness.md` préparent la vérification du stockage avant relance du calcul ; aucune exécution n'est consignée (code seul) |
| Arène d'agents | Code sur `main` ; exécutions rapportées seulement par des commits ; activation sans décision au registre, à régulariser selon `AGENTS.md` | Code seul : `0dcbe8c`, `b5f0227`, `015b815`, `9b31b41`, `cd68960`, `d9c0e42`, `b486851` ; observations de commit : `8ef2f8a`, `dbca0c6`, `b486851` | Auteurs arbitrés par le bac à sable hors ligne, relecteur, Elo, paquets de 50 solutions avec manifeste et SHA-256 en attente d'approbation ; page `/arena` et approbations par fichier ; résumé en terminal ; santé mesurée sur l'ensemble retenu avec `max_task_share` borné à 0,25 | `docs/model/self-training-loop-spec.md` reste `INACTIVE`. Les commits rapportent 41 puis 28 paquets. D-044 consigne que l'arène a joué sur E2 le 2026-09-11 et étiquette E2 « contaminée ». Depuis `eea75b5` (code seul), la suite par défaut de `services/arena/runner.py` est la suite d'entraînement et E2 ne se joue que par choix explicite ; la suite jouée depuis le 2026-09-11 n'est pas consignée. D-045 active l'approbation automatique réelle des paquets selon D-039 et D-040 ; elle n'est pas implémentée dans le code de `main` |
| Suite d'entraînement de l'arène | 182 tâches versionnées | Code seul : `1857089`, `0655d42`, `db9414d`, `eea75b5` | `configs/arena/practice-suite.v1.json`, auto-validée par des solutions de référence, identifiants disjoints de E2 | Aucun relevé de chargement. 14 noms de fonction sont communs avec E2 ; `tests/test_arena_practice_suite.py` les liste en attente d'une décision du propriétaire et fait échouer tout nouveau recouvrement. Depuis `eea75b5`, l'arène (`services/arena/runner.py`) et `tools/build_core_increment_from_arena.py` la chargent par défaut ; le constructeur refuse une suite E2 et les solutions de tâches E2, et inscrit l'empreinte de la suite dans le manifeste d'incrément. `tools/build_increments_for_approved_packets.py` pointe par défaut vers une copie de cette suite hors dépôt, dont la présence n'est pas consignée |
| Incréments de corpus issus de l'arène | Code sur `main` ; usage rapporté par des commits ; admissibilité décidée au registre (D-040), validateurs pas encore alignés | Code seul : `229ffe0`, `689fa70`, `75d234a`, `0655d42` ; observations de commit : `5f59591`, `dbca0c6` | Paquet approuvé converti en incrément RAW synthétique déterministe ; promotion RAW → VALIDATED demandée depuis `/corpus` et appliquée par un service périodique qui vérifie l'empreinte ; aucun entraînement déclenché | D-040 admet pour l'entraînement de CORE le code synthétique de l'arène dont chaque solution passe ses tests en bac à sable, généré par Qwen2.5-Coder, étiqueté synthétique, sans recouvrement avec les jeux d'évaluation, dans la limite de 20 % des tokens d'une version de corpus ; les sorties de BOOTSTRAP restent exclues. D-040 résout le conflit entre `promote_arena_increment` et `validate_training_corpus_manifest` et demande l'alignement des validateurs ; dans le code de `main`, ce validateur refuse encore un matériau `synthetic` autorisé `approved`. Les paquets enregistrent le moteur de chaque solution (`engine`), les profils `author-bootstrap` de `services/arena/league.py` sont servis par BOOTSTRAP, et les outils d'incrément ne lisent pas ce champ. Le modèle de confiance des approbations relève de la régularisation de l'arène. `dbca0c6` rapporte 2 incréments pour 41 paquets. D-043 révoque l'autorisation d'entraînement des incréments `0001` et `0002`, promus en `VALIDATED` le 2026-09-11 ; les outils qui construisent un corpus doivent refuser un incrément révoqué, ce que le code de `main` ne fait pas encore |
| Orchestrateur | Préparation fail-closed | Vérifié en direct | Chargement du registre et validation partielle d'enveloppes/permissions | Aucun appel de modèle, d'outil ou de file d'exécution ; les outils du chat passent par la passerelle, pas par l'orchestrateur |
| Profils d'agents | Registre de 60 profils `draft` ; profils sélectionnables dans le chat par le code, sans décision au registre, à régulariser selon `AGENTS.md` | Code seul : `5891fff`, `91ff285`, `9ac11cd` | Selon `91ff285`, 59 profils du catalogue deviennent sélectionnables (49 sur le moteur 14B avec outils, 10 de la famille `development` sur Qwen-Coder), avec `coordination` et les agents d'arène approuvés, groupés par famille | Les gates d'évaluation par profil ne sont pas appliqués ; seul un commentaire de `services/web/catalog_profiles.py` l'attribue à un choix du propriétaire. `configs/agents/registry.json` garde les 60 profils en `draft` |
| Mémoire conversationnelle | SQLite local avec sauvegarde durable vérifiée | Vérifié en direct | Masquage de secrets, empreintes, historique, export, suppression avec reçu sans contenu et sauvegarde SQLite vérifiée vers le NAS | Pas raccordée au RAG ; restauration applicative de remplacement reste manuelle |
| Interface Web du projet | Passerelle installée derrière le HTTPS privé au relevé du 2026-09-09 | Vérifié en direct ; relevé `docs/operations/qwen-conversation-fix.md` pour le moteur Qwen ; code seul pour les pages ajoutées ensuite | Première configuration, login, CSRF, historique réouvrable, export, suppression et `/v1/chat` vers llama.cpp, CORE ou Qwen-Coder ; le sélecteur marque CORE-700M comme expérimental ; pages `/arena`, `/corpus` et `/sante` dans le code | Depuis le correctif ciblé, aucune archive versionnée ne correspond au HEAD de `main` : l'état installé est inconnu |
| Page `/sante` | Code sur `main` | Code seul : `017e79f` | `GET /v1/health` et page authentifiée : joignabilité des moteurs, index, arène, incréments, espace de travail et ressources du conteneur de la passerelle | Décrit le conteneur de la passerelle, pas l'hôte ; libelle l'emplacement BOOTSTRAP comme Qwen2.5-14B |
| Bascule « chat rapide » | Script hôte versionné, sans décision au registre | Code seul : `aec81e3`, `6a79309` ; observation de commit pour les débits rapportés | Suspend l'entraînement CORE-30M par `SIGSTOP` et donne les deux sockets au moteur 14B, puis reprend par `SIGCONT` | Contraire à la règle de ne jamais interrompre un entraînement pour une opération de confort ; vise une unité 14B absente du dépôt ; usage et état non consignés. Depuis `6a79309`, les identifiants de conteneurs viennent d'une configuration privée hors Git (D-036) |
| Authentification/RBAC | Argon2id et sessions en place au relevé | Vérifié en direct | Secret propriétaire créé dans le navigateur, jetons de session hachés, cookie sécurisé et CSRF | Initialisation du compte propriétaire non consignée ; politiques des agents non raccordées |

## Correspondance des commits

Les 43 commits de `8ec82e0..db9414d` se répartissent ainsi :

- Agent Qwen-Coder : `ac05afc`, `7b2111b`, `a2e40ea`, `1ba28b6`, `bf13670`,
  `e09c521`, `ec56b30` ;
- Évaluation de code et réparation : `0a1c2ee`, `e09c521`, `e292451`,
  `58c26c9` ;
- Arène d'agents : `0dcbe8c`, `b5f0227`, `015b815`, `9b31b41`, `8ef2f8a`,
  `cd68960`, `d9c0e42`, `b486851` ;
- Suite d'entraînement de l'arène : `1857089`, `0655d42`, `db9414d` ;
- Incréments de corpus : `229ffe0`, `689fa70`, `75d234a`, `0655d42`,
  `5f59591`, `dbca0c6` ;
- Profils d'agents : `5891fff`, `91ff285`, `9ac11cd` ;
- Documents partagés et RAG : `010706c`, `5c917de`, `a8151e7`, `d7cc78c` ;
- Outils de chat : `a133659`, `04473fe`, `3410b36` ;
- Emplacement BOOTSTRAP libellé CHAT-14B : `9b31b41`, `017e79f` ;
- Page `/sante` : `017e79f` ;
- Bascule « chat rapide » : `aec81e3` ;
- refactorisations et tests sans changement de capacité : `d5ebe5d`,
  `63457d2`, `d2ad588`, `2858499`, `233a577`.

Les cinq commits de `db9414d..c0b169e` : `8eb9c07` consigne D-035 à D-038,
`4775afb` réécrit `AGENTS.md` pour la phase 1, `5e28408` consigne D-039 à
D-042, `1cf5daf` ajoute le contrôleur en lecture seule
`tools/check_synology_readiness.py` et son runbook
`docs/operations/synology-restart-readiness.md`, et `c0b169e` implémente
l'interrupteur `SOVEREIGN_ACTIONS_ENABLED` de D-035. Aucun des deux derniers
n'a de relevé de déploiement ni d'exécution sur le serveur.

Les neuf commits de `c0b169e..eea75b5`, tous sans relevé de déploiement ni
d'exécution sur le serveur : `6a79309` (#24) sort du code les points d'accès
et identifiants privés vers une configuration hors Git (D-036) ; `485fd72`
(#25) ferme la connexion SQLite fuitée par `tests/test_arena.py`, verrouille
D-025 sur la documentation publique, fige par des tests la surface V0 du
collecteur et accepte Etalab-2.0 dans l'audit d'approbation ; `ad1ed68` (#19)
versionne la CI de D-037 ; `654b730` (#26) durcit le comparateur NUMA et
ajoute son contrat v2, le vérificateur de distinction et le protocole G4
étendu PROVISOIRE ; `367f48a` (#28) consigne D-043 à D-045 ; `48fc63f` (#27)
ajoute la matrice des flux interzones, l'évaluation du tokenizer et
l'évaluation de la recherche hors ligne ; `30f5e8e` (#29) ajoute des contrats
candidats d'ingestion et de quarantaine ; `c7d1510` (#30) propose les ADR-0006
et 0007, la note de décision G3, l'inventaire du corpus et le lock candidat
d'embeddings ; `eea75b5` (#31) propose la grille d'évaluation V1 et ses suites
candidates et tient E2 hors du corpus par défaut.

## Vérifications confirmées jusqu'au 2026-09-10

Ces contrôles ont été faits en direct avant l'arrêt du serveur. Ils décrivent
l'état à leur date.

- PyTorch `2.13.0+cpu` et NumPy `2.5.2` ont été vérifiés contre leurs locks puis
  installés hors ligne dans un runtime isolé ; CUDA est indisponible et non
  compilé, et quatre tests CPU ciblés passent dans ce runtime ;
- après cette installation, CORE ne présente aucune route par défaut ; une
  résolution DNS externe et une connexion TCP directe de contrôle vers Internet
  sont refusées ;
- un entraînement CORE-MINI `authorized-text` de 50 étapes a produit un
  checkpoint durable, puis a repris 10 étapes jusqu'à l'étape 60 sur Linux ;
  les métriques restent continues et liées au même corpus et tokenizer. Ce
  palier prouve la reprise technique, pas une capacité conversationnelle ;
- CORE-700M a été instancié et entraîné sur CPU pour une étape réelle, puis
  restauré depuis ce checkpoint et entraîné jusqu'à l'étape 2 ; les deux
  checkpoints sont persistés. Ce test prouve le chemin technique, pas la
  qualité du modèle ni une capacité conversationnelle ;
- le harness et la future inférence partagent maintenant la même définition
  CPU-only du decoder, sans modifier le format des checkpoints existants ;
- le trainer et le vérificateur lisent, valident et hachent la configuration
  CORE-MINI depuis une seule copie d'octets bornée, avec architecture et
  comptage exacts ; leurs parseurs publics n'exposent pas les chemins reçus ;
- le tokenizer Byte-BPE normalise, encode et décode de façon déterministe,
  refuse les fusions ou couvertures d'octets incohérentes et borne les entrées ;
- le chargeur de texte autorisé refuse toute partition autre que `train` et lie
  corpus, manifeste et tokenizer sans recopier leur contenu dans la lignée ;
- `train_core_mini.py` n'active ce chargeur que par
  `--data-mode authorized-text`, exige les trois artefacts, vérifie le
  vocabulaire exact et ne bascule jamais implicitement vers les données
  synthétiques ;
- le journal `authorized-text` refuse les clés ou valeurs inattendues, lie
  chaque mesure au SHA-256 du contrat et vérifie la continuité avant reprise ;
  son préfixe exact est haché dans le checkpoint puis exigé lors d'une reprise ;
- le harness et le vérificateur partagent les contrôles stricts de l'état du
  modèle et de l'optimiseur, y compris les strides, stockages et alias AdamW ;
  la compatibilité d'un ancien checkpoint historique n'a pas encore été
  prouvée ;
- le summarizer de métriques `v2` valide strictement un journal synthétique ou
  `authorized-text`, publie le SHA-256 exact de ses octets et calcule, après
  chauffe, moyenne, médiane, minimum, maximum, écart-type de population, MAD et
  débit ; il exige un journal commençant à l'étape 1, ne recompose pas une
  reprise, n'agrège pas plusieurs runs et ne constitue pas une preuve de
  benchmark NUMA complet ;
- le runner NUMA exige un nouveau répertoire de run absolu, un contrat privé
  strict hors Git, une session `session-<UUID v4>` et une archive Git source
  canonique ; les répétitions, étapes, chauffe, lot, séquence,
  threads, graine et délais sont bornés ;
- avant tout run, il exige que les sockets flux et datagrammes des familles
  `AF_INET` et `AF_INET6` soient déjà refusées, compare exactement affinité et
  politique mémoire au contrat privé, puis confirme l'environnement CPU-only
  dans un processus enfant ;
- chaque répétition emploie des processus frais sans shell, relit le résumé
  `v2`, reprend le checkpoint une étape avec le vérificateur offline et refuse
  toute dérive d'empreinte, de placement ou de source ; la sortie publique ne
  contient aucun hostname, détail CPU exact, commande ou chemin ;
- BOOTSTRAP charge ses poids GGUF vérifiés et génère du texte français localement ;
- un premier échange français a été généré localement ;
- le service BOOTSTRAP persistant est lié à la boucle locale, fonctionne sans
  outils, agent, proxy MCP ou téléchargement à l'exécution ; la passerelle Web
  authentifiée l'appelle localement et est relayée en HTTPS privé au tailnet.
  Ce constat précède les outils de chat ajoutés au code à partir de `a133659` ;
- le MCP Knowledge répond actuellement en `stdio` et voit trois notices
  synthétiques ;
- une recherche `stockage hybride` retourne des résumés avec `provenance_id` ;
- la passerelle Web propre au projet est installée sur le sas ; son endpoint de
  chat appelle réellement BOOTSTRAP et sa mémoire SQLite locale prend en charge
  historique, export et suppression explicite ;
- le service d'index local a construit la base SQLite/FTS5 depuis les vingt
  documents Markdown livrés avec la révision installée ; une recherche lexicale
  locale a renvoyé des documents et leurs empreintes de provenance ;
- une sauvegarde de l'index lexical a été créée puis vérifiée et restaurée dans
  un fichier de contrôle, avec empreinte identique ; ce fichier de contrôle a
  été supprimé sans remplacer la base utilisée par la passerelle ;
- le manifeste RAG interne `project-internal-v1` a été approuvé et reconstruit
  atomiquement depuis quatre documents versionnés (capacités, décisions,
  architecture et modèle de menace) ; son empreinte de contenu est
  `f2176bce068c4da8eb89cb0ef615c3d2a36a33756d4da7f345cbbdaa30189de5`. Cette
  révision du fichier des capacités ne correspond plus à cette empreinte ;
- la sauvegarde durable de cet index approuvé a été restaurée dans un fichier
  de contrôle isolé ; le vérificateur a confirmé son empreinte, puis le fichier
  de contrôle a été supprimé sans remplacer la base utilisée par la
  passerelle ;
- un run CORE-MINI synthétique frais de vingt étapes a produit un checkpoint,
  copié vers le stockage durable puis restauré dans un fichier de contrôle avec
  la même empreinte ; le vérificateur offline a repris cette copie à l'étape 21
  et l'a déclarée compatible CPU-only, réseau désactivé ;
- le relais HTTPS du Collector répond en mode `write-only` ; son expéditeur
  refuse les redirections, valide chaque payload en file et ne le supprime
  qu'après écriture atomique et vérification locale d'un reçu concordant ;
- le stockage durable Synology est monté avec SMB 3.1.1 chiffré sur l'hôte de
  calcul, activé au démarrage puis fourni au conteneur CORE par un point de
  montage contrôlé ; une écriture de contrôle temporaire suivie de sa
  suppression et un aller-retour synthétique vérifié par empreinte ont réussi
  depuis CORE ; le conteneur ne conserve pas le secret SMB ;
- le 2026-09-09, la passerelle a été déployée par fichiers ciblés pour
  transmettre à Qwen-Coder son historique et ses références, puis un appel réel
  a restitué les deux valeurs attendues (relevé
  `docs/operations/qwen-conversation-fix.md`) ;
- le 2026-09-10, Qwen2.5-Coder-7B a été promu par le propriétaire avec
  empreintes relues en RAW, en VALIDATED et sur son nœud, puis isolé à une seule
  entrée réseau depuis la passerelle (relevé
  `configs/runtime/qwen2.5-coder-7b-q4km.promotion.json`).

### Tests

- À la révision `8071843`, alors installée, 198 tests passaient, lock NumPy et
  preuve NUMA renforcée compris (relevé historique de ce document).
- Les messages de commit rapportent 470 tests verts à `dbca0c6`
  (observation de commit).
- Une exécution locale Windows du 2026-09-26 sur `db9414d`, Python 3.14 avec
  `-B`, compte 484 tests : 7 échecs, 6 erreurs et 2 sautés, liés à
  l'environnement Windows et à une connexion SQLite non fermée dans un test,
  corrigée depuis par `485fd72`. Elle n'est pas une référence.
- D-037 décide une intégration continue GitHub sur un runner Linux hébergé,
  sans secret ni déploiement automatique ; `ad1ed68` versionne
  `.github/workflows/tests.yml`, qui exécute la suite sous Python 3.11 et
  3.13. `485fd72` rapporte la suite Linux verte (observation de commit).
  Aucune exécution sur le nœud de calcul n'est consignée.

Le relais HTTPS et le coffre ont été établis comme preuves opérationnelles
réversibles pendant la phase 0. Le passage en phase 1 (D-038) ne valide ni
l'orientation P-002, ni la topologie cible, ni un gate : G0 à G8 et A0 à A8
restent ouverts tant que leurs preuves ne sont pas acceptées.

Ces contrôles ne prouvent pas encore l'isolation réseau complète après tous les
scénarios de redémarrage, la qualité d'un modèle linguistique ou la
disponibilité d'un service de production.

## Utilisation au dernier relevé

Au relevé du 2026-09-09, le chat BOOTSTRAP était disponible en CLI SSH et la
passerelle Web sur le HTTPS privé décrit dans [le runbook
BOOTSTRAP](../operations/bootstrap-chat-cli.md) ; le propriétaire devait
d'abord activer son client tailnet puis terminer la première configuration du
compte dans le navigateur. La CLI ouvre une conversation interactive réelle ;
`/exit` ou `Ctrl+C` la termine. Tant que le serveur est hors ligne, aucun de
ces accès n'est disponible.

Depuis la racine du dépôt, sans serveur :

```bash
# Vérifier le socle
python3 -B -m unittest discover -s tests -q

# Vérifier les nombres de paramètres
python3 -B tools/count_core_parameters.py \
  --config configs/models/core-mini.candidate.json
python3 -B tools/count_core_parameters.py \
  --config configs/models/core-700m.candidate.json
```

Après réinjection et vérification hors ligne du bundle PyTorch CPU, CORE-MINI
peut être entraîné sur un répertoire neuf :

```bash
python -B -m tools.train_core_mini \
  --config configs/models/core-mini.candidate.json \
  --output-dir runs/core-mini-demo \
  --steps 20 \
  --batch-size 4 \
  --sequence-length 64 \
  --threads 20
```

Cette commande produit une preuve technique, pas un modèle auquel parler.

Le runner NUMA est lui aussi un outil de preuve, pas une commande
d'activation. Sa CLI et ses préconditions sont décrites dans le
[protocole CORE-MINI NUMA](../model/core-mini-numa-protocol.md). Les arguments
obligatoires sont `--run-root`, `--placement-contract`,
`--benchmark-session-id` et `--source-archive`. Une instance réelle du contrat
de placement reste privée et ne doit jamais être ajoutée au dépôt.

Le mode `authorized-text` est volontairement inutilisable sans les trois
artefacts approuvés et concordants. Sa forme de commande est documentée dans
[le gate corpus et tokenizer](../model/corpus-and-tokenizer-gate.md) ; elle ne
doit pas être exécutée avec un contenu réel avant l'approbation du gate.

Le MCP Knowledge peut être interrogé par un client MCP compatible `stdio` avec
les outils suivants :

- `knowledge_status {}` ;
- `search_validated {"query": "stockage hybride"}`.

## Suite du travail selon D-034

D-034 sépare deux voies. CORE-30M valide le pipeline CPU jusqu'à son budget de
600 M tokens, sans objectif conversationnel ; Qwen2.5-Coder-7B est l'agent de
programmation réel ; CORE-700M ne reçoit pas de palier long. La section
historique qui décrivait comment rendre le chat CORE-700M utilisable est donc
retirée.

Avant toute nouvelle affirmation de capacité, il reste à :

1. relever l'état installé au retour du serveur, composant par composant, et
   exécuter la suite de tests sur Linux ;
2. faire réapprouver par le propriétaire le manifeste RAG `project-internal-v1`
   modifié par cette page, puis reconstruire et vérifier l'index ;
3. constituer le corpus selon D-039 et D-041, réentraîner le tokenizer selon
   D-042 et faire approuver la grille d'évaluation ; tout nouveau palier
   d'entraînement exige en outre un contrat approuvé par le propriétaire et le
   gate correspondant accepté (`AGENTS.md`) ;
4. fermer le gate G4 par un benchmark reproductible accepté par le
   propriétaire ;
5. valider l'isolation réseau, les droits, l'audit, les sauvegardes et la
   restauration avant toute extension d'un service.

BOOTSTRAP fournit le chat immédiat, mais ne franchit aucune de ces étapes et ne
doit jamais être présenté comme CORE. Aucune inférence distante n'est utilisée.

## Décidé au registre, pas encore dans le code

Au 2026-09-27, ces décisions sont consignées mais le code de `main` ne les
implémente pas encore, ou seulement en partie ; aucune n'est déployée. D-035,
D-036 et D-037 n'en font plus partie : l'interrupteur des actions est sur
`main` depuis `c0b169e`, la configuration privée hors Git depuis `6a79309` et
la CI depuis `ad1ed68` ; les deux premiers n'ont aucun déploiement consigné,
et la configuration privée doit précéder le déploiement du code de D-036.

- D-039 : politique automatique versionnée et auditée qui produit le manifeste
  `VALIDATED` d'une version de corpus ;
- D-040 : alignement des validateurs de corpus et exclusion des solutions
  qui ne viennent pas de Qwen2.5-Coder ; depuis `eea75b5`, le constructeur
  d'incréments refuse déjà une suite E2 et les solutions de tâches E2 ;
- D-041 : acquisition, par le flux contrôlé, de sources françaises sous
  licence admise et plan d'échantillonnage déterministe versionné ;
- D-042 : tokenizer réentraîné sur le corpus final et accepté sur métriques
  mesurées ;
- D-043 : révocation tracée des incréments `0001` et `0002`, et refus de tout
  incrément révoqué par les outils qui construisent un corpus ;
- D-044 : suite E2-v2 scellée hors dépôt, dont l'empreinte est versionnée et
  vérifiée par les outils d'évaluation avant usage ;
- D-045 : approbation automatique réelle des paquets de l'arène par la
  politique de D-039 (acteur `policy:auto-v1`), avec chaîne d'audit,
  interrupteur d'arrêt et révocation.

## Décisions du propriétaire en attente

Ce document ne tranche aucun de ces points :

- l'emplacement BOOTSTRAP libellé CHAT-14B face à D-024 ;
- les profils sélectionnables sans gates d'évaluation ;
- la réactivation éventuelle des actions après D-035, décision distincte, et
  l'unité de passerelle qu'exigerait bwrap ;
- les documents partagés : niveau de confiance, isolement des extracteurs et
  effet d'une reconstruction de l'index ;
- la régularisation de l'arène et de la boucle, que `AGENTS.md` range parmi
  les composants à régulariser, et son articulation avec D-045, qui active
  l'approbation automatique réelle des paquets (**OUVERT**) ;
- le traitement des 14 tâches communes à E2 et à la suite d'entraînement ;
- la ratification du modèle d'embeddings au titre de D-028 : lock candidat
  depuis `c7d1510`, empreinte et licence à relire, ADR-0007 PROPOSÉ ;
- la bascule « chat rapide » face à la règle de non-interruption.
