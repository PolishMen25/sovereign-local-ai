# Roadmap du projet

## Mode de pilotage

La roadmap est organisée en jalons et portes de décision (`gate`). Une porte peut conclure `GO`, `À REVOIR` ou `ARRÊT`. Le passage au jalon suivant dépend de preuves mesurées et de livrables vérifiables, pas d'une date arbitraire.

Aucune durée d'entraînement du modèle cible n'est annoncée avant le benchmark miniature sur le ML350 bi-socket NUMA au jalon J4. Les estimations ultérieures restent des fourchettes avec hypothèses et incertitudes.

Les gates `G0–G8` de ce document pilotent le projet. Les gates `A0–A8` du document d'architecture vérifient séparément l'aptitude opérationnelle et la sécurité.

> Des prototypes appartenant à des jalons ultérieurs sont déjà présents pour
> réduire les risques techniques. Leur présence ne signifie pas que le jalon ou
> son gate est terminé. En particulier, le chat CORE-700M, le RAG sémantique et
> les agents restent non disponibles.

## Périmètre V1

La V1 couvre une chaîne locale CPU-only : ingestion contrôlée, gouvernance des données, modèle principal créé de zéro, entraînement reproductible, évaluation, inférence locale, RAG traçable, accès MCP interne et premiers profils d'agents logiques.

Sont explicitement hors V1 :

- l'intégration du serveur DL380p ;
- la génération d'images ;
- 60 copies du modèle — la cible est d'environ 60 profils logiques partageant un petit nombre de moteurs.

## J0 — Cadrage et inventaire fiable

**Objectif :** transformer les intentions en contraintes vérifiables sans inventer l'état de l'infrastructure.

Livrables :

- réponses au questionnaire de découverte et trois cas d'usage V1 priorisés ;
- inventaires vérifiés du ML350, de Proxmox, du Synology et du réseau ;
- registre des informations connues, manquantes, hypothèses, décisions et risques ;
- critères de succès mesurables pour sécurité, ingestion, modèle, RAG et exploitation ;
- propriétaires des décisions et risques bloquants.

**Gate G0 :** aucune inconnue critique n'est masquée ; chaque choix ouvert possède une preuve attendue et un moment de décision.

## J1 — Architecture et socle sécurisé

**Objectif :** approuver les frontières de confiance et obtenir un dépôt reproductible sans secret.

Livrables :

- topologie cible, flux autorisés/interdits et modèle de menace approuvés ;
- choix documenté du mécanisme de sas et de la méthode d'administration ;
- conventions du dépôt, commandes locales reproductibles et contrôles automatiques minimaux ;
- règles de secrets, dépendances, licences, sauvegarde et restauration ;
- plan de tests négatifs prouvant l'absence d'accès Internet depuis IA-CORE ;
- ADR requis avant toute ouverture de port ou déploiement interzone.

**Gate G1 :** les frontières sont vérifiables, le plan de retour arrière existe et aucun secret n'est versionné. Un prototype peut être construit sans ouvrir implicitement un flux interdit.

## J2 — Ingestion contrôlée et provenance

**Objectif :** recevoir une recherche externe sans lui accorder de confiance ni de droit de lecture interne.

Livrables :

- ADR comparant dépôt direct et architecture B avec Research Gateway ;
- contrat d'ingress versionné imposant l'état `RAW` et validation sémantique côté serveur ;
- schémas append-only pour événements de cycle de vie, décisions et artefacts dérivés ;
- prototype de Collector sans opération `get`, `list`, `search`, `status`, `update` ou `delete` ;
- stockage RAW immuable, reçu d'ingress, idempotence et journal d'audit ;
- quarantaine avec limites de format/taille/ressources, contrôle de secrets et corpus de fichiers hostiles ;
- politique de promotion définissant validation automatique autorisée et revue humaine obligatoire.

**Gate G2 :** un émetteur externe ne peut ni déclarer une donnée validée, ni lire le système interne, ni contourner la quarantaine. Empreintes, reprise, rejet et restauration sont testés.

## J3 — Corpus, tokenizer et stratégie RAG

**Objectif :** préparer des données autorisées et les choix de recherche nécessaires au modèle et au RAG.

Livrables :

- politique des sources, licences, consentements, données personnelles et exclusions ;
- pipeline de normalisation, filtrage, déduplication et découpage versionné ;
- manifeste donnant l'origine et l'empreinte de chaque artefact ;
- jeux d'entraînement, validation et test séparés et contrôlés contre les fuites ;
- expériences de tokenizer permettant de valider ou réviser le vocabulaire candidat de 32 000 unités ;
- ADR sur le moteur d'embeddings du RAG et l'éventuel reranker, créés de zéro ou pré-entraînés ;
- comparaison CPU des solutions d'index vectoriel et plan de sauvegarde/reconstruction.

**Gate G3 :** chaque donnée d'entraînement est traçable et autorisée ; tokenizer, corpus, moteur d'embeddings RAG et critères de recherche sont explicitement approuvés.

## J4 — Mini-modèle et benchmark CPU/NUMA

**Objectif :** prouver le chemin logiciel complet et mesurer la faisabilité avant toute projection vers CORE-700M.

Livrables :

- implémentation miniature utilisant les mêmes familles d'opérations que le candidat : masque causal, MHA, RoPE, RMSNorm, SwiGLU et poids liés ;
- compteur lisant la configuration candidate et vérifiant exactement 691 160 320 paramètres ;
- cycle entraînement → évaluation → checkpoint → reprise → inférence sur un petit corpus autorisé ;
- mesures un socket/deux sockets, placements NUMA, threads, lots et longueurs de séquence ;
- débit en tokens/s, mémoire de pointe, CPU, défauts NUMA, entrées/sorties et temps de checkpoint ;
- résultats bruts reproductibles sur au moins deux tailles miniatures ;
- extrapolation avec marges d'incertitude et critères d'arrêt.

**Gate G4 :** le chemin complet est correct et reproductible, le benchmark est accepté par le propriétaire et une fourchette de ressources est disponible. Toute sortie de la cible 50–100M exige une nouvelle décision explicite.

## J5 — Pilote de montée en échelle

**Objectif :** confronter l'extrapolation à des exécutions intermédiaires avant l'entraînement cible.

Livrables :

- essais à plusieurs tailles intermédiaires choisies après G4 ;
- courbes de débit, mémoire, stabilité numérique et qualité ;
- test prolongé de checkpoint/reprise et récupération après interruption ;
- budget de ressources, fenêtre opérationnelle et critères d'arrêt anticipé ;
- révision documentée des risques et estimations.

**Gate G5 :** `GO` vers l'entraînement cible, révision explicite du plan ou arrêt. Une extrapolation non confirmée bloque le passage.

## J6 — Entraînement progressif du candidat CORE-700M

**Objectif :** entraîner la configuration approuvée sans perdre la traçabilité.

Livrables :

- configuration immuable et versionnée de l'expérience ;
- suivi des données, métriques, checkpoints, incidents et reprises ;
- évaluations régulières et critères d'arrêt appliqués ;
- modèle final accompagné de sa fiche, de ses limites et de sa provenance ;
- comparaison aux baselines miniatures et intermédiaires.

**Gate G6 :** les seuils de qualité, sécurité, stabilité et reproductibilité définis en amont sont atteints. Le simple achèvement du calcul ne suffit pas.

## J7 — Knowledge, RAG, inférence et MCP interne

**Objectif :** fournir une réponse locale citée, sûre et observable à partir des seules connaissances autorisées.

Livrables :

- service d'inférence CPU avec limites de ressources, file d'attente et arrêt propre ;
- index RAG versionné, citations et remontée de provenance jusqu'au paquet source ;
- MCP Knowledge interne avec contrats stricts, permissions minimales et aucune exposition Internet ;
- intégration de la chaîne d'ingestion validée à J2 sans lien retour automatique ;
- tests de panne, délai, annulation, injection d'instructions et indisponibilité de la collecte externe ;
- prototype d'interface interne avec authentification et historique selon la politique de données.

**Gate G7 :** le système fonctionne sans fournisseur externe, aucune action Internet n'est possible depuis IA-CORE et toute réponse fondée sur le RAG expose une provenance vérifiable.

## J8 — Profils d'agents et durcissement V1

**Objectif :** spécialiser progressivement le modèle partagé et préparer l'exploitation contrôlée.

Livrables :

- registre versionné des profils, missions, outils, données, mémoires et règles d'escalade ;
- premier lot restreint de profils couvrant les besoins prioritaires ;
- évaluations propres à chaque profil et tests de séparation des autorisations ;
- ordonnanceur compatible avec les contraintes CPU/NUMA ;
- tests d'isolation réseau A1, restauration A6, capacité A7 et runbooks A8 réussis ;
- plan d'extension vers environ 60 profils uniquement si les mesures le justifient.

**Gate G8 :** la V1 satisfait ses critères fonctionnels et les gates d'architecture nécessaires. Chaque profil ajoute une valeur mesurée et respecte le moindre privilège sans dupliquer le modèle.

## Après la V1

- intégration éventuelle du DL380p, précédée d'un nouvel inventaire et de benchmarks réseau ;
- génération d'images avec modèle de menace, données, licences et budget de calcul propres ;
- réplication éventuelle du service d'inférence pour la capacité, distincte du nombre de profils ;
- autres modalités ou accélérateurs, sans remettre en cause le chemin CPU de référence sauf nouvelle décision.

## Premiers tickets

1. **Clore le questionnaire de découverte et prioriser trois usages V1.**
2. **Inventorier le ML350/Proxmox, la topologie NUMA et le stockage actif.**
3. **Inventorier le RS3617xs+ : DSM, volumes, ACL, snapshots, réseau et restauration** ([protocole d'inventaire](architecture/synology-rs3617xs-inventory.md)).
4. **Cartographier le réseau et définir les tests prouvant l'isolement d'IA-CORE.**
5. **Rédiger l'ADR Research Gateway contre dépôt direct sur le Collector.**
6. **Spécifier la validation sémantique et les schémas de lignée/événements.**
7. **Définir le protocole du mini-benchmark CPU/NUMA et son format de résultats.**
8. **Décider corpus, tokenizer et politique du moteur d'embeddings RAG.**
9. **Définir la grille d'évaluation V1 et les critères d'arrêt.**

Chaque ticket doit inclure un critère d'acceptation vérifiable, les informations à expurger et le gate qu'il contribue à ouvrir.

