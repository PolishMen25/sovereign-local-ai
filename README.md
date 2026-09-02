# Sovereign Local AI

Socle d'une intelligence artificielle locale, souveraine et **CPU-only**, construite progressivement sous contrôle du projet. La V1 vise un modèle de langage créé localement dans la classe 50–100 millions de paramètres, un RAG traçable, des agents logiques et une séparation stricte entre ingestion externe et connaissances internes, sans donner d'accès Internet à l'IA interne. Deux services MCP distincts constituent l'option candidate actuelle, encore soumise à audit.

> État : **phase 0 — découverte et validation de l'architecture**. Ce dépôt pose les contraintes, les contrats et les gates de décision. Il ne prétend pas encore fournir une plateforme de production.

> **Utilisation actuelle : un chat tiers BOOTSTRAP fonctionne localement en
> CLI CPU.** Il fournit des réponses réelles pendant la construction de CORE,
> mais n'est ni CORE-MINI ni CORE-700M. CORE-MINI valide toujours le chemin
> d'entraînement et CORE-700M n'a pas encore de poids linguistiques. Voir la
> matrice [Capacités réellement disponibles](docs/project/current-capabilities.md).

## Invariants déjà décidés

- aucun GPU, CUDA, ROCm ou TPU dans le chemin V1 ;
- calcul principal sur le **HPE ProLiant ML350 Gen9**, CPU-only, sous Proxmox ; l'inventaire mesuré et les divergences avec la fiche initiale restent suivis séparément ;
- **Synology RS3617xs+** : stockage long terme, archives, datasets, modèles validés, checkpoints importants, connaissances et sauvegardes — pas d'entraînement principal ;
- **DL380p Gen8 exclu de la V1** ;
- la future zone **IA-CORE ne doit avoir aucun accès Internet direct** ; le blocage réseau et son test négatif restent un gate obligatoire, distinct des refus applicatifs déjà codés ;
- toute donnée externe est non fiable et entre par un collecteur, une quarantaine, une validation, puis un import contrôlé ;
- une recherche brute n'est jamais automatiquement une connaissance validée ;
- les originaux RAW et leur provenance sont conservés ;
- environ 60 agents sont des profils logiques partageant un petit nombre de moteurs, et non 60 copies du modèle ;
- aucune durée d'entraînement ne sera annoncée avant benchmark sur le matériel réel.

Le registre complet se trouve dans [docs/project/decisions.md](docs/project/decisions.md).

## Architecture cible candidate — pas l'état actuel

Le schéma suivant décrit la destination. Les blocs ne sont pas tous déployés ou
reliés ; la page des capacités indique l'état réel de chacun.

```text
Internet / fournisseurs externes
              |
              v
     RESEARCH-GATEWAY (DMZ)
       appels API contrôlés
              |
              v
     MCP COLLECTOR EXTERNE
      dépôt à privilèges minimes
              |
              v
    QUARANTAINE + VALIDATION
              |
       import autorisé
              v
  STOCKAGE / CONNAISSANCES VALIDÉES
       Synology RS3617xs+
              |
        réseau IA privé
              v
           IA-CORE
       HPE ML350 Gen9
  modèle + RAG + orchestrateur
              |
              v
      MCP KNOWLEDGE INTERNE

IA-CORE -X-> Internet
Internet -X-> MCP Knowledge interne
Collector externe -X-> lecture des données privées
```

L'option Research Gateway est la direction recommandée pour l'étude, car elle centralise les clés, les coûts, les fournisseurs et l'audit. Elle reste une **décision provisoire** jusqu'à validation de la topologie, des usages et des politiques de sortie.

## Cible CORE-700M

Le candidat principal est un Transformer decoder-only de **691 160 320 paramètres entraînables** : vocabulaire 32 000, dimension 1 280, 32 blocs, 20 têtes, MLP SwiGLU 3 584, RoPE, RMSNorm, matrice d'embedding de tokens et tête de sortie liées, sans biais. CORE-80M reste une référence historique, sans entraînement long prévu.

Ce nombre est exact pour cette définition, mais aucun poids linguistique n'existe encore. Le contexte candidat est 2 048 tokens ; le corpus exact, le tokenizer, la précision et les seuils d'évaluation restent soumis aux gates. Voir [docs/model/core-700m.md](docs/model/core-700m.md) et vérifier le calcul avec :

Sous Windows :

```powershell
py -3 -B tools/count_core_parameters.py
```

Sous Linux :

```bash
python3 -B tools/count_core_parameters.py
```

## Structure du dépôt

```text
.
├── AGENTS.md                         règles de travail pour Codex
├── SECURITY.md                       signalement et principes de sécurité
├── configs/models/                   configurations candidates, non validées
├── docs/
│   ├── architecture/                 architecture logique et déploiement
│   ├── security/                     menaces, frontières et gates
│   ├── mcp/                          collecteur externe et MCP interne
│   ├── data/                         provenance et cycle de vie
│   ├── model/                        définitions CORE-MINI, CORE-80M et CORE-700M
│   ├── agents/                       agents logiques et permissions
│   ├── project/                      décisions et questionnaire de découverte
│   └── ROADMAP.md                    phases et critères de sortie
├── schemas/                          contrats de données versionnés
├── services/                         frontières des futurs services
├── infra/                            futur déploiement, après validation
├── tools/                            outils locaux sans dépendances lourdes
└── tests/                            vérifications du socle
```

## Commencer correctement

1. Lire [AGENTS.md](AGENTS.md) et le [registre des décisions](docs/project/decisions.md).
   Pour reprendre avec un autre agent, consulter aussi le
   [handoff Claude Code](docs/project/claude-code-handoff.md).
2. Compléter uniquement les informations encore ouvertes dans le [questionnaire de découverte](docs/project/discovery-questionnaire.md).
3. Valider la topologie réseau, les flux, le stockage, l'identité, les sauvegardes et les politiques de données.
4. Mesurer le ML350 : CPU, RAM, NUMA, disque, threads et tokens/seconde sur un mini-modèle.
5. Produire les ADR et figer une pile minimale avant toute implémentation de production.

Le projet n'adopte pas encore de base vectorielle, de framework Web définitif,
de système de queue ou de moteur d'embeddings pour le RAG. SMB est utilisé pour
les essais de stockage actuels ; son rôle définitif reste soumis à décision.
Les options devront être comparées sur les contraintes réelles, puis consignées
dans le registre.

## Principes de sécurité

- deny-by-default entre les zones ;
- aucun secret dans Git, les prompts, les archives de recherche ou les logs ;
- formats d'entrée explicitement autorisés, limites de taille et validation stricte ;
- contenu externe traité comme données, jamais comme instructions ;
- RAW immuable et promotion vers `VALIDATED` traçable ;
- outils MCP à portée minimale, sans fichier arbitraire, shell ou exploration réseau ;
- approbation explicite pour toute donnée autorisée à sortir ;
- tests des flux interdits, pas seulement des flux autorisés.

Consulter [SECURITY.md](SECURITY.md) et [docs/security/threat-model.md](docs/security/threat-model.md).

## Roadmap

La progression suit des gates mesurables : découverte, architecture sécurisée, ingestion contrôlée, corpus/tokenizer/RAG, mini-modèle et benchmark CPU/NUMA, pilote de montée en échelle, entraînement progressif CORE-700M, Knowledge/RAG/MCP interne, puis profils d'agents et durcissement. Des prototypes de jalons ultérieurs peuvent exister sans que leur gate soit franchi. La génération d'images et le DL380p sont hors périmètre V1.

Voir [docs/ROADMAP.md](docs/ROADMAP.md).

## Licence

Aucune licence n'est ajoutée tant que le propriétaire n'a pas choisi les droits
de réutilisation. L'absence de licence signifie qu'aucun droit de réutilisation
n'est accordé implicitement ; ce choix reste à traiter pendant la découverte.
