# Registre initial des décisions

Dernière mise à jour : 2026-08-25. Ce registre distingue les décisions confirmées des orientations provisoires. Une orientation ne devient ferme qu'après validation explicite du propriétaire et, pour un choix structurant, création d'un ADR.

## Décisions confirmées

| ID | Décision | Conséquence V1 |
|---|---|---|
| D-001 | Le projet est CPU-only. | Aucun composant obligatoire ne dépend d'un GPU, CUDA, ROCm ou TPU. |
| D-002 | Le calcul principal se fait sur le HPE ML350 Gen9. | Entraînement, benchmarks et inférence principale y sont conçus et mesurés. |
| D-003 | Configuration connue du ML350 : 2 × E5-2699 v4, 44C/88T, 88 Go, ~12 To, Proxmox. | NUMA dual-socket et marge pour l'hyperviseur doivent être pris en compte. |
| D-004 | Le Synology RS3617xs+ est le stockage long terme ; configuration déclarée : 32 Go de RAM, ~8,1 To utiles, ~1,1 To utilisés et ~7 To libres. | RAW, datasets, connaissances, modèles validés, checkpoints importants, audit et sauvegardes y résident selon une arborescence/ACL à valider. Capacités et état doivent être vérifiés pendant l'inventaire. |
| D-005 | Le RS3617xs+ ne fait pas l'entraînement principal. | Les datasets actifs et checkpoints temporaires pourront être placés sur stockage local du ML350. |
| D-006 | Le DL380p Gen8 est exclu de la V1. | Aucun service, capacité ou disponibilité V1 ne dépend de cette machine. |
| D-007 | IA-CORE n'a aucun accès Internet direct. | Le contrôle doit être imposé au réseau, y compris DNS et routes, et testé. |
| D-008 | Les connaissances externes entrent par un flux contrôlé. | Collecte, quarantaine, validation et promotion précèdent l'usage interne. |
| D-009 | Le collecteur externe ne permet aucune lecture interne. | API/MCP minimal de dépôt ; pas de recherche privée, mémoire, modèles, fichiers arbitraires ou exploration réseau. |
| D-010 | RAW et connaissance validée sont séparés. | États distincts et aucune confiance automatique accordée aux réponses externes. |
| D-011 | L'original RAW est conservé avec sa provenance. | Une transformation ne remplace pas l'original ; empreinte et version de schéma sont requises. |
| D-012 | Toute donnée Internet est non fiable. | Défenses contre pièces jointes malveillantes, HTML actif et prompt injection indirecte. |
| D-013 | Le modèle principal est créé dans le projet. | Tokenizer, architecture, dataset, entraînement, évaluation et inférence sont sous contrôle local. |
| D-014 | La première cible est comprise entre 50M et 100M de paramètres. | `CORE-80M` sert de candidat de travail avec comptage exact. |
| D-015 | Les performances et durées doivent être mesurées. | Mini-modèle et benchmark matériel obligatoires avant entraînement long ou estimation. |
| D-016 | Environ 60 agents sont des profils logiques. | Modèles partagés, registry, permissions, mémoire et outils par profil ; pas 60 copies en RAM. |
| D-017 | Le RAG porte la connaissance évolutive. | Les nouvelles recherches ne déclenchent pas automatiquement un réentraînement des poids. |
| D-018 | La génération d'images est ultérieure. | Hors périmètre V1 ; aucun compromis V1 n'est fait pour elle. |
| D-019 | La V1 est d'abord un assistant personnel pour le propriétaire du projet. | Une seule session interactive est la cible initiale ; au-delà, le système met en file ou refuse jusqu'au benchmark de capacité. |
| D-020 | Les trois usages V1 prioritaires sont : organisation personnelle, développement logiciel et conseil d'infrastructure locale. | Corpus, RAG, profils logiques et évaluations sont conçus en priorité pour ces usages. Les scénarios, limites et critères sont versionnés dans `docs/project/v1-use-cases.md`. |
| D-021 | L'assistant doit être force de proposition, sans autonomie de modification. | Il explicite hypothèses, sources, risques, options et vérifications ; toute action durable, sortie de données ou modification d'infrastructure exige une confirmation humaine. |
| D-022 | La connaissance de l'infrastructure locale est fournie par des inventaires et documents approuvés. | Aucune découverte réseau, exécution de commande, accès aux secrets ou modification de l'infrastructure n'est permise par défaut. |
| D-023 | Le stockage V1 suit une stratégie hybride : capacité locale Proxmox pour le calcul actif et le temporaire ; Synology RS3617xs+ pour RAW, connaissances, modèles, checkpoints retenus et sauvegardes. | Le stockage local n'est pas la copie durable unique ; les flux vers le Synology restent restreints, mesurés et sauvegardés. Aucun disque n'est initialisé sans procédure approuvée. |
| D-024 | Un modèle tiers Qwen2.5-1.5B-Instruct GGUF est autorisé comme chat BOOTSTRAP temporaire, distinct de CORE, en CLI locale CPU uniquement. | Acquisition et empreintes verrouillées ; aucun service persistant, outil, RAG ou téléchargement à l'exécution. Cette exception ne remplace pas CORE-80M et ne valide aucun gate d'entraînement. |

## Orientations provisoires

| ID | Orientation | Validation attendue |
|---|---|---|
| P-001 | Préférer une Research Gateway qui appelle les API externes puis dépose les résultats. | Comparaison formelle avec un dépôt MCP direct, politique de sortie, fournisseurs et budget. |
| P-002 | Candidat : deux services MCP séparés, Collector externe et Knowledge interne. Invariant ferme : aucune identité, aucun droit de lecture et aucun processus de confiance partagé entre ingress externe et consultation interne. | Topologie réseau, authentification, protocoles, nombre exact de services et disponibilité. |
| P-003 | Candidat CORE : decoder-only, 81 444 480 paramètres. | Langues, corpus, tokenizer, contexte, benchmark miniature et objectifs de qualité. |
| P-004 | Architecture hybride : modèle principal créé de zéro + RAG + éventuels petits modèles spécialisés. | Politique autorisant ou non un moteur d'embeddings RAG et un reranker pré-entraînés, séparés de CORE-80M. |
| P-005 | Copier le dataset actif sur un stockage local rapide du ML350. | Inventaire réel des contrôleurs, disques, volumes et débits. |

## Décisions ouvertes majeures

- langues et proportions du corpus, code source, logs et vocabulaire métier ;
- droit ou interdiction d'utiliser un moteur d'embeddings RAG et un reranker pré-entraînés, distincts de CORE ;
- pile logicielle des services, base relationnelle, index vectoriel et file de tâches ;
- découpage Proxmox en VM/LXC, allocations, NUMA, stockage local et sauvegardes ;
- topologie physique, VLAN, pare-feu, DNS, NTP et mécanisme d'import entre zones ;
- DSM, volumes, système de fichiers, ACL, snapshots et protocole NAS ;
- fournisseurs externes, gestion des clés, budgets, rétention et conditions contractuelles ;
- classification des données, approbation des sorties, rôles humains et durée de conservation ;
- utilisateurs, authentification et exposition de l'interface Web interne ;
- RPO/RTO, stratégie 3-2-1 et restauration testée ;
- licence du dépôt et politique de contribution.

## Procédure de modification

1. Lier la décision à une issue et rassembler les mesures nécessaires.
2. Pour un choix structurant, rédiger un ADR avec options, critères, décision et conséquences.
3. Obtenir la validation explicite du propriétaire.
4. Déplacer l'élément vers les décisions confirmées et mettre à jour les documents concernés.
5. Ne jamais réécrire l'historique : conserver les décisions remplacées avec la mention `SUPERSEDED` et leur successeur.

