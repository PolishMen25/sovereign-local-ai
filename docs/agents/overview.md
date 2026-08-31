# Agents logiques — vue d'ensemble

## Principe directeur

La cible d'environ 60 agents désigne des **profils logiques spécialisés partageant le même modèle**, et non 60 modèles chargés en mémoire ni 60 entraînements indépendants.

Un profil combine une mission, des instructions versionnées, un périmètre de données, une liste d'outils autorisés, une politique de mémoire, des limites de ressources et des tests propres. Le service d'inférence CORE est mutualisé. Une éventuelle réplication technique de ce service pour la capacité serait une décision d'exploitation distincte, fondée sur des mesures ; elle ne découle pas du nombre de profils.

## Architecture conceptuelle

```text
Utilisateur / service autorisé
            |
            v
  Authentification et politique
            |
            v
       Orchestrateur
       /    |      \
 profil  contexte  mémoire autorisée
       \    |      /
            v
   Service de modèle partagé
            |
       demande d'outil
            v
 Passerelle MCP et contrôles
            |
       outil interne autorisé
            |
            v
 Validation, réponse et audit
```

Les profils ne contiennent pas de secrets. Ils référencent des capacités ; les justificatifs d'accès restent dans un gestionnaire de secrets et sont injectés uniquement au point d'usage autorisé.

## Composants

### Registre de profils

Chaque profil devrait déclarer au minimum :

- identifiant stable et version ;
- mission et résultats attendus ;
- limites explicites et cas d'escalade humaine ;
- version des instructions système ;
- outils autorisés et opérations interdites ;
- périmètres de données en lecture et en écriture ;
- politique de mémoire et durée de conservation ;
- schéma de sortie, limites de contexte et budget de ressources ;
- suite d'évaluation et seuils de qualité ;
- propriétaire fonctionnel et historique des changements.

Le registre initial est maintenant matérialisé dans
[`configs/agents/registry.json`](../../configs/agents/registry.json) et validé
par [`schemas/agent-profile-registry.schema.json`](../../schemas/agent-profile-registry.schema.json).
Il contient 60 profils logiques en statut `draft` : ils partagent le modèle,
n'écrivent pas en mémoire et restent en mode proposition tant que les gates
d'architecture, d'évaluation et d'identité ne sont pas franchis. Toute
activation devra être un changement versionné accompagné de tests et d'une
revue humaine.

### Orchestrateur

L'orchestrateur sélectionne le profil, assemble uniquement le contexte autorisé, applique les limites de ressources, met les requêtes en file d'attente et valide le résultat. Il ne doit pas accorder un outil ou une donnée simplement parce qu'un texte généré le réclame.

Sur CPU, l'ordonnancement doit protéger la latence et la mémoire : limite de concurrence, priorité explicite, annulation, délais maximums et contre-pression. Les réglages seront dérivés des benchmarks du ML350 bi-socket NUMA.

### Service de modèle partagé

Le modèle est chargé une fois par instance de service et reçoit le profil comme configuration de requête. L'état propre à une mission ne doit pas modifier les poids partagés. L'adaptation par fine-tuning, adapters ou routage de modèles reste une décision future et ne doit pas être supposée dans la V1.

Le candidat actuel est documenté dans [CORE-80M](../model/core-80m.md). Son architecture demeure provisoire jusqu'aux gates de benchmark et de données.

### Passerelle MCP

Toute utilisation d'outil passe par des contrats MCP versionnés, des entrées validées et une autorisation calculée côté serveur. Les profils reçoivent le moindre privilège : lecture, écriture et action sont des capacités distinctes.

Les opérations sensibles doivent pouvoir exiger une confirmation humaine. Les agents d'IA-CORE n'appellent aucun outil externe : les recherches Internet sont réalisées séparément dans la zone Research Gateway/Collector, puis importées par le pipeline contrôlé. Les appels aux outils internes ont des délais, des limites, une politique de reprise sans double effet et un journal d'audit expurgé des secrets. Une réponse issue d'un outil reste une donnée non fiable à valider, pas une instruction supérieure.

### Mémoire et connaissances

La mémoire doit rester séparée du modèle et segmentée par portée, par exemple session, projet et base approuvée. L'ingestion automatique de toutes les conversations n'est pas un comportement par défaut.

Chaque élément conservé doit pouvoir porter sa provenance, sa date, son périmètre d'accès, sa durée de rétention et, lorsque nécessaire, un moyen de correction ou suppression. Le stockage, la recherche et la stratégie du moteur d'embeddings RAG pour cette mémoire restent à sélectionner.

## Cycle d'une requête

1. authentifier l'appelant et déterminer son périmètre ;
2. sélectionner un profil autorisé et sa version ;
3. récupérer seulement le contexte et la mémoire permis ;
4. exécuter l'inférence sur le service de modèle partagé ;
5. intercepter toute demande d'outil et appliquer schéma, politique et confirmation ;
6. valider et filtrer le résultat avant restitution ;
7. enregistrer les métadonnées d'audit sans exposer de secret ni de contenu sensible superflu.

Un identifiant de corrélation doit permettre de relier ces étapes sans confondre identité utilisateur, profil logique et instance technique du modèle.

## Déploiement progressif

Le nombre « environ 60 » est une cible de couverture fonctionnelle, pas un objectif de lancement simultané.

1. commencer par un petit lot de profils prioritaires ;
2. mesurer leur exactitude, leur utilité, leur coût CPU et leurs incidents ;
3. ajouter un profil seulement si sa mission et ses autorisations sont distinctes ;
4. fusionner ou retirer les profils redondants ;
5. tendre vers environ 60 profils uniquement si les besoins et les évaluations le justifient.

Des familles possibles — sans figer leur nombre — incluent coordination, développement, données, entraînement, évaluation, sécurité, exploitation, recherche, documentation et gouvernance.

## Invariants de sécurité

- refus par défaut pour les outils et les données ;
- aucune élévation de privilège décidée par le modèle ;
- séparation entre contenu non fiable, instructions du profil et politique serveur ;
- secrets absents des prompts, sorties et journaux ;
- aucune action externe depuis IA-CORE ; toute préparation d'une demande sortante suit un workflow distinct de déclassification et d'approbation hors du chemin automatique ;
- mémoire isolée entre périmètres ;
- validation des entrées et sorties de chaque outil ;
- possibilité d'annuler, de limiter et de désactiver immédiatement un profil ;
- fonctionnement local autonome lorsque les fournisseurs externes sont indisponibles.

## Décisions encore ouvertes

- format et moteur du registre de profils ;
- technologie d'orchestration et politique de planification CPU ;
- nombre de profils du premier lot et composition finale ;
- longueur de contexte par profil et stratégie de résumé ;
- stockage de mémoire, moteur de recherche et stratégie du moteur d'embeddings RAG ;
- seuils imposant une confirmation humaine ;
- niveaux de concurrence et éventuelle réplication du service partagé ;
- mécanisme d'évaluation continue et procédure de retrait d'un profil ;
- éventuelles adaptations spécialisées du modèle après la V1.

## Gate d'acceptation V1

Un premier lot de profils peut entrer en V1 lorsque chacun possède une mission non redondante, un périmètre de données, une liste d'outils minimale, des tests de sécurité, des seuils de qualité et une règle d'escalade. Les tests doivent démontrer qu'un profil ne peut ni accéder aux capacités d'un autre ni contourner la passerelle MCP.

L'extension vers environ 60 profils est conditionnée aux mesures de la [roadmap](../ROADMAP.md) ; elle n'est ni un prérequis de la V1 ni une raison de dupliquer le modèle.

