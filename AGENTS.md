# AGENTS.md — règles de travail du dépôt

Ce fichier s'applique à tout le dépôt. Il guide Codex et tout autre agent de développement.

## Mission

Construire progressivement une IA locale souveraine, CPU-only, auditable et isolée d'Internet. Le système doit combiner un modèle créé dans ce projet, un RAG avec provenance, des agents logiques, une mémoire contrôlée et une ingestion externe par sas de sécurité.

La priorité n'est pas de produire vite beaucoup de code. La priorité est de préserver les frontières de sécurité, mesurer le matériel réel et rendre chaque décision réversible et traçable.

## Sources de vérité

Lire avant toute modification :

1. `docs/project/decisions.md` pour les décisions fermes et provisoires ;
2. `docs/project/discovery-questionnaire.md` pour les informations manquantes ;
3. `docs/architecture/overview.md` et `docs/security/threat-model.md` pour les frontières ;
4. le document spécialisé concerné par le changement ;
5. les issues GitHub acceptées pour le travail demandé.

En cas de conflit, appliquer dans cet ordre : sécurité et décisions fermes, demande explicite du propriétaire, ADR approuvé, documentation spécialisée, issue. Signaler le conflit au lieu de choisir silencieusement.

## Contraintes non négociables

- V1 CPU-only : ne jamais introduire de dépendance ou de chemin d'exécution nécessitant GPU, CUDA, ROCm ou TPU.
- IA-CORE ne contacte jamais Internet, directement ou indirectement.
- Le DL380p Gen8 ne reçoit aucun service V1.
- Le ML350 Gen9 réalise le calcul et l'entraînement principaux.
- Le RS3617xs+ stocke ; il ne réalise pas l'entraînement principal.
- L'ingestion externe et la consultation des connaissances internes sont des frontières de confiance distinctes, sans identité ni droit partagé. Deux services MCP séparés sont le candidat actuel, pas une décision définitive avant ADR.
- Le collecteur externe ne lit jamais les documents, mémoires, modèles ou réseaux internes.
- Toute entrée externe reste non fiable, même si elle vient d'un fournisseur d'IA connu.
- `RAW` n'est pas `VALIDATED`. Aucune promotion automatique sans politique et trace d'audit.
- Une version nettoyée ne remplace et ne détruit jamais l'original RAW.
- Aucun secret, donnée personnelle réelle ou détail interne sensible dans le dépôt, les fixtures ou les exemples.
- Les agents sont des profils logiques à permissions minimales ; ne pas instancier un modèle complet par agent.
- Ne jamais promettre une durée d'entraînement avant benchmark reproductible sur le ML350.

## Phase actuelle

La phase courante est **0 — découverte**.

Avant le gate d'architecture, les changements autorisés sont : documentation, schémas de données, modèles de menace, ADR, outils de calcul statique, harness de benchmark minimal et tests associés. Ne pas déployer de service de production, ouvrir de port, appeler un fournisseur externe ou créer une liaison entre zones sans décision approuvée.

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
- rendre les refus sûrs et journalisables ;
- conserver identifiants, versions de schéma, horodatages et provenance ;
- éviter les dépendances lourdes tant qu'un besoin mesuré ne les justifie pas ;
- employer des identifiants techniques en anglais et une documentation utilisateur en français ;
- ne pas ajouter de télémétrie externe ni de téléchargement automatique.

Après l'édition :

- exécuter les tests ciblés puis les contrôles du dépôt ;
- documenter toute nouvelle option de configuration ;
- mettre à jour le registre si et seulement si une décision a été approuvée ;
- indiquer ce qui a été mesuré et ce qui reste une estimation ;
- vérifier qu'aucune donnée sensible ni aucun secret n'apparaît dans le diff.

## Règles d'architecture

Les dépendances doivent suivre le sens de confiance :

```text
external providers
  -> controlled acquisition (Research Gateway if option B is approved)
  -> external ingress/collector
  -> quarantine
  -> controlled promotion
  -> internal knowledge
  -> IA-CORE
```

Une dépendance inverse est interdite par défaut. Un accusé de réception technique du collecteur peut être autorisé dans sa propre zone, mais il ne doit contenir aucune donnée interne.

Ne jamais exposer via MCP :

- exécution de shell générique ;
- lecture ou écriture de chemin arbitraire ;
- accès réseau arbitraire ;
- récupération de secrets ;
- recherche dans les mémoires privées depuis la DMZ ;
- promotion directe en connaissance validée.

## Données et provenance

- Utiliser des identifiants stables et un schéma versionné.
- Calculer les empreintes sur des octets canoniques clairement définis.
- Conserver séparément contenu brut, dérivés, décisions de validation et index.
- Une suppression logique ou une rétention réglementaire ne doit pas être confondue avec une promotion de contenu ; documenter les exceptions à l'immuabilité.
- Toute affirmation exploitable doit pouvoir remonter à un paquet, une source et une décision de validation.
- Les journaux d'audit ne doivent pas recopier inutilement le contenu ou les secrets.

## Modèle et benchmarks

`CORE-80M` est le nom de travail d'un candidat, pas une architecture approuvée. Toute modification de sa définition doit mettre à jour ensemble la configuration, le calcul exact et les tests.

Pour les performances :

- enregistrer matériel, VM/LXC, affinité CPU, NUMA, RAM, versions, threads, batch, contexte et dataset ;
- séparer débit de préparation, entraînement et inférence ;
- rapporter médiane, dispersion et période de chauffe ;
- ne pas extrapoler avant un mini-entraînement réussi et reproductible ;
- ne pas comparer des résultats obtenus avec des protocoles différents comme s'ils étaient équivalents.

## Tests minimaux

Selon le changement, couvrir :

- chemin nominal ;
- entrée malformée, trop grande ou de type interdit ;
- permission refusée ;
- absence de réseau extérieur depuis IA-CORE ;
- tentative de lecture interne depuis le collecteur ;
- conservation du RAW après transformation ;
- traçabilité de la promotion ;
- reprise après interruption et idempotence ;
- calcul exact des paramètres du modèle.

## Code Review Rules

Lors d'une revue Codex, signaler en priorité tout changement qui :

- ajoute un chemin réseau, une télémétrie ou un téléchargement depuis IA-CORE ;
- permet au Collector externe de lire, lister ou modifier des données internes ;
- promeut une entrée RAW sans validation et trace d'audit ;
- donne à un outil MCP un shell, un chemin de fichier ou un accès réseau arbitraire ;
- introduit un secret, une donnée réelle sensible ou un artefact de modèle dans Git ;
- dépend d'un GPU ou présente une estimation non mesurée comme un résultat ;
- change un contrat de données ou le calcul de CORE-80M sans migration, test et documentation.

Proposer avec chaque signalement une voie sûre : refus par défaut, capacité plus étroite, schéma strict, fixture synthétique, benchmark reproductible ou décision explicite. Laisser le style et le formatage mécanique aux contrôles automatisés.

## Définition de terminé

Un changement est terminé quand : le besoin et le périmètre sont clairs, les contraintes fermes sont respectées, les tests pertinents passent, la documentation reflète le comportement, les risques résiduels sont explicités et aucun choix encore ouvert n'est présenté comme décidé.

