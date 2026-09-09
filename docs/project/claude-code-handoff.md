# Reprise Claude Code

Dernière mise à jour : 2026-09-09.

Ce document est le point de reprise public et expurgé. Il ne contient ni
adresse privée, compte, secret, chemin d'administration ou inventaire détaillé.
Lire d'abord `AGENTS.md`, `docs/project/decisions.md`,
`docs/project/current-capabilities.md`, `docs/architecture/overview.md` et
`docs/security/threat-model.md`.

## Mise à jour vérifiée — 2026-09-09

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
- le runner E2 contient dix tâches Python et retient uniquement des verdicts
  produits par leurs tests dans un bac à sable offline. Il est prêt à être
  exécuté lorsqu'un environnement Linux avec Bubblewrap est disponible ; il ne
  remplace pas E1 et ne transforme aucune réponse en donnée d'entraînement ;
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

## Mise à jour consolidée — 2026-09-08

Cette section **remplace les instantanés historiques plus bas dans ce fichier**.
Ils sont conservés uniquement pour la traçabilité de la tranche du 7 septembre.

### Point de départ

- dépôt : `PolishMen25/sovereign-local-ai` ; branche de travail :
  `codex/cpu-offline-harness` ;
- actualiser le HEAD distant et vérifier le diff avant toute modification ;
- les déploiements sont des archives versionnées : préparer, tester, committer
  puis déployer une archive vérifiée ; ne jamais modifier directement une
  release installée ;
- aucun secret, artefact réel, checkpoint, corpus, identifiant ou détail
  d'exploitation privé ne doit rejoindre Git.

### État vérifié et limites

- l'interface privée, l'authentification et BOOTSTRAP fonctionnent ; BOOTSTRAP
  reste le moteur par défaut et le seul chat présenté comme exploitable ;
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
  ne sont pas terminés ;
- l'interface expose un état RAG sans contenu : au relevé, l'index lexical
  contenait quatre documents VALIDATED. Cet état ne rend ni RAW ni les
  conversations consultables par le RAG ;
- sur cette lignée, la suite complète compte 254 tests verts et un ignoré.
  Après l'ajout de l'export conversationnel et de sa reprise contrôlée, la
  suite compte 271 tests verts et un ignoré.

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
  tests externes sans auto-évaluation du modèle.

## Branche de travail

- dépôt : `PolishMen25/sovereign-local-ai` ;
- branche d'intégration : `codex/cpu-offline-harness` ;
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
  que leurs gates ne sont pas franchis ;
- aucun secret, poids, checkpoint, corpus réel ou détail interne dans Git.

## Ce qui fonctionne réellement

- chat BOOTSTRAP Qwen2.5-1.5B-Instruct en CLI locale CPU ; la passerelle Web du
  projet l'appelle sur la boucle locale et est exposée en HTTPS privé dans le
  tailnet, sans outil, agent ou proxy MCP ;
- instanciation CPU historique et comptage exact de CORE-80M, conservé comme
  référence sans poids ;
- entraînement synthétique strict de CORE-MINI sur 20 étapes, checkpoint
  atomique puis reprise de 5 étapes jusqu'à l'étape 25 ; la compatibilité d'un
  ancien checkpoint historique reste à confirmer séparément sur Linux ;
- runner de preuve CORE-MINI NUMA implémenté avec contrat de placement externe,
  archive source et runtime offline vérifiés, contrôle INET flux/datagrammes
  fail-closed et répétitions bornées ; le doublon d'option a été corrigé,
  déployé et testé. Les preuves A/B ont produit trois répétitions chacune sur
  le même commit et workload ; un comparateur strict les a vérifiées. A est
  3,8 % au-dessus de B en médiane, sans décision de placement ;
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
  fail-closed seulement.

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
  conversation ne rejoint cet index ;
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
  profils du registre sont toujours `draft` ;
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
état est informatif et peut devenir obsolète.

## Refus attendus

Un changement doit être refusé s'il introduit un téléchargement depuis CORE,
un build GPU, un tokenizer auto-approuvé, un corpus autre que `train`, une
promotion RAW automatique, un endpoint MCP générique, un secret dans Git ou une
revendication de capacité non mesurée.
