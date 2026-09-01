# Sovereign Local AI

Socle d'une intelligence artificielle locale, souveraine et **CPU-only**, construite progressivement sous contrôle du projet. La V1 vise un modèle de langage créé localement dans la classe 50–100 millions de paramètres, un RAG traçable, des agents logiques et une séparation stricte entre ingestion externe et connaissances internes, sans donner d'accès Internet à l'IA interne. Deux services MCP distincts constituent l'option candidate actuelle, encore soumise à audit.

> État : **phase 0 — découverte et validation de l'architecture**. Ce dépôt pose les contraintes, les contrats et les gates de décision. Il ne prétend pas encore fournir une plateforme de production.

## Invariants déjà décidés

- aucun GPU, CUDA, ROCm ou TPU dans le chemin V1 ;
- calcul principal sur le **HPE ProLiant ML350 Gen9** : 2 × Xeon E5-2698 v4, 40 cœurs physiques / 80 threads, 88 Go de RAM, environ 12 To, sous Proxmox ;
- **Synology RS3617xs+** : stockage long terme, archives, datasets, modèles validés, checkpoints importants, connaissances et sauvegardes — pas d'entraînement principal ;
- **DL380p Gen8 exclu de la V1** ;
- la zone **IA-CORE n'a aucun accès Internet direct**, blocage imposé au niveau réseau et pas seulement par l'application ;
- toute donnée externe est non fiable et entre par un collecteur, une quarantaine, une validation, puis un import contrôlé ;
- une recherche brute n'est jamais automatiquement une connaissance validée ;
- les originaux RAW et leur provenance sont conservés ;
- environ 60 agents sont des profils logiques partageant un petit nombre de moteurs, et non 60 copies du modèle ;
- aucune durée d'entraînement ne sera annoncée avant benchmark sur le matériel réel.

Le registre complet se trouve dans [docs/project/decisions.md](docs/project/decisions.md).

## Architecture de principe candidate

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

## Cible CORE-80M

Le premier candidat vérifiable est un Transformer decoder-only de **81 444 480 paramètres entraînables** : vocabulaire 32 000, dimension 640, 12 blocs, 10 têtes, MLP SwiGLU 1 792, RoPE, RMSNorm, matrice d'embedding de tokens et tête de sortie liées, sans biais.

Ce nombre est exact pour cette définition, mais l'architecture est encore un candidat. Le tokenizer, les langues, la longueur de contexte, le dataset et la politique du moteur d'embeddings du RAG doivent être décidés après l'audit. Voir [docs/model/core-80m.md](docs/model/core-80m.md) et vérifier le calcul avec :

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
│   ├── model/                        définition de CORE-80M
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
2. Compléter uniquement les informations encore ouvertes dans le [questionnaire de découverte](docs/project/discovery-questionnaire.md).
3. Valider la topologie réseau, les flux, le stockage, l'identité, les sauvegardes et les politiques de données.
4. Mesurer le ML350 : CPU, RAM, NUMA, disque, threads et tokens/seconde sur un mini-modèle.
5. Produire les ADR et figer une pile minimale avant toute implémentation de production.

Le projet n'adopte pas encore de base vectorielle, de framework Web, de système de queue, de protocole de partage NAS ou de moteur d'embeddings pour le RAG. Les options devront être comparées sur les contraintes réelles, puis consignées dans le registre.

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

La progression suit des gates mesurables : découverte, architecture sécurisée, ingestion contrôlée, corpus/tokenizer/RAG, mini-modèle et benchmark CPU/NUMA, pilote de montée en échelle, entraînement CORE-80M, Knowledge/RAG/MCP interne, puis profils d'agents et durcissement. La génération d'images et le DL380p sont hors périmètre V1.

Voir [docs/ROADMAP.md](docs/ROADMAP.md).

## Licence

Aucune licence n'est ajoutée tant que le propriétaire n'a pas choisi les droits de réutilisation. Le dépôt étant privé, l'absence de licence doit rester explicite et sera traitée pendant la découverte.

