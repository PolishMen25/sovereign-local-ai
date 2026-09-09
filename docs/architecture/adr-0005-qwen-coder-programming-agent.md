# ADR-0005 — Agent de programmation Qwen2.5-Coder-7B séparé

- Statut : **ACCEPTÉ, acquisition et déploiement en attente**
- Date : 2026-09-09
- Autorité : propriétaire du projet

## Décision

La capacité de programmation utile ne sera pas recherchée dans CORE-30M ni
dans CORE-700M. CORE-30M conserve uniquement le rôle de validation du pipeline
d'entraînement CPU jusqu'à son budget de 600 M tokens. Aucun dialogue privé ne
sert à le rendre conversationnel et aucun entraînement long CORE-700M n'est
planifié.

L'agent de programmation est fondé sur
`Qwen/Qwen2.5-Coder-7B-Instruct-GGUF`, variante `Q4_K_M`, exécutée par
llama.cpp CPU. Le dépôt officiel déclare Apache-2.0 et fournit le fichier
`qwen2.5-coder-7b-instruct-q4_k_m.gguf` ; la licence est relue à la révision
figée lors de l'acquisition. La taille et le SHA-256 sont relevés seulement sur
la copie RAW complète, puis relus après chaque transfert.

## Isolement et exécution

L'agent, son terminal et ses conteneurs de travail sont placés sur un nœud
physique séparé du calcul CORE et de la passerelle. Ils ne reçoivent jamais
`pct`, `qm`, `pvesh`, ni un secret ou une identité d'administration du cluster.
Les outils restent bornés à des espaces de travail explicitement attribués et
toute action durable demeure soumise à confirmation humaine.

Une fois acquis, le runtime ne télécharge rien. Le démarrage est mesuré avec
llama.cpp b10537, vingt threads de génération liés à un socket et quarante
threads de préremplissage. Ces nombres sont une configuration de départ mesurée,
pas une promesse de débit transférable à un autre hôte.

L'historique d'une session agent est strictement additif : ni le prompt système,
ni les tours, ni les résultats d'outils déjà présents ne sont réécrits ou
réordonnés. Cette règle protège la réutilisation du cache KV. Une nouvelle
session peut être ouverte explicitement ; elle ne se substitue jamais
silencieusement à l'historique en cours.

## Acquisition et gates

1. relever la licence et la révision officielles ;
2. télécharger hors du domaine d'exécution vers RAW ;
3. calculer SHA-256 et taille, puis relire la copie RAW ;
4. compléter le lock candidat et vérifier ses champs ;
5. promouvoir explicitement vers le stockage de modèles ;
6. relire l'empreinte côté runtime avant le premier chargement.

Une absence d'empreinte, une divergence de taille ou de licence, ou une
promotion non enregistrée bloque le démarrage. Aucun modèle, poids ou détail
d'exploitation ne rejoint Git.

## Retour arrière

Arrêter le service d'agent et conserver RAW et les reçus de provenance. Ni le
pipeline CORE ni la passerelle existante ne dépendent de cet agent avant son
activation explicite.
