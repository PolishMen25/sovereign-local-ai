# État public du déploiement

Dernière vérification en direct : 2026-09-09. Dernier relevé versionné :
2026-09-10. Mise à jour documentaire : 2026-09-27, contre `main` à `eea75b5` :
registre jusqu'à D-045, phase 1 (D-038) ; depuis `db9414d`, le code a reçu
l'interrupteur D-035, le contrôleur de disponibilité du NAS, les points
d'accès privés hors Git (D-036), la CI (D-037), le comparateur NUMA durci, des
contrats et outils candidats hors ligne et la séparation par défaut entre E2
et l'arène, sans relevé de déploiement.

La source de vérité détaillée est la page
[Capacités réellement disponibles](current-capabilities.md), qui donne pour
chaque composant ses commits et son niveau de preuve. Ce résumé reste
volontairement au niveau des composants et n'expose ni adresse privée, ni
compte, ni secret, ni chemin d'administration.

## Vérification

Le serveur de calcul ML350 est hors ligne depuis le 2026-09-14 environ. Rien
n'a été revérifié en direct après le 2026-09-09, hormis les relevés versionnés
cités. Ce résumé décrit les derniers relevés et le code de `main`, pas un état
d'exécution présent. « Sans décision au registre » signale une capacité qui
dépend d'un choix du propriétaire absent de `docs/project/decisions.md`.
« À régulariser » reprend la liste de `AGENTS.md` des composants en service
sans décision au registre ou au-delà de leur décision.

## État essentiel

- **Chat BOOTSTRAP : vérifié au relevé du 2026-09-09 en CLI et via une
  passerelle HTTPS privée.** Des poids GGUF Qwen2.5-1.5B vérifiés étaient
  chargés par llama.cpp sur CPU et produisaient une vraie réponse. Le serveur
  restait lié à sa boucle locale ; la passerelle authentifiée appelait ce
  moteur et était relayée dans le tailnet. Depuis `9b31b41`, l'interface
  libelle cet emplacement « CHAT-14B · Qwen2.5-14B » alors que le dépôt ne
  verrouille que le 1.5B : sans décision au registre, à régulariser. Ce modèle
  tiers temporaire reste distinct de CORE.
- **Agent de programmation Qwen2.5-Coder-7B : promu par le propriétaire le
  2026-09-10.** Selon le relevé
  `configs/runtime/qwen2.5-coder-7b-q4km.promotion.json`, il a été déployé sur
  un nœud physique séparé, avec empreintes relues et une seule entrée réseau
  depuis la passerelle ; il obtient 38/50 sur E2 en un essai et 45/50 avec une
  passe de réparation. Le relevé `docs/operations/qwen-conversation-fix.md`
  consigne son raccordement à la passerelle par fichiers ciblés.
- **CORE-MINI : harness fonctionnel.** Un entraînement synthétique et un
  entraînement `authorized-text` de 50 étapes, repris jusqu'à l'étape 60, ont
  été vérifiés avec checkpoints et empreintes. Un checkpoint synthétique frais
  de vingt étapes a été copié sur le stockage durable, restauré dans un fichier
  de contrôle et repris offline à l'étape 21.
- **Runner NUMA : deux paires A/B de sens opposé.** Le 2026-09-06, la médiane
  de A était 3,8 % au-dessus de B ; le 2026-09-07, révision `6cebad1`, le ratio
  A/B vaut 0,9497, soit B environ 5,3 % au-dessus de A, avec des plages
  observées qui se recouvrent. L'observation est non concluante ; aucun choix
  de placement ni délai n'en est déduit et le gate G4 reste ouvert.
- **CORE-30M : pilote de pipeline.** La lignée a atteint son palier final de
  19 532 étapes avec copie durable relue. Elle ne produit ni chat ni assistant
  de code : la tentative E1 du 2026-09-09 sur le checkpoint final a été
  refusée par le garde E0 sur une sortie répétitive (`ff16ad9`) ; aucun paquet
  E1 n'a été créé.
- **CORE-700M : preuves mécaniques archivées.** L'architecture candidate et son
  comptage exact de 691 160 320 paramètres sont versionnés ; le tokenizer 32k
  est promu en `candidate_core` avec reçu d'empreintes. Conformément à D-034,
  CORE-700M ne reçoit pas de palier long.
- **Corpus : gate simplifié, ratifié par D-039.** Depuis `6d959d7`, un
  manifeste validé suffit au préflight et `approved.json` n'est plus bloquant.
  D-039 autorise une version de corpus dès qu'une politique automatique
  versionnée et auditée produit ce manifeste ; cette politique n'est pas
  désignée dans le dépôt. D-041 vise environ 40 % de français technique et
  D-042 un tokenizer réentraîné sur le corpus final.
- **MCP Knowledge et RAG : recherche lexicale approuvée au relevé ; recherche
  hybride dans le code.** MCP expose en `stdio` l'état, la recherche lexicale
  et une provenance exacte. La passerelle joint des extraits bornés de son
  index approuvé et retourne les citations. Le manifeste `project-internal-v1`
  couvre quatre documents internes versionnés ; la page des capacités en fait
  partie et sa révision du 2026-09-26 doit être réapprouvée par le propriétaire
  avant reconstruction. Le moteur d'embeddings Qwen3-Embedding-0.6B est présent
  dans le code (`d7cc78c`), déploiement non vérifié ; depuis `c7d1510`, un lock
  candidat attend la relecture RAW de son empreinte et de sa licence, et
  l'ADR-0007 est PROPOSÉ. Le moteur d'embeddings et le dépôt de documents sont
  à régulariser.
- **Interface Web du projet : installée derrière le HTTPS privé au relevé du
  2026-09-09.** Argon2id, sessions, CSRF, mémoire SQLite locale, historique
  réouvrable, export, suppression et client llama.cpp loopback fonctionnaient.
  Le code ajoute depuis les pages `/arena`, `/corpus` et `/sante` ; aucun relevé
  n'atteste leur installation.
- **Agents et outils : code sans relevé.** Le registre garde les 60 profils en
  `draft`, mais le code rend les profils du catalogue sélectionnables dans le
  chat sans leurs gates d'évaluation. Il ajoute des outils en lecture seule et
  deux actions, `run_python` et `write_file`, chacune derrière une
  confirmation humaine à usage unique. Profils et boucle d'outils sont à
  régulariser. D-035 place les deux actions derrière l'interrupteur
  `SOVEREIGN_ACTIONS_ENABLED`, désactivé par défaut ; le code de `main`
  l'implémente depuis `c0b169e`, sans déploiement consigné.
- **Arène d'agents et incréments de corpus : code et observations de commit.**
  Le code de l'arène produit des paquets de solutions vérifiées par le bac à
  sable, en attente d'approbation ; un paquet approuvé peut devenir un
  incrément RAW puis être promu en VALIDATED depuis l'interface. Les commits
  rapportent des paquets réels, mais aucun relevé versionné ne les confirme.
  L'arène et la boucle sont à régulariser. D-044 consigne que l'arène a joué
  sur E2 le 2026-09-11, étiquette E2 « contaminée » et la remplace, pour
  l'évaluation, par une suite E2-v2 scellée hors dépôt ; D-043 révoque
  l'autorisation d'entraînement des incréments `0001` et `0002`. Depuis
  `eea75b5`, le code de l'arène et du constructeur d'incréments prend par
  défaut la suite d'entraînement et le constructeur refuse les tâches E2 ; la
  suite jouée sur le serveur n'est pas consignée. D-040 admet le code
  synthétique de l'arène généré par Qwen2.5-Coder, sans recouvrement avec les
  jeux d'évaluation, dans la limite de 20 % des tokens d'une version de
  corpus ; les validateurs de `main` ne sont pas encore alignés sur cette
  règle. D-045 active l'approbation automatique réelle des paquets ; ni elle
  ni le refus des incréments révoqués ne sont implémentés dans le code de
  `main`.
- **Orchestrateur et autorisations : préparation seulement.** Les validateurs
  fail-closed existent ; les outils du chat passent par la passerelle, pas par
  l'orchestrateur.
- **Collector : ingress write-only vérifié en direct au relevé du 2026-08-31
  (`cd1740e`).** Son endpoint HTTPS de santé répondait ; une entrée acceptée
  reste `RAW` et n'est jamais promue automatiquement.
- **Stockage : partage Synology monté et persistant.** L'arborescence durable
  est accessible au conteneur CORE depuis un montage hôte SMB 3.1.1 chiffré,
  activé au démarrage et contrôlé par un compte de service limité. Une écriture
  temporaire suivie de sa suppression et un aller-retour synthétique vérifié
  par empreinte ont été validés depuis CORE. Les sauvegardes SQLite de mémoire
  et d'index lexical ont été vérifiées et restaurées dans des fichiers de
  contrôle, sans remplacement de la base utilisée par l'application.
- **Zone CORE : invitée non privilégiée au relevé.** Les flux et le stockage
  sont bornés. Le runtime PyTorch/NumPy CPU, reconstruit depuis des wheels
  vérifiés, est installé hors ligne et a passé son smoke test CPU. Aucun poids
  CORE utile n'existe.

Ces éléments ont été établis comme preuves opérationnelles réversibles pendant
la phase 0. Le passage en phase 1 (D-038) ne valide ni l'orientation P-002, ni
la topologie cible, ni un gate : G0 à G8 et A0 à A8 restent ouverts.

## Preuves techniques actuelles

- PyTorch CPU et NumPy ont été vérifiés contre leurs locks, réinjectés hors
  ligne dans CORE et validés sans CUDA ni ROCm ;
- après cette réinjection, CORE ne possède pas de route par défaut ; les tests
  DNS externe et TCP direct vers Internet ont été refusés ;
- CUDA et ROCm ne font pas partie du runtime ;
- CORE-80M s'est historiquement instancié en CPU avec son nombre candidat exact ;
- CORE-700M possède une configuration et un comptage exacts ; deux paliers
  techniques ont prouvé chargement, checkpoint et reprise, sans poids utiles ;
- le cycle CORE-MINI entraînement → checkpoint → reprise a réussi sur Linux
  avec 20 étapes puis 5 étapes de reprise sous les contrôles stricts actuels ;
- le manifeste est lié au seul split `train` par taille, compte et SHA-256 ;
  le contrat tokenizer accepte `experimental` pour les essais et
  `candidate_core` pour la préparation CORE, avec refus des autres états ;
- la configuration CORE-MINI est lue, validée et hachée depuis une unique copie
  bornée, avec architecture et comptage exacts ; les erreurs CLI publiques
  n'exposent pas les chemins fournis ;
- le harness exige explicitement manifeste, JSONL `train` et tokenizer, vérifie
  le vocabulaire exact et lie métriques et checkpoint au contrat sans recopier
  le contenu ;
- le checkpoint `authorized-text` lie l'empreinte du préfixe exact du journal
  attendu à la reprise ;
- la reprise du modèle et de l'optimiseur utilise des contrôles CPU stricts
  partagés avec le vérificateur offline et refuse les strides, stockages ou
  alias AdamW anormaux ;
- la vérification renforcée d'un ancien checkpoint historique reste à terminer
  sur Linux ;
- le MCP Knowledge répond et retourne des résultats synthétiques avec
  `provenance_id` ;
- l'expéditeur du Collector refuse les redirections HTTP, valide les payloads
  en file et n'efface une entrée qu'après écriture atomique et vérification
  locale d'un reçu concordant ;
- le summarizer de métriques `v2` valide un journal borné et publie son SHA-256
  exact ainsi que moyenne, médiane, écart-type de population, MAD et débit
  après chauffe ;
- le runner NUMA exige un nouveau répertoire absolu, un contrat de
  placement privé strict, une session UUID v4, une archive Git canonique et un
  lock de runtime offline ; ses paramètres de charge et délais sont bornés ;
- il refuse de démarrer si les sockets flux ou datagrammes des familles
  `AF_INET` et `AF_INET6` restent disponibles, vérifie l'égalité exacte du
  placement observé avec le contrat dans chaque phase enfant, puis exécute 3 à
  10 répétitions en processus frais ; chaque résumé est relu et chaque
  checkpoint est repris une étape sans modifier sa source ;
- sa preuve publique ne contient ni hostname, ni modèle ou liste CPU, ni
  commande ou chemin. Les deux paires A/B comparées sont de sens opposé et
  non concluantes ; le comparateur employé pour elles ne vérifiait pas que
  les deux contrats de placement étaient distincts. Depuis `654b730`, il
  refuse deux preuves de même engagement et un vérificateur hors ligne établit
  cette distinction à partir des contrats privés, sans exécution consignée sur
  ces preuves. Aucune mesure mémoire ni série complète de compteurs NUMA ne
  permet d'extrapoler une durée d'entraînement ;
- tests : 198 tests passaient à la révision `8071843` ; les messages de commit
  rapportent 470 tests verts à `dbca0c6` ; l'intégration continue Linux
  hébergée de D-037 est versionnée depuis `ad1ed68`, et aucune exécution sur
  le nœud de calcul n'est consignée.

## Non revendiqué

Le projet ne revendique pas encore : entraînement sur un corpus réel approuvé
au-delà des pilotes, poids linguistiques CORE utiles, modèle conversationnel
CORE, RAG sémantique vérifié sur le serveur, agents autonomes, outils ou
profils approuvés au registre, arène activée par décision, interface
utilisateur finale, authentification de production, gate réseau achevé,
décision NUMA G4 acceptée ou entraînement CORE-700M. Le service BOOTSTRAP
privé est une démonstration bornée, pas un service CORE de production.

Le contenu de ce jalon ne versionne aucun secret, identifiant privé ni adresse
d'administration.
