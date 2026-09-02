# Reprise Claude Code

Dernière mise à jour : 2026-09-02.

Ce document est le point de reprise public et expurgé. Il ne contient ni
adresse privée, compte, secret, chemin d'administration ou inventaire détaillé.
Lire d'abord `AGENTS.md`, `docs/project/decisions.md`,
`docs/project/current-capabilities.md`, `docs/architecture/overview.md` et
`docs/security/threat-model.md`.

## Branche de travail

- dépôt : `PolishMen25/sovereign-local-ai` ;
- branche d'intégration : `codex/cpu-offline-harness` ;
- phase : découverte et prototypes bornés, aucun service n'est qualifié de
  production ;
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
- le runner NUMA n'applique jamais un placement et ne publie jamais le contrat
  privé, l'identité de la machine, les listes CPU/NUMA, une commande ou un
  chemin ;
- les 60 agents sont des profils logiques partagés et restent désactivés tant
  que leurs gates ne sont pas franchis ;
- aucun secret, poids, checkpoint, corpus réel ou détail interne dans Git.

## Ce qui fonctionne réellement

- chat BOOTSTRAP Qwen2.5-1.5B-Instruct en CLI locale CPU ; la passerelle Web du
  projet l'appelle sur la boucle locale et est exposée en HTTPS privé dans le
  tailnet, sans outil, agent ou proxy MCP ;
- instanciation CPU historique et comptage exact de CORE-80M, conservé comme
  référence sans poids ;
- entraînement synthétique strict de CORE-MINI sur 20 étapes, checkpoint
  atomique puis reprise de 5 étapes jusqu'à l'étape 25 ; la compatibilité d'un
  ancien checkpoint historique reste à confirmer séparément sur Linux ;
- runner de preuve CORE-MINI NUMA implémenté avec contrat de placement externe,
  archive source et runtime offline vérifiés, contrôle INET flux/datagrammes
  fail-closed et répétitions bornées ; le préflight réel a réussi, puis le
  premier run a révélé un doublon d'option désormais corrigé et testé
  localement. Les preuves A/B restent à rejouer après redéploiement ;
- prototype MCP Knowledge `stdio` sur trois notices synthétiques ;
- Collector de conversations write-only vers RAW ;
- stockage chiffré validé avec des données synthétiques ;
- passerelle Web authentifiée déployée avec Argon2id, CSRF, `/v1/chat` réel vers
  BOOTSTRAP et mémoire SQLite locale exportable/supprimable ; première
  configuration propriétaire encore requise ;
- registre de 60 profils, orchestrateur et autorisations en préparation
  fail-closed seulement.

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
- mode `authorized-text` explicite dans `train_core_mini.py`, sans repli vers le
  générateur synthétique : il exige le manifeste autorisé, le JSONL `train` et
  le tokenizer correspondant, puis refuse un vocabulaire différent de celui du
  modèle ;
- contrat d'entraînement `0.2.0` sans contenu brut dans le checkpoint et journal
  de métriques strict lié à son SHA-256, avec étapes contiguës ; le checkpoint
  conserve l'empreinte du préfixe exact du journal exigé à la reprise ;
- chargement commun de la configuration CORE-MINI depuis une seule copie
  bornée : JSON strict, architecture et comptage exacts, SHA-256 calculé sur les
  mêmes octets ; parseurs CLI publics qui n'exposent pas les chemins reçus ;
- primitives partagées de checkpoint dans `services/inference/checkpoint.py` :
  chargement CPU `weights_only=True`, clés, formes, types et état AdamW
  stricts avant reprise, avec refus des strides, stockages et alias anormaux ;
- vérificateur offline des checkpoints historiques construit sur ces mêmes
  primitives ;
- summarizer de métriques `core-mini-metrics-summary.v2` : journal strict et
  borné, empreinte exacte des octets source, chauffe explicite, moyenne,
  médiane, écart-type de population, MAD et débit ; cette capacité porte sur
  un journal commençant à l'étape 1, ne recompose pas une reprise et ne ferme
  pas le gate du benchmark NUMA ;
- runner `tools/core_mini_numa_benchmark.py` Linux-only : CLI obligatoire
  `--run-root`, `--placement-contract`, `--benchmark-session-id` et
  `--source-archive`, paramètres bornés, configuration CORE-MINI fixe et contrat
  privé conforme à `schemas/core-mini-private-placement.schema.json` ;
- vérification exacte de l'affinité et de la politique mémoire dans chaque
  phase enfant, refus préalable des sockets flux/datagrammes `AF_INET`/`AF_INET6`,
  sonde enfant CPU-only, 3 à 10
  répétitions fraîches, résumé relu et checkpoint repris une étape sans
  modification ;
- artefact public fermé par `schemas/core-mini-numa-evidence.schema.json`, avec
  empreintes exactes et statistiques inter-répétitions, sans détail matériel,
  commande ou chemin ; son contrat `0.2.0` lie séparément les locks PyTorch et
  NumPy à l'observation réelle ; le commit est une déclaration au format strict,
  pas une lecture de Git par le runner ;
- candidat CORE-700M versionné avec comptage exact de 691 160 320 paramètres,
  CORE-80M conservé comme référence historique ;
- passerelle Web mono-utilisateur, authentification Argon2id, sessions, CSRF,
  mémoire conversationnelle masquée, export et suppression explicite ;
- catalogue RAG hybride local SQLite/FTS5/vecteurs et capacités MCP étroites de
  recherche/provenance, testés mais pas encore alimentés ni raccordés au chat ;
- Collector forcé sur loopback et relais Codex sans URL d'installation codée
  en dur ;
- relais Codex refusant toute redirection HTTP et validant le payload en file,
  l'état, l'identifiant et le SHA-256 du reçu avant d'enregistrer ce reçu puis
  de supprimer la file ;
- configuration Windows personnelle exclue, exemple générique versionné.

## Ce qui ne fonctionne pas encore

- aucun poids linguistique CORE utile ;
- aucun tokenizer ou corpus final approuvé ;
- aucun entraînement `authorized-text` n'a été exécuté de bout en bout avec
  PyTorch et un bundle réel approuvé : le chemin est implémenté et couvert par
  des tests unitaires et structurels, pas autorisé à produire des poids ;
- aucun runtime de génération CORE actif ;
- `/v1/chat` appelle réellement BOOTSTRAP et nomme le moteur ; la réponse reste
  JSON non progressive et ne doit pas être confondue avec CORE ;
- aucun catalogue RAG réel, agent actif, RBAC final ou streaming de réponse ;
- aucune preuve répétée du runner NUMA n'a encore été acceptée sur le nœud CPU,
  aucun comparateur multi-placement n'est implémenté et G4 reste ouvert ;
- l'isolation réseau complète et les restaurations de production restent des
  gates à prouver.
- le client SMB est installé et le partage NAS existe, mais aucun secret local,
  montage durable, test négatif de droits ou restauration n'est terminé ;
- la mémoire de la passerelle reste locale et n'est pas répliquée sur le NAS.

## Ordre de reprise recommandé

1. versionner le correctif du runner et les locks PyTorch/NumPy liés à la preuve ;
2. déployer une nouvelle archive immuable et rejouer la suite Linux sans
   télécharger de dépendance ;
3. produire au moins trois répétitions pour chaque
   placement avec le même UUID de session, le même commit et le même workload,
   puis conserver séparément les deux preuves publiques ;
4. implémenter un comparateur strict de ces deux preuves avant toute conclusion
   de placement, sans présenter ce lot comme la fermeture de G4 ;
5. finaliser le secret SMB hors chat, le montage, les tests positifs/négatifs de
   droits et une restauration depuis le stockage durable ;
6. terminer la première configuration du compte propriétaire dans l'interface ;
7. confirmer la compatibilité d'un checkpoint CORE-MINI historique sur le
   nœud CPU avec le vérificateur offline ;
8. définir puis approuver les sources, licences, langues et exclusions du
   corpus ;
9. produire un tokenizer expérimental depuis le seul split `train`, évaluer sa
   qualité, puis faire approuver séparément son SHA-256 exact ;
10. exécuter le premier mini-entraînement `authorized-text` avec le bundle exact
   approuvé et conserver checkpoint, journal de métriques et lignée ;
11. évaluer ce run, vérifier sa reprise hors ligne, puis exporter un bundle
   d'inférence borné et vérifié ;
12. seulement après les gates, raccorder génération CORE, RAG, authentification,
   interface et profils d'agents.

## État de travail à vérifier avant reprise

Au moment de cette mise à jour, la correction du runner, son test et le lock
NumPy sont intentionnels. Les anciennes archives générées localement ont été
exclues du dépôt et supprimées du dossier de travail. Toujours relire le HEAD
distant et `git status` : cet état est informatif et peut devenir obsolète.

## Refus attendus

Un changement doit être refusé s'il introduit un téléchargement depuis CORE,
un build GPU, un tokenizer auto-approuvé, un corpus autre que `train`, une
promotion RAW automatique, un endpoint MCP générique, un secret dans Git ou une
revendication de capacité non mesurée.
