# Retour du ML350 : séquence de reprise

- Statut : **PROPOSÉ**. Aucune étape n'a été exécutée : chacune est **à
  exécuter, non mesuré**.
- Rédaction : 2026-09-26, contre `main` à `db9414d`, serveur de calcul hors
  ligne depuis le 2026-09-14 environ. Dernier relevé en direct : 2026-09-09 ;
  dernier relevé versionné : 2026-09-10.
- Portée : ce document ordonne tous les travaux qui exigent le matériel réel,
  recensés par le tri de la phase 0 du 2026-09-26. Il ne prend aucune décision
  du propriétaire, n'autorise aucun déploiement et ne présente aucune mesure :
  il décrit, pour chaque étape, ses prérequis et la preuve qu'elle doit
  produire.

## Pourquoi cet ordre

- **Relever avant de modifier.** L'état installé ne se déduit plus de `main` :
  le correctif Qwen a été déployé par fichiers ciblés et les commits suivants
  n'ont aucun relevé de déploiement.
- **Ne rien détruire avant décision.** Une reconstruction de l'index approuvé
  efface les documents déposés et tous les embeddings ; elle vient après la
  décision sur les documents déposés et après une sauvegarde vérifiée.
- **Auditer avant de produire.** L'arène joue par défaut le benchmark scellé
  E2 ; ses paquets et incréments se comptent avant d'en créer d'autres.
- **Mesurer au repos.** Les compteurs NUMA de l'hôte sont faussés par les
  charges voisines ; ils se valident sur un hôte au repos.

## Règles communes

1. **Lecture seule d'abord.** Tant que les relevés des étapes 1 et 4 ne sont
   pas consignés, aucune écriture dans RAW ou VALIDATED, aucune promotion,
   aucune reconstruction ni suppression d'index, aucun lancement ni reprise
   d'entraînement, aucune modification d'unité ou de pare-feu. Cette fenêtre se
   définit par ces deux relevés, pas par un numéro d'étape : une étape bloquée,
   comme l'étape 7 en attente de décision, ne la prolonge pas. Dans ces
   limites, chaque étape n'effectue que les arrêts, reprises et écritures
   qu'elle nomme :
   - étape 6 : les arrêts nommés, avec l'accord du propriétaire ; à la fin de
     l'étape, les services arrêtés retrouvent, avec le même accord, l'état
     qu'ils avaient avant elle, sauf une reprise d'entraînement qui attend la
     fin de la fenêtre de lecture seule ;
   - étape 7 : seule étape autorisée à reconstruire l'index approuvé et à
     réencoder ses passages ;
   - étape 10 : seuls les runs de benchmark du protocole approuvé ;
   - étape 13 : lecture du catalogue RAW, sorties hors RAW et VALIDATED ;
   - étapes 16 et 17 : seules étapes qui modifient un déploiement, une unité
     ou un pare-feu, après leurs prérequis ;
   - toutes les autres étapes restent en lecture seule sur l'état installé et
     n'écrivent que leurs relevés et preuves, ainsi que le lock candidat de
     l'étape 3.
2. **Aucun réseau nouveau.** Aucun port ouvert, aucun appel à un fournisseur,
   aucun téléchargement. Les tests du dépôt s'exécutent sans réseau.
3. **Expurgation.** Les relevés versionnés ne contiennent ni adresse IP, ni nom
   d'hôte, ni identifiant de conteneur, ni chemin d'hôte, ni compte, ni
   secret, ni numéro de série, ni valeur matérielle exacte non autorisée par
   D-025. Ces détails restent dans l'inventaire et les journaux internes, hors
   Git. Les composants sont nommés par rôle : passerelle, arène, service de
   promotion périodique, service d'embeddings, emplacement de chat BOOTSTRAP,
   runtime CORE, agent de programmation, collecteur.
4. **Une preuve datée par étape.** Chaque étape produit une entrée datée dans
   `docs/operations/`, avec le commit du dépôt utilisé, ce qui a été mesuré et
   ce qui reste une estimation. Une étape dont un prérequis manque est
   consignée « bloquée », jamais contournée ; la séquence continue avec les
   étapes qui n'en dépendent pas.
5. **Décisions du propriétaire.** Un prérequis « décision du propriétaire »
   reste manquant tant que `docs/project/decisions.md` ne le consigne pas, ou
   que le propriétaire ne l'a pas donné explicitement pour une action
   ponctuelle. Aucun agent ne l'anticipe.

## Avant le redémarrage : question au propriétaire

Au redémarrage, les services activés peuvent reprendre d'eux-mêmes : démon de
l'arène, service périodique de promotion du corpus (toutes les deux minutes,
en root, sur des approbations JSON non signées) et, selon son état, la bascule
« chat rapide ». **Décision du propriétaire** : les laisser reprendre, ou les
garder arrêtés jusqu'à la fin des étapes 1 et 4. Proposition, **PROPOSÉ** et
non décidée : les garder arrêtés, pour que le relevé décrive l'état figé et
qu'aucun paquet ne soit produit sur la suite par défaut avant l'audit.

## Vue d'ensemble

| Étape | Objet | Dépend des étapes | Statut |
| --- | --- | --- | --- |
| 1 | Relevé de l'état installé | aucune | à exécuter, non mesuré |
| 2 | Suite de tests complète sous Linux | 1 | à exécuter, non mesuré |
| 3 | Relecture du modèle d'embeddings et lock | 1 | à exécuter, non mesuré |
| 4 | Audit des paquets et incréments dérivés de E2 | 1 | à exécuter, non mesuré |
| 5 | Comparateur NUMA sur les preuves `0.2.0` | 1 | à exécuter, non mesuré |
| 6 | Validation des compteurs NUMA | 1 | à exécuter, non mesuré |
| 7 | Réapprobation et reconstruction de l'index RAG | 1, 3 | à exécuter, non mesuré |
| 8 | Tests réseau négatifs (issue #4) | 1 | à exécuter, non mesuré |
| 9 | Inventaire interne du ML350 (issue #2) | 1 | à exécuter, non mesuré |
| 10 | Protocole NUMA étendu (G4) | 5, 6, 9 | à exécuter, non mesuré |
| 11 | Évaluation du tokenizer | 2 | à exécuter, non mesuré |
| 12 | Benchmark de recherche au volume réel | 3, 7 | à exécuter, non mesuré |
| 13 | Split par paquet et sous-échantillon du catalogue RAW | 2 | à exécuter, non mesuré |
| 14 | Évaluations de référence des moteurs | 1, 2, 4 | à exécuter, non mesuré |
| 15 | Seuils de performance, ressources et reprise | 7, 10 | à exécuter, non mesuré |
| 16 | Déploiement du collecteur durci | 8 | à exécuter, non mesuré |
| 17 | Contrôles SSRF réseau et placement en DMZ | 8 | à exécuter, non mesuré |

Les étapes 1 à 8 forment le premier jour, dans cet ordre. Les étapes 9 à 17
suivent quand leurs prérequis sont réunis. Les prérequis hors séquence,
décisions et outils à fusionner, sont détaillés dans chaque étape.

## Premier jour

### Étape 1 — Relevé de l'état installé

Statut : **à exécuter, non mesuré**.

Prérequis : aucun. La réponse du propriétaire à la question d'avant
redémarrage est consignée avec le relevé.

Actions, en lecture seule :

- pour chaque composant, noter le commit installé ou, à défaut, l'empreinte
  SHA-256 de chaque fichier déployé, comparée aux fichiers de `main` ;
- emplacement de chat BOOTSTRAP : modèle réellement servi (Qwen2.5-1.5B
  verrouillé ou un 14B), son empreinte, ses options (`--no-agent` ou
  `--jinja`), existence d'une unité absente du dépôt ;
- dans le conteneur de la passerelle : présence et version de `bwrap`, de
  `tesseract` et des outils poppler (`pdftotext`, `pdftoppm`) ; résultat de
  l'auto-test du bac à sable sous l'unité réellement installée, qui confirme ou
  infirme l'HYPOTHÈSE `PrivateDevices`/`AF_NETLINK` ;
- valeurs effectives de `SOVEREIGN_ARENA_SUITE` pour l'arène et de
  `SOVEREIGN_TOOLS_ENABLED` pour la passerelle. Une suite est rapportée au
  fichier du dépôt dont elle porte l'empreinte SHA-256, jamais par son chemin
  d'hôte ;
- nombre de paquets de l'arène par état, nombre d'incréments RAW et
  VALIDATED, approbations en attente dans les dépôts d'approbation ;
- état de la bascule « chat rapide » : CORE-30M suspendu ou non ;
- intégrité du checkpoint final CORE-30M : SHA-256 relu sur le stockage de
  calcul et sur la copie durable, comparé à l'empreinte consignée lors de
  l'archivage.

Preuve attendue :

- une entrée datée de relevé de déploiement dans `docs/operations/`, limitée
  aux commits, empreintes, versions, booléens et comptes ;
- dans `docs/project/current-capabilities.md`, la date de dernière
  vérification en direct mise à jour, et chaque ligne « code seul » ou
  « observation de commit » passée à « relevé » avec son entrée datée, ou
  marquée « non déployé ». Cette révision précède l'étape 7, pour qu'une seule
  réapprobation du manifeste RAG couvre le texte relevé.

### Étape 2 — Suite de tests complète sous Linux

Statut : **à exécuter, non mesuré**.

Prérequis :

- étape 1, pour connaître le commit installé ;
- correctif de la connexion SQLite non fermée de `tests/test_arena.py`
  fusionné sur `main`. Sans lui, un échec connu de `test_train_core_mini`
  apparaît sous Linux.

Actions : dans un invité Linux du nœud de calcul, sans réseau, depuis une
extraction propre du commit visé, exécuter
`python3 -B -m unittest discover -s tests -q`. Noter la version de Python et
la présence de `bwrap`, de NumPy et du bundle PyTorch hors ligne.

Preuve attendue : un résumé daté (nombre de tests, échecs, erreurs, sauts et
leur cause) qui remplace les comptes tirés des messages de commit et les
exécutions Windows non représentatives. Aucun fichier ne subsiste hors des
dossiers temporaires.

### Étape 3 — Relecture du modèle d'embeddings et lock

Statut : **à exécuter, non mesuré**.

Prérequis :

- étape 1, qui établit si le service d'embeddings est installé ;
- ADR-0007 au statut PROPOSÉ et lock candidat
  `configs/runtime/qwen3-embedding-0.6b-q8_0.lock.candidate.json` avec son
  test, fusionnés sur `main` (absents au 2026-09-26).

Actions : relire la taille et le SHA-256 du GGUF en RAW et dans le runtime,
la révision amont et le texte de licence ; vérifier que le service n'écoute
qu'en boucle locale et démarre avec `--offline` ; exécuter un test négatif de
sortie réseau depuis son invité ; reporter les valeurs relues dans le lock.

Preuve attendue : empreinte identique entre RAW et runtime, licence relue,
test d'absence de sortie consigné, lock complété. Le reçu de promotion n'est
produit qu'après une **décision du propriétaire** qui ratifie ce modèle au
titre de D-028 ; sans elle, le lock reste candidat.

### Étape 4 — Audit des paquets et incréments dérivés de E2

Statut : **à exécuter, non mesuré**.

Prérequis :

- étape 1, pour la suite effective et les comptes ;
- vérificateur statique `tools/check_evaluation_contamination.py` fusionné sur
  `main` (absent au 2026-09-26) ;
- arène à l'arrêt, ou copie de sa base ouverte en lecture seule.

Actions, en lecture seule :

- repérer les paquets et solutions dont `task_id` correspond à
  `^python-\d\d-` (identifiants E2) et tout incrément construit à partir
  d'eux ;
- exécuter `tools/build_increments_for_approved_packets.py --dry-run` et
  `tools/recheck_packet_health.py` sans `--apply` ;
- passer le vérificateur de contamination sur les incréments RAW et
  VALIDATED, y compris pour les 14 noms de fonction communs à E2 et à
  `configs/arena/practice-suite.v1.json`.

Preuve attendue : un compte sans contenu, identifiants et empreintes
seulement, des paquets et incréments concernés, versé au dossier de la
**décision du propriétaire** sur la remédiation de E2. Aucune suppression,
rétrogradation ni exclusion n'est faite à cette étape.

### Étape 5 — Comparateur NUMA sur les preuves `0.2.0`

Statut : **à exécuter, non mesuré**.

Prérequis :

- fusionnés sur `main` : durcissement de
  `tools/compare_core_mini_numa_evidence.py` (refus d'un engagement de
  placement partagé, de moins de trois répétitions, d'octets non canoniques),
  contrat de sortie v2, vérificateur de distinction des placements ;
- preuves et contrats privés disponibles hors Git.

Actions : relancer le comparateur durci sur les deux paires consignées, celle
du 2026-09-06 et celle du 2026-09-07 à la révision `6cebad1`, soit quatre
preuves `0.2.0` ; lancer le vérificateur de distinction avec les contrats
privés et leurs sels.

Preuve attendue : pour chaque paire, une sortie descriptive (issue de
séparation, ratios) ou un refus documenté avec sa raison, et un reçu de
distinction qui ne contient que les deux engagements et des booléens. Les
artefacts privés restent hors Git. Aucun placement n'est désigné et G4 reste
ouvert.

### Étape 6 — Validation des compteurs NUMA

Statut : **à exécuter, non mesuré**.

Prérequis :

- étape 1, pour l'état de la bascule « chat rapide » ;
- sections de métriques système du protocole G4, au statut PROVISOIRE,
  fusionnées dans `docs/model/core-mini-numa-protocol.md` ;
- hôte au repos : CORE-30M, agent de programmation, moteur de chat et arène
  arrêtés, avec l'**accord du propriétaire** pour ces arrêts.

Actions : dans l'invité CORE non privilégié, sur un processus synthétique,
vérifier la lisibilité et la plausibilité de `getrusage` (`ru_maxrss`, temps
CPU), des compteurs d'E/S par processus et de `numa_maps` réduit à un ratio
local/distant ; noter quels compteurs de procfs sont globaux à l'hôte
(`vmstat`, `numastat`) et donc pollués par les charges voisines ; établir si
une source de température est visible depuis l'invité.

Preuve attendue : un tableau par compteur (lisible ou non, par processus ou
global, plausible ou non), sans identifiant ni nombre de nœuds, conformément
à D-025. Aucun seuil n'est fixé.

### Étape 7 — Réapprobation et reconstruction de l'index RAG

Statut : **à exécuter, non mesuré**.

Prérequis :

- **décision du propriétaire** sur les documents déposés : niveau de
  confiance distinct, extracteurs isolés, approbation avant indexation, ou
  abandon assumé. Sans elle, l'étape reste bloquée : la reconstruction
  effacerait les documents déposés ;
- révision de `docs/project/current-capabilities.md` fusionnée et complétée
  par l'étape 1 ;
- **réapprobation par le propriétaire** de la nouvelle empreinte du manifeste
  `project-internal-v1` ;
- étape 3, avant tout réencodage ;
- sauvegarde vérifiée de la base de connaissances actuelle.

Actions :

1. sauvegarder la base actuelle avec `tools/backup_knowledge_index.py` et
   vérifier l'artefact ;
2. passerelle arrêtée, reconstruire avec
   `tools/build_project_knowledge_index.py build` et l'empreinte approuvée ;
3. conserver ou réintégrer les documents déposés selon la décision ;
4. réencoder avec `tools/reembed_validated_chunks.py` ;
5. restaurer la sauvegarde dans un fichier de contrôle et comparer les
   empreintes.

Preuve attendue : empreinte de manifeste de l'index en service égale à
l'empreinte approuvée ; le chat cite le texte révisé des capacités ;
documents déposés conservés ou écartés sciemment, et consignés ;
aller-retour de sauvegarde et restauration vérifié ; nombre de passages avec
et sans vecteur.

### Étape 8 — Tests réseau négatifs (issue #4)

Statut : **à exécuter, non mesuré**.

Prérequis :

- 8a : étape 1. Cette partie peut suivre immédiatement le relevé ; il est
  proposé (**PROPOSÉ**) de l'exécuter avant de rouvrir le relais HTTPS ou le
  collecteur ;
- 8b : schéma et validateur de la matrice des flux fusionnés sur `main`
  (absents au 2026-09-26), puis matrice réelle expurgée **approuvée par le
  propriétaire**.

Actions :

- 8a : rejouer après redémarrage les contrôles négatifs déjà consignés avant
  l'arrêt du serveur : depuis IA-CORE, absence de route par défaut, résolution
  DNS externe refusée, connexion TCP directe vers Internet refusée (consignés
  le 2026-09-06, `5ba5427`, section « Vérifications confirmées » de
  `docs/project/current-capabilities.md`) ; pour l'agent de programmation,
  seule entrée admise depuis la passerelle vers le port du moteur, sortie
  refusée (relevé de promotion du 2026-09-10, `e09c521`). Y ajouter un
  contrôle jamais consigné : service d'embeddings en boucle locale seulement,
  si l'étape 1 l'a trouvé installé ;
- 8b : pour chaque flux de la matrice approuvée, tests négatifs DNS, HTTP,
  HTTPS, proxy et NAT, après démarrage, après restauration et après
  changement.

Preuve attendue : pour chaque contrôle, résultat attendu et résultat observé,
datés et expurgés ; la partie 8b constitue la preuve du gate A1.

## Étapes suivantes

### Étape 9 — Inventaire interne du ML350 (issue #2)

Statut : **à exécuter, non mesuré**.

Prérequis : étape 1 ; **décision du propriétaire** sur le critère
d'acceptation de l'issue #2 : inventaire interne hors Git et résumé public
expurgé, conformément à D-025.

Actions : relever la disposition NUMA et DIMM et la RAM visible par nœud dans
l'inventaire interne.

Preuve attendue : inventaire interne validé par un schéma ; résumé public
limité au caractère CPU-only, bi-socket et NUMA, et aux seuls faits
explicitement autorisés.

### Étape 10 — Protocole NUMA étendu (G4)

Statut : **à exécuter, non mesuré**.

Prérequis :

- étapes 5, 6 et 9 ;
- **décision du propriétaire** sur le périmètre de G4 après D-034 : cible de
  l'extrapolation, seconde échelle, charge synthétique ou pilote-v3 ;
- protocole approuvé par le propriétaire, avec ses seuils d'arrêt ;
- runner à métriques système (évidence `0.3.0`) fusionné sur `main`.

Actions : deux placements, au moins trois répétitions, deux échelles, plus un
balayage de threads ; contrats privés distincts, reçus de distinction et
comparaisons v2.

Preuve attendue : preuves conformes pour chaque placement et chaque échelle,
métriques système présentes et plausibles. Aucune durée n'est publiée sans
approbation de l'extrapolation ; G4 n'est fermé que par une décision du
propriétaire.

### Étape 11 — Évaluation du tokenizer

Statut : **à exécuter, non mesuré**.

Prérequis : étape 2 ; `tools/evaluate_tokenizer.py` et
`docs/model/tokenizer-experiments-protocol.md` fusionnés sur `main`.

Actions : en lecture seule, sur les splits validation et test de pilote-v3,
évaluer les artefacts candidats et leurs variantes de vocabulaire, en deux
exécutions.

Preuve attendue : rapport haché, identique sur les deux exécutions ; seules
les métriques et les empreintes sont publiées, sans contenu de corpus ; aucun
seuil n'est décidé, ce choix relevant du gate G3.

### Étape 12 — Benchmark de recherche au volume réel

Statut : **à exécuter, non mesuré**.

Prérequis : étapes 3 et 7 ; `tools/evaluate_retrieval.py` fusionné sur
`main` ; jeu d'or privé hors Git.

Actions : latence p50 et p95, mémoire et rappel pour l'index SQLite
exhaustif et ses alternatives, avec et sans reranker ; balayage de la
pondération 0,45/0,55 ; état du réencodage.

Preuve attendue : médiane, dispersion et période de chauffe, matériel et
versions consignés selon `AGENTS.md`, reportés dans l'ADR-0007 ; aucune
extrapolation présentée comme mesure.

### Étape 13 — Split par paquet et sous-échantillon du catalogue RAW

Statut : **à exécuter, non mesuré**.

Prérequis : étape 2 ; `tools/build_package_level_splits.py` et
`tools/plan_corpus_subsample.py` fusionnés sur `main` ; **décisions du
propriétaire** du gate G3 sur les proportions du corpus et la politique de
traitement.

Actions : appliquer le split et le plan au catalogue RAW, du stockage durable
vers le nœud de calcul, sans écriture dans RAW ni VALIDATED.

Preuve attendue : manifeste candidat `pending_owner_approval` avec empreintes
par split et fuite de holdout nulle. Aucun entraînement n'est lancé.

### Étape 14 — Évaluations de référence des moteurs

Statut : **à exécuter, non mesuré**.

Prérequis :

- étape 1, qui identifie le modèle réellement servi par l'emplacement
  BOOTSTRAP ;
- étape 2 et bac à sable `bwrap` opérationnel ;
- étape 4 et **décision du propriétaire** sur la remédiation de E2 ;
- suites candidates `configs/evaluation/v1-use-cases.candidate.json` et
  `configs/evaluation/v1-safety.candidate.json` fusionnées sur `main`.

Actions : E0, E1, E2, cas d'usage et sûreté sur l'emplacement BOOTSTRAP,
Qwen-Coder et le dernier checkpoint CORE-30M, dans `bwrap`.

Preuve attendue : rapports sans contenu liés à leurs SHA-256, médianes et
protocole consignés, liés depuis la grille d'évaluation V1. Aucun seuil n'est
tiré d'une seule exécution.

### Étape 15 — Seuils de performance, ressources et reprise

Statut : **à exécuter, non mesuré**.

Prérequis : étapes 7 et 10 ; preuves des gates A6 (restauration avec RPO et
RTO réels) et A7 (capacité) de `docs/architecture/overview.md`.

Actions : mesurer tokens/s, latence, RAM, CPU, disque, restauration (RPO et
RTO), fonctionnement hors ligne et confinement des erreurs.

Preuve attendue : chaque ligne de performance et de reprise de la grille
d'évaluation cite une mesure reproductible sur le ML350, jamais une
estimation.

### Étape 16 — Déploiement du collecteur durci

Statut : **à exécuter, non mesuré**.

Prérequis :

- étape 8 ;
- PR #17 fusionnée ;
- **décision du propriétaire** sur la politique d'ingress : rejet ou
  signalement par catégorie de secret, et contrat des conversations ;
- scanner de secrets fusionné, puis raccordé après cette décision en
  coordination avec Codex.

Actions : déployer par archive versionnée, puis vérifier de bout en bout avec
des entrées synthétiques.

Preuve attendue : réponse 422 pour chaque classe de secret synthétique, aucun
fichier RAW pour un corps rejeté, `already_imported` au renvoi, révision
conservée ; statut public mis à jour sans détail interne.

### Étape 17 — Contrôles SSRF réseau et placement en DMZ

Statut : **à exécuter, non mesuré**.

Prérequis : étape 8b, avec les flux F0 et F1 dans la matrice approuvée ;
ADR-0006 accepté par le propriétaire ; politique d'URL statique fusionnée sur
`main`.

Actions : pour le composant qui déréférence les URL, épinglage du résolveur,
défense contre le rebinding DNS, politique de redirection, proxy de sortie et
allowlist ; tests négatifs sur le réseau réel.

Preuve attendue : redirections vers des adresses privées ou de métadonnées
bloquées, réponses DNS qui basculent vers une adresse privée bloquées, aucune
route de la Gateway ou du collecteur vers IA-CORE, perte de la Gateway sans
ouverture d'Internet pour IA-CORE ; résultats consignés contre le cas d'abus
T09 du modèle de menace.

## Correspondance avec le tri de la phase 0

Chaque travail matériel du tri figure une seule fois :

| Travail matériel du tri | Étape |
| --- | --- |
| Relevé de déploiement : commit par composant, `bwrap`/`tesseract`/poppler, `SOVEREIGN_ARENA_SUITE`, paquets et incréments, bascule, checkpoint CORE-30M | 1 |
| Suite de tests Linux sur le matériel réel | 2 |
| Relecture du GGUF d'embeddings, lock et reçu de promotion | 3 |
| Audit en lecture seule des paquets et incréments dérivés de E2 | 4 |
| Comparateur durci et vérificateur de distinction sur les preuves `0.2.0` existantes | 5 |
| Validation des compteurs NUMA dans l'invité, hôte au repos | 6 |
| Réapprobation du manifeste `project-internal-v1`, reconstruction, réencodage, sauvegarde et restauration | 7 |
| Issue #4 : matrice des flux réelle, tests négatifs après démarrage, restauration et changement | 8 |
| Issue #2 : inventaire ML350, NUMA/DIMM et RAM visible par nœud | 9 |
| Protocole NUMA étendu et clôture de G4 | 10 |
| Évaluation du tokenizer sur pilote-v3 | 11 |
| Benchmark de recherche au volume réel et état du réencodage | 12 |
| Split par paquet et sous-échantillon appliqués au catalogue RAW | 13 |
| Évaluations de référence E0/E1/E2, cas d'usage et sûreté | 14 |
| Seuils de performance, ressources et reprise | 15 |
| Déploiement du collecteur durci et vérification de bout en bout | 16 |
| Contrôles SSRF réseau et placement Gateway/collecteur en DMZ | 17 |
