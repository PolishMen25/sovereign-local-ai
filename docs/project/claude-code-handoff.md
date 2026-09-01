# Reprise Claude Code

Dernière mise à jour : 2026-09-01.

Ce document est le point de reprise public et expurgé. Il ne contient ni
adresse privée, compte, secret, chemin d'administration ou inventaire détaillé.
Lire d'abord `AGENTS.md`, `docs/project/decisions.md`,
`docs/project/current-capabilities.md`, `docs/architecture/overview.md` et
`docs/security/threat-model.md`.

## Branche de travail

- dépôt : `PolishMen25/sovereign-local-ai` ;
- branche d'intégration : `codex/cpu-offline-harness` ;
- phase : découverte et prototypes bornés, aucun service CORE de production ;
- le dossier de travail d'un agent ne doit pas être supposé synchronisé : lire
  le HEAD distant et vérifier l'état Git avant toute modification.

## Invariants à préserver

- CPU-only, sans CUDA, ROCm, GPU ou téléchargement à l'exécution ;
- IA-CORE sans accès Internet ;
- BOOTSTRAP est un modèle tiers temporaire, jamais CORE ;
- RAW, quarantaine et VALIDATED restent séparés ;
- aucune promotion automatique de contenu externe ;
- Collector externe write-only, MCP Knowledge interne séparé ;
- aucun shell, chemin arbitraire ou accès réseau arbitraire via MCP ;
- les 60 agents sont des profils logiques partagés et restent désactivés tant
  que leurs gates ne sont pas franchis ;
- aucun secret, poids, checkpoint, corpus réel ou détail interne dans Git.

## Ce qui fonctionne réellement

- chat BOOTSTRAP Qwen2.5-1.5B-Instruct en CLI locale CPU avec llama.cpp ;
- instanciation CPU et comptage exact du candidat CORE-80M, sans poids ;
- entraînement synthétique, checkpoint atomique et reprise de CORE-MINI ;
- prototype MCP Knowledge `stdio` sur trois notices synthétiques ;
- Collector de conversations write-only vers RAW ;
- stockage chiffré validé avec des données synthétiques ;
- registre de 60 profils, orchestrateur, autorisations et interface Web en mode
  préparation fail-closed seulement.

## Tranche technique intégrée le 2026-09-01

- définition commune du decoder dans `services/inference/model.py`, partagée
  entre entraînement et future inférence, strictement CPU-only ;
- tokenizer Byte-BPE expérimental `0.2.0` avec NFC commun, fusions ordonnées,
  IDs spéciaux fixes, état runtime immuable, encode/decode et limites ;
- manifeste corpus `0.2.0` avec taille, empreinte et compte propres à chaque
  split ;
- chargeur `authorized_text_bundle.py` limité au split `train`, avec lignée
  contenu-free du corpus et du tokenizer ;
- producteur du tokenizer lié à l'empreinte exacte du split `train` ;
- vérificateur offline d'anciens checkpoints, chargement
  `weights_only=True`, CPU, modèle/optimiseur stricts et une reprise bornée ;
- Collector forcé sur loopback et relais Codex sans URL d'installation codée
  en dur ;
- configuration Windows personnelle exclue, exemple générique versionné.

## Ce qui ne fonctionne pas encore

- aucun poids linguistique CORE utile ;
- aucun tokenizer ou corpus final approuvé ;
- aucun runtime de génération CORE actif ;
- `/v1/chat` reste volontairement en HTTP 503 ;
- aucun RAG vectoriel, agent actif, RBAC de production ou interface finale ;
- l'isolation réseau complète et les restaurations de production restent des
  gates à prouver.

## Ordre de reprise recommandé

1. vérifier la suite de tests locale et Linux, sans télécharger de dépendance ;
2. confirmer la compatibilité d'un checkpoint CORE-MINI historique sur le
   nœud CPU avec le vérificateur offline ;
3. définir puis approuver les sources, licences, langues et exclusions du
   corpus ;
4. produire un tokenizer expérimental depuis le seul split `train`, évaluer sa
   qualité, puis faire approuver séparément son SHA-256 exact ;
5. ajouter un mode d'entraînement `authorized-text` explicite, sans modifier le
   mode synthétique et avec lignée stricte dans le checkpoint ;
6. exporter un bundle d'inférence borné et vérifié ;
7. seulement après les gates, raccorder génération CORE, RAG, authentification,
   interface et profils d'agents.

## Refus attendus

Un changement doit être refusé s'il introduit un téléchargement depuis CORE,
un build GPU, un tokenizer auto-approuvé, un corpus autre que `train`, une
promotion RAW automatique, un endpoint MCP générique, un secret dans Git ou une
revendication de capacité non mesurée.
