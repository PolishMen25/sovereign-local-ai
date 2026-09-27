# Capacités réellement disponibles

Dernière vérification en direct : 2026-09-09. Dernier relevé versionné :
2026-09-10. Mise à jour documentaire : 2026-09-26, contre `main` à `db9414d`.

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
propriétaire absent de `docs/project/decisions.md`. Ce document décrit l'état
du code et des relevés ; il ne tranche aucun de ces choix.

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
déploiement et plusieurs sont sans décision au registre.

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
| Emplacement de chat `BOOTSTRAP` | Qwen2.5-1.5B vérifié au relevé ; libellé « CHAT-14B » dans l'interface, sans décision au registre | Vérifié en direct pour le 1.5B ; code seul pour le libellé 14B (`9b31b41` pour l'interface, `017e79f` pour `/sante`) | Qwen2.5-1.5B-Instruct Q4_K_M générait réellement sur CPU avec llama.cpp en boucle locale ; la passerelle authentifiée nomme le moteur, conserve localement les échanges masqués et peut joindre des références avec provenance | Modèle tiers temporaire, pas CORE. L'interface et `/sante` présentent cet emplacement comme Qwen2.5-14B, alors que le dépôt ne verrouille que le 1.5B (lock et unité avec `--no-agent`) : aucun lock, licence, unité ni entrée du registre pour un 14B. D-024 exclut outil, agent et RAG pour BOOTSTRAP ; voir les outils de chat plus bas |
| Agent Qwen2.5-Coder-7B (`QWEN-CODER`) | Promu par le propriétaire le 2026-09-10 et déployé sur un nœud physique séparé selon le relevé | Relevés : `configs/runtime/qwen2.5-coder-7b-q4km.promotion.json` (`bf13670`, `e09c521`) et `docs/operations/qwen-conversation-fix.md` (`ac05afc`, `7b2111b`, `a2e40ea`, `1ba28b6`) | Empreintes SHA-256 relues en RAW, en VALIDATED et sur le nœud d'exécution ; E2 : 38/50 en un essai et 45/50 avec une passe de réparation, contre 23/50 pour Qwen2.5-1.5B ; la passerelle transmet les 20 derniers messages et les références lexicales ; une seule entrée réseau admise depuis la passerelle, sortie refusée ; réponse 503 quand le moteur n'est pas configuré (`ec56b30`, code seul) | État présent non revérifié. Le correctif de la passerelle a été déployé par fichiers ciblés, hors archive versionnée. La passe de réparation montre l'assertion échouée : elle mesure un agent qui lit ses erreurs. `AGENTS.md` exclut encore tout service V1 du DL380p Gen8, en conflit avec D-034 ; arbitrage du propriétaire |
| Évaluation de code et réparation | Outils hors ligne versionnés | Code seul : `e09c521`, `e292451`, `58c26c9` ; observation de commit : `0a1c2ee`, `58c26c9` | Générateur de candidats sans nouvel essai ; boucle écrire, tester, corriger avec `first_pass` et `final_pass` ; réparation de projet sur copie, fichiers de test jamais modifiés, diff remis à un humain ; budget de tâches et auto-test du bac à sable | Aucune exécution postérieure au 2026-09-10 consignée. `0a1c2ee` rapporte un bac à sable qui rejetait chaque tâche avant correction |
| CORE-MINI-1M | Entraînement `authorized-text` borné et reprise vérifiés | Vérifié en direct | Modèle de 1 328 256 paramètres ; 50 étapes sur le corpus approuvé, checkpoint durable, puis reprise contrôlée de 10 étapes jusqu'à 60 avec journal continu et empreintes ; modes explicitement séparés | 60 étapes ne produisent pas un assistant : aucune évaluation linguistique ni question CORE possible |
| CORE-30M | Pilote de pipeline, palier final de 19 532 étapes atteint | Relevé : section du 2026-09-09 de `docs/project/claude-code-handoff.md` | Checkpoint final avec copie durable relue et empreinte identique ; lecture pré-tokenisée liée par empreintes au manifeste, au split et au tokenizer | Pas un chat ni un assistant de code (D-034) : la tentative E1 du 2026-09-09 sur le checkpoint final a été refusée par le garde E0 sur une sortie répétitive (`ff16ad9`) ; aucun paquet E1 n'a été créé. Aucun entraînement postérieur au 2026-09-09 n'est consigné |
| Runner CORE-MINI NUMA | Deux paires A/B répétées, résultat non concluant | Vérifié en direct ; détail dans `docs/model/core-mini-numa-protocol.md` | Contrats privés hors Git, archive source et runtimes offline vérifiés, placement externe, sockets INET refusées, trois répétitions fraîches par placement et comparaison fermée | Paire du 2026-09-06 : A 3,8 % au-dessus de B. Paire du 2026-09-07, révision `6cebad1` : ratio A/B 0,9497, soit B environ 5,3 % au-dessus, plages observées qui se recouvrent. Non concluant, aucun placement désigné. Le comparateur ne vérifie pas que les deux contrats de placement sont distincts. Mesures mémoire/NUMA élargies et décision G4 absentes |
| Zone de calcul CORE | Invité non privilégié au relevé | Vérifié en direct | Runtime CPU hors ligne isolé, stockage de travail local et accès borné au stockage durable ; aucun téléchargement à l'exécution ; deux paliers CORE-700M exécutés | Aucun poids CORE utile ; preuve d'isolation après redémarrage reste à compléter |
| CORE-700M | Preuves mécaniques archivées | Vérifié en direct | Configuration, tokenizer et checkpoints techniques sont conservés pour traçabilité | Aucun entraînement long ni objectif de chat ou code ; cette voie est remplacée par D-034 |
| Corpus / tokenizer | Candidat 32k traçable | Vérifié en direct ; changement de gate `6d959d7` | Manifeste `0.2.0`, split `train` lié par taille/compte/SHA, Byte-BPE ordonné, NFC partagé, encode/decode et promotion `experimental` → `candidate_core` avec reçu | Qualité, couverture française et passage à l'échelle restent à traiter. Depuis `6d959d7`, un manifeste validé suffit au préflight et `approved.json` n'est plus bloquant : ratification par le propriétaire en attente |
| Moteur d'inférence CORE | Runtime expérimental CPU au relevé | Vérifié en direct | Checkpoint d'inférence compact validé, contrat configuration/tokenizer/manifeste/préflight vérifié, API privée authentifiée sur une adresse privée configurée hors Git (D-036), génération gloutonne bornée et déterministe | Vingt étapes ne constituent pas une qualité linguistique ; aucune promesse d'assistant général. Le runtime ne reçoit ni Internet ni outil arbitraire |
| MCP Knowledge | Prototype `stdio` fonctionnel | Vérifié en direct | Handshake MCP, état, recherche lexicale et récupération bornée d'une provenance exacte | Trois notices synthétiques ; non raccordé au chat |
| RAG | Index lexical approuvé vérifié au relevé ; recherche hybride et documents partagés dans le code | Vérifié en direct pour l'index lexical ; code seul : `d7cc78c`, `010706c`, `5c917de` | L'index SQLite/FTS5 fournit des extraits bornés et des citations depuis quatre documents internes approuvés ; toute reconstruction exige un manifeste exact, son empreinte et une référence d'audit ; le rappel passe de 2 à 6 extraits (`5c917de`) | Conversations et RAW restent hors index. Les documents partagés y entrent sans approbation (voir plus bas). Ce fichier appartient au manifeste `project-internal-v1`, à réapprouver puis reconstruire |
| Moteur d'embeddings RAG | Code présent (`d7cc78c`), déploiement non vérifié | Code seul : `d7cc78c` | Client en boucle locale pour Qwen3-Embedding-0.6B servi par llama.cpp, recherche hybride avec repli lexical, `tools/reembed_validated_chunks.py` | D-028 autorise un petit moteur d'embeddings, mais aucun lock, licence ni empreinte de ce modèle n'est versionné dans `configs/runtime/` |
| Documents partagés et analyse | Code sur `main`, sans décision au registre | Code seul : `010706c`, `5c917de`, `a8151e7` | Dépôt jusqu'à 25 Mo, extraction hors ligne (texte, docx, PDF via poppler, OCR Tesseract), analyse map-reduce bornée à 30 passages, rendu Markdown des réponses | Les passages rejoignent la table de l'index approuvé sans approbation, par `upsert_validated` ; extracteurs sans bac à sable ; présence de poppler et Tesseract non consignée ; une reconstruction de l'index approuvé les effacerait avec les embeddings |
| Outils de chat en lecture seule | Code sur `main`, sans décision au registre | Code seul : `a133659` | `search_knowledge`, `list_documents`, `read_document` et `current_time`, sans système de fichiers, shell ni réseau ; enclenchés par défaut dans le code via `SOVEREIGN_TOOLS_ENABLED` | Contredit D-024 pour BOOTSTRAP. Exige un serveur 14B lancé avec `--jinja`, dont l'unité n'est pas versionnée |
| Outils d'action | Code sur `main`, sans décision au registre | Code seul : `04473fe`, `3410b36` | `run_python` dans le bac à sable bwrap et `write_file` dans un espace de travail, chacun après une confirmation humaine à usage unique ; fichiers produits listés par `GET /v1/workspace` | `SOVEREIGN_ACTIONS_ENABLED` n'existe pas dans le code. L'unité versionnée de la passerelle garde `PrivateDevices=yes` sans `AF_NETLINK`. **HYPOTHÈSE** : sous cette unité, l'auto-test du bac à sable échoue et `run_python` n'est pas proposé |
| Collector de conversations | Ingress write-only fonctionnel | Vérifié en direct | Endpoint HTTPS de santé et dépôt authentifié vers RAW | Aucune lecture interne ni promotion automatique vers `VALIDATED` |
| Synology | Stockage durable monté et persistant sur l'hôte de calcul | Vérifié en direct | SMB 3.1.1 chiffré, compte de service limité, montage activé au démarrage, lecture/écriture CORE et aller-retour synthétique vérifiés via un point de montage contrôlé ; mémoire, index lexical et checkpoint CORE-MINI sont sauvegardés et restaurés avec empreintes vérifiées | Le remplacement d'une base utilisée, la restauration d'un checkpoint CORE-700M et le test de droits négatifs restent à faire |
| Arène d'agents | Code sur `main` ; exécutions rapportées seulement par des commits ; activation sans décision au registre | Code seul : `0dcbe8c`, `b5f0227`, `015b815`, `9b31b41`, `cd68960`, `d9c0e42`, `b486851` ; observations de commit : `8ef2f8a`, `dbca0c6`, `b486851` | Auteurs arbitrés par le bac à sable hors ligne, relecteur, Elo, paquets de 50 solutions avec manifeste et SHA-256 en attente d'approbation ; page `/arena` et approbations par fichier ; résumé en terminal ; santé mesurée sur l'ensemble retenu avec `max_task_share` borné à 0,25 | `docs/model/self-training-loop-spec.md` reste `INACTIVE`. Les commits rapportent 41 puis 28 paquets. La suite par défaut de `services/arena/runner.py` est le benchmark E2 scellé ; la suite réellement utilisée n'est pas consignée |
| Suite d'entraînement de l'arène | 182 tâches versionnées | Code seul : `1857089`, `0655d42`, `db9414d` | `configs/arena/practice-suite.v1.json`, auto-validée par des solutions de référence, identifiants disjoints de E2 | Aucun relevé de chargement. 14 noms de fonction sont communs avec E2. Ni l'arène (`services/arena/runner.py`) ni `tools/build_core_increment_from_arena.py` ne la chargent par défaut ; seul `tools/build_increments_for_approved_packets.py` pointe par défaut vers une copie de cette suite hors dépôt, dont la présence n'est pas consignée |
| Incréments de corpus issus de l'arène | Code sur `main` ; usage rapporté par des commits ; sans décision au registre | Code seul : `229ffe0`, `689fa70`, `75d234a`, `0655d42` ; observations de commit : `5f59591`, `dbca0c6` | Paquet approuvé converti en incrément RAW synthétique déterministe ; promotion RAW → VALIDATED demandée depuis `/corpus` et appliquée par un service périodique qui vérifie l'empreinte ; aucun entraînement déclenché | L'approbation est un JSON sans signature ni HMAC, malgré le terme « signée » du code ; l'applicateur s'exécute en root. `dbca0c6` rapporte 2 incréments pour 41 paquets |
| Orchestrateur | Préparation fail-closed | Vérifié en direct | Chargement du registre et validation partielle d'enveloppes/permissions | Aucun appel de modèle, d'outil ou de file d'exécution ; les outils du chat passent par la passerelle, pas par l'orchestrateur |
| Profils d'agents | Registre de 60 profils `draft` ; profils sélectionnables dans le chat par le code, sans décision au registre | Code seul : `5891fff`, `91ff285`, `9ac11cd` | Selon `91ff285`, 59 profils du catalogue deviennent sélectionnables (49 sur le moteur 14B avec outils, 10 de la famille `development` sur Qwen-Coder), avec `coordination` et les agents d'arène approuvés, groupés par famille | Les gates d'évaluation par profil ne sont pas appliqués ; seul un commentaire de `services/web/catalog_profiles.py` l'attribue à un choix du propriétaire. `configs/agents/registry.json` garde les 60 profils en `draft` |
| Mémoire conversationnelle | SQLite local avec sauvegarde durable vérifiée | Vérifié en direct | Masquage de secrets, empreintes, historique, export, suppression avec reçu sans contenu et sauvegarde SQLite vérifiée vers le NAS | Pas raccordée au RAG ; restauration applicative de remplacement reste manuelle |
| Interface Web du projet | Passerelle installée derrière le HTTPS privé au relevé du 2026-09-09 | Vérifié en direct ; relevé `docs/operations/qwen-conversation-fix.md` pour le moteur Qwen ; code seul pour les pages ajoutées ensuite | Première configuration, login, CSRF, historique réouvrable, export, suppression et `/v1/chat` vers llama.cpp, CORE ou Qwen-Coder ; le sélecteur marque CORE-700M comme expérimental ; pages `/arena`, `/corpus` et `/sante` dans le code | Depuis le correctif ciblé, aucune archive versionnée ne correspond au HEAD de `main` : l'état installé est inconnu |
| Page `/sante` | Code sur `main` | Code seul : `017e79f` | `GET /v1/health` et page authentifiée : joignabilité des moteurs, index, arène, incréments, espace de travail et ressources du conteneur de la passerelle | Décrit le conteneur de la passerelle, pas l'hôte ; libelle l'emplacement BOOTSTRAP comme Qwen2.5-14B |
| Bascule « chat rapide » | Script hôte versionné, sans décision au registre | Code seul : `aec81e3` ; observation de commit pour les débits rapportés | Suspend l'entraînement CORE-30M par `SIGSTOP` et donne les deux sockets au moteur 14B, puis reprend par `SIGCONT` | Contraire à la règle de ne jamais interrompre un entraînement pour une opération de confort ; vise une unité 14B absente du dépôt ; usage et état non consignés |
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
  l'environnement Windows et à une connexion SQLite non fermée dans un test.
  Elle n'est pas une référence.
- Aucune CI n'est versionnée et aucune exécution Linux n'est consignée pour
  `db9414d`.

Le relais HTTPS et le coffre restent des preuves opérationnelles réversibles de
phase 0. Ils ne valident ni l'orientation P-002, ni la topologie cible, ni un
gate de mise en production.

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

Le runner NUMA est lui aussi un outil de preuve de phase 0, pas une commande
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
3. approuver corpus, tokenizer et grille d'évaluation avant tout nouveau palier
   d'entraînement ;
4. fermer le gate G4 par un benchmark reproductible accepté par le
   propriétaire ;
5. valider l'isolation réseau, les droits, l'audit, les sauvegardes et la
   restauration avant tout service persistant.

BOOTSTRAP fournit le chat immédiat, mais ne franchit aucune de ces étapes et ne
doit jamais être présenté comme CORE. Aucune inférence distante n'est utilisée.

## Décisions du propriétaire en attente

Ce document ne tranche aucun de ces points :

- l'emplacement BOOTSTRAP libellé CHAT-14B face à D-024 ;
- les profils sélectionnables sans gates d'évaluation ;
- les outils d'action : interrupteur réel, unité de la passerelle et bwrap ;
- les documents partagés : niveau de confiance, isolation des extracteurs et
  effet d'une reconstruction de l'index ;
- l'activation de l'arène, la suite utilisée, la contamination éventuelle de
  E2 et la promotion d'incréments en root sur une approbation non signée ;
- le lock, la licence et l'empreinte du modèle d'embeddings ;
- la ratification du changement de gate `6d959d7` ;
- la ligne d'`AGENTS.md` sur le DL380p Gen8 face à D-034 ;
- la bascule « chat rapide » face à la règle de non-interruption.
