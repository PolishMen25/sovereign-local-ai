# AGENTS.md — règles de travail du dépôt

Ce fichier s'applique à tout le dépôt et à tout agent de développement
(Codex, Claude Code ou autre). Il est maintenu sous l'autorité du
propriétaire du projet : un agent peut proposer une modification par PR, jamais
la fusionner seul.

## Mission

Construire progressivement une IA locale souveraine, CPU-only, auditable et
isolée d'Internet. Le système combine un modèle créé dans ce projet, un RAG
avec provenance, des agents logiques, une mémoire contrôlée et une ingestion
externe par sas de sécurité.

La priorité n'est pas de produire vite beaucoup de code. Elle est de préserver
les frontières de sécurité, de mesurer le matériel réel et de rendre chaque
décision réversible et traçable.

## Sources de vérité

Lire avant toute modification :

1. `docs/project/decisions.md` : décisions confirmées (`D-xxx`) et
   orientations provisoires (`P-xxx`) ;
2. `docs/project/current-capabilities.md` : ce qui fonctionne réellement ;
3. `docs/project/claude-code-handoff.md` : état de reprise le plus récent ;
4. `docs/architecture/overview.md` et `docs/security/threat-model.md` :
   frontières et menaces ;
5. `docs/project/discovery-questionnaire.md` : informations encore manquantes ;
6. le document spécialisé concerné, puis l'issue GitHub acceptée.

En cas de conflit, appliquer dans cet ordre : sécurité et décisions confirmées,
demande explicite du propriétaire, ADR approuvé, documentation spécialisée,
issue. Signaler le conflit au lieu de choisir silencieusement. Un document de
reprise ou de capacités peut être en retard sur le code : le vérifier contre
Git avant de s'y fier.

## Contraintes non négociables

**Calcul et matériel**

- CPU-only (D-001) : aucune dépendance ni chemin d'exécution nécessitant GPU,
  CUDA, ROCm ou TPU.
- Le HPE ML350 Gen9 porte le calcul et l'entraînement principaux (D-002).
- Le Synology RS3617xs+ stocke ; il n'entraîne pas (D-004, D-005).
- Le DL380p Gen8 ne reçoit aucune fonction CORE ni aucun entraînement (D-006,
  remplacée par D-034).
- L'agent de programmation Qwen s'exécute sur un nœud physique séparé, sans
  privilège d'administration du cluster (D-034).
- Aucune durée d'entraînement n'est annoncée avant un benchmark reproductible
  sur le ML350 (D-015).

**Frontières de confiance**

- IA-CORE ne contacte jamais Internet, directement ou indirectement ; le blocage
  est imposé au réseau (routes, DNS) et prouvé par des tests négatifs (D-007).
- L'ingestion externe et la consultation des connaissances internes sont des
  frontières distinctes, sans identité ni droit partagé ; deux services MCP
  séparés restent le candidat P-002, non décidé avant ADR.
- Le collecteur externe ne lit jamais les documents, mémoires, modèles ou
  réseaux internes (D-009).
- Toute entrée externe reste non fiable, même venant d'un fournisseur d'IA
  connu (D-012).

**Données**

- `RAW` n'est pas `VALIDATED` (D-010). Une version nettoyée ne remplace ni ne
  détruit jamais l'original RAW (D-011).
- Une promotion automatique n'est permise que par une **politique versionnée
  approuvée au registre**, avec journal d'audit, acteur identifié (jamais le
  nom du propriétaire), refus en cas de doute et révocation possible avant
  consommation. Sans cette politique, toute promotion passe par le propriétaire.
- Les jeux d'évaluation (E0, E1, E2 et suivants) n'entrent jamais dans un
  entraînement, ni directement ni par une donnée dérivée ou paraphrasée.
- Une conversation n'alimente les poids qu'à travers un manifeste validé, ses
  empreintes et le gate d'entraînement (D-032).

**Dépôt public**

- Le dépôt est public. Aucun secret, donnée personnelle réelle, adresse IP,
  nom d'hôte, identifiant de conteneur, chemin d'infrastructure, compte,
  numéro de série, valeur matérielle exacte (D-025) ni détail de posture de
  sécurité. Ces éléments vivent dans une configuration ou un inventaire privés,
  hors Git (D-004, D-036).
- Un secret affiché ou commité est considéré comme compromis : révocation
  d'abord, purge ensuite.

**Agents et actions**

- Les agents sont des profils logiques à permissions minimales partageant un
  petit nombre de moteurs ; jamais un modèle complet par agent (D-016).
- L'assistant est force de proposition : toute action durable, sortie de
  données ou modification d'infrastructure exige une confirmation humaine, et
  une sortie de modèle ne s'auto-confirme jamais (D-021). Aucune découverte
  réseau, exécution de commande ni accès aux secrets par défaut (D-022).
- Les actions du chat (`run_python`, `write_file`) doivent être placées derrière
  l'interrupteur `SOVEREIGN_ACTIONS_ENABLED`, désactivé par défaut (D-035). Tant
  que ce code n'est ni fusionné ni déployé, aucun agent ne s'appuie sur cet
  interrupteur ni n'étend ces actions ; leur réactivation exige une décision
  distincte.

## Phase actuelle

La phase courante est **1 — socle expérimental en service** (D-038). Elle
correspond aux jalons J0 à J2 de la [feuille de route](docs/ROADMAP.md),
partiellement réalisés, avec des prototypes de jalons ultérieurs.

Sont en service, chacun dans les limites exactes de sa décision :

| Composant | Décision |
| --- | --- |
| Chat BOOTSTRAP Qwen2.5-1.5B, modèle tiers temporaire, sans outil ni agent | D-024 |
| Passerelle Web authentifiée, mono-utilisateur, HTTPS privé | D-030 |
| Mémoire conversationnelle locale | D-032 ; sauvegardes : D-023 |
| Collecteur de conversations en écriture seule vers RAW | D-008, D-009, D-032 |
| Agent de programmation Qwen2.5-Coder | D-034 |
| Stockage durable Synology | D-023 (protocole NAS encore ouvert) |

Sont en service **sans décision au registre**, ou au-delà de leur décision, et
doivent être régularisés par le propriétaire avant toute extension :

- le moteur 14B qui sert l'emplacement BOOTSTRAP, et la boucle d'outils du chat ;
- l'activation des profils du catalogue dans le chat ;
- le moteur d'embeddings, autorisé dans son principe par D-028 mais sans lock
  ni reçu de promotion ;
- l'analyse et le téléversement de documents ;
- l'arena et la boucle d'auto-entraînement.

Un agent ne les étend pas, ne les active pas davantage et ne s'appuie pas sur
leur présence comme autorisation. La validation du pipeline CPU par CORE-30M
(D-034) est terminée et archivée ; elle n'est pas un service.

Ce qu'un agent peut faire, selon le cas :

| Changement | Condition |
| --- | --- |
| Documentation, schémas, ADR proposés, modèles de menace, outils locaux, tests | PR, tests et CI verts |
| Correction d'un composant en service, dans les limites exactes de sa décision | PR revue et CI verte ; fusion et déploiement par archive versionnée avec l'accord du propriétaire, ponctuel ou permanent (voir « Exploitation ») ; composants à régulariser exclus |
| Nouveau moteur, service, port, outil, profil, source de données, flux entre zones, appel à un fournisseur externe ou promotion automatique | Décision du propriétaire au registre, et ADR si le choix est structurant |
| Entraînement ou reprise d'entraînement | Contrat approuvé par le propriétaire (manifeste, tokenizer, préflight) et gate correspondant accepté ; aucun contournement |

Les gates G0 à G8 de la feuille de route et A0 à A8 de l'architecture restent
ouvertes tant que leurs preuves ne sont pas acceptées par le propriétaire.

## Travail à plusieurs agents

- Une branche par lot, créée depuis `origin/main` ; une PR vers `main`.
- Les branches `codex/*` appartiennent à Codex, les branches `claude/*` à
  Claude Code. Ne jamais committer, rebaser ni forcer la branche ou le dossier
  de travail d'un autre agent ; ne jamais réécrire la branche d'une PR du
  propriétaire sans son accord.
- Travailler dans un worktree dédié, jamais dans le dossier où un autre agent
  a des modifications non commitées.
- Une tâche par commit, message `<type>(<portée>): <résumé en français>`, corps
  expliquant le pourquoi et, s'il existe, l'identifiant de la tâche ou de
  l'issue. Auteur : l'adresse `noreply` GitHub du propriétaire, avec une ligne
  `Co-Authored-By:` qui identifie l'agent ayant produit le commit.
- La CI (D-037) doit être verte avant fusion ; un échec préexistant se signale,
  il ne s'ignore pas.

## Protocole de travail

Avant d'éditer :

- vérifier si la question est déjà répondue ;
- distinguer `CONFIRMÉ`, `PROVISOIRE`, `OUVERT` et `HYPOTHÈSE` ;
- ne jamais inventer une caractéristique de l'infrastructure ;
- limiter le changement au périmètre de l'issue ;
- identifier les données et frontières de confiance touchées.

Pendant l'édition :

- privilégier de petits composants à responsabilité unique ;
- valider les entrées à la frontière, avec schémas stricts et limites explicites ;
- rendre les refus sûrs et journalisables ; échouer fermé ;
- conserver identifiants, versions de schéma, horodatages et provenance ;
- éviter les dépendances lourdes tant qu'un besoin mesuré ne les justifie pas ;
- identifiants techniques en anglais, documentation utilisateur en français ;
- aucune télémétrie externe ni téléchargement automatique.

Après l'édition :

- exécuter les tests ciblés puis la suite complète ;
- documenter toute nouvelle option de configuration ;
- mettre à jour le registre si et seulement si le propriétaire a approuvé une
  décision ;
- indiquer ce qui a été mesuré et ce qui reste une estimation ;
- vérifier qu'aucune donnée sensible ni aucun identifiant privé n'apparaît dans
  le diff.

## Exploitation de l'infrastructure

- Lecture seule par défaut. Toute écriture sur le cluster ou le NAS est
  précédée d'une sauvegarde de l'état modifié et accompagnée d'un retour
  arrière décrit.
- Déployer uniquement des archives versionnées, construites depuis un commit
  testé et vérifiées par empreinte ; ne jamais modifier une release installée
  en place.
- Avant toute action, détecter les calculs en cours et les laisser finir ; ne
  jamais interrompre un entraînement pour une opération de confort.
- Checkpoints : écriture atomique, destination absente, empreinte SHA-256
  comparée entre source et copie durable, source conservée.
- Avant de relancer le calcul, vérifier le stockage durable selon le runbook
  de préparation du Synology.
- Ne redémarrer un service qu'en cas de nécessité, en l'annonçant et en
  vérifiant son état après coup.
- Les détails d'exploitation (adresses, comptes, chemins, inventaires) restent
  dans la documentation privée, hors Git.

## Règles d'architecture

Les dépendances suivent le sens de confiance :

```text
external providers
  -> controlled acquisition (Research Gateway if option B is approved, P-001)
  -> external ingress/collector
  -> quarantine
  -> controlled promotion
  -> internal knowledge
  -> IA-CORE
```

Une dépendance inverse est interdite par défaut. Un accusé de réception
technique du collecteur peut être autorisé dans sa propre zone, sans aucune
donnée interne.

Ne jamais exposer via MCP ni via un outil de chat :

- exécution de shell générique ;
- lecture ou écriture de chemin arbitraire ;
- accès réseau arbitraire ;
- récupération de secrets ;
- recherche dans les mémoires privées depuis la DMZ ;
- promotion directe en connaissance validée.

## Données et provenance

- Identifiants stables et schémas versionnés.
- Empreintes calculées sur des octets canoniques clairement définis.
- Contenu brut, dérivés, décisions de validation et index conservés séparément.
- Une suppression logique ou une rétention réglementaire n'est pas une
  promotion ; les exceptions à l'immuabilité sont documentées.
- Toute affirmation exploitable remonte à un paquet, une source et une décision
  de validation.
- Les journaux d'audit ne recopient ni contenu inutile ni secret.

## Modèle et benchmarks

- CORE-30M a validé le pipeline CPU ; il n'a pas d'objectif conversationnel
  (D-034). CORE-700M est archivé comme preuve mécanique,
  CORE-80M comme référence historique ; aucun n'est présenté comme assistant.
- Toute modification de la définition d'un candidat met à jour ensemble sa
  configuration, son comptage exact de paramètres et ses tests.
- Pour les performances : enregistrer matériel, VM/LXC, affinité CPU, NUMA,
  RAM, versions, threads, lot, contexte et dataset ; séparer préparation,
  entraînement et inférence ; rapporter médiane, dispersion et chauffe ; ne
  pas extrapoler avant un mini-entraînement réussi et reproductible ; ne pas
  comparer des protocoles différents.

## Tests minimaux

Selon le changement, couvrir :

- chemin nominal ;
- entrée malformée, trop grande ou de type interdit ;
- permission refusée ;
- absence de réseau extérieur depuis IA-CORE ;
- tentative de lecture interne depuis le collecteur ;
- conservation du RAW après transformation ;
- traçabilité de la promotion, humaine ou par politique ;
- séparation entre données d'évaluation et d'entraînement ;
- reprise après interruption et idempotence ;
- calcul exact des paramètres du modèle.

## Règles de revue

Signaler en priorité tout changement qui :

- ajoute un chemin réseau, une télémétrie ou un téléchargement depuis IA-CORE ;
- permet au collecteur externe de lire, lister ou modifier des données internes ;
- promeut une entrée RAW sans politique approuvée ni trace d'audit ;
- laisse une donnée d'évaluation atteindre un entraînement ;
- donne à un outil MCP ou de chat un shell, un chemin de fichier ou un accès
  réseau arbitraire, ou contourne `SOVEREIGN_ACTIONS_ENABLED` ;
- introduit un secret, un identifiant d'infrastructure privé, une donnée réelle
  sensible ou un artefact de modèle dans Git ;
- dépend d'un GPU ou présente une estimation non mesurée comme un résultat ;
- change un contrat de données ou la définition d'un candidat CORE sans
  migration, test et documentation.

Proposer avec chaque signalement une voie sûre : refus par défaut, capacité
plus étroite, schéma strict, fixture synthétique, benchmark reproductible ou
décision explicite. Laisser le style et le formatage mécanique aux contrôles
automatisés.

## Définition de terminé

Un changement est terminé quand : le besoin et le périmètre sont clairs, les
contraintes fermes sont respectées, les tests pertinents et la CI passent, la
documentation reflète le comportement, les risques résiduels sont explicités
et aucun choix encore ouvert n'est présenté comme décidé.
