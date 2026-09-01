# Capacités réellement disponibles

Dernière vérification : 2026-09-01.

Ce document est la source de vérité publique sur l'état exécutable du projet.
Il distingue ce qui fonctionne aujourd'hui de l'architecture visée.

## Réponse courte

Il est maintenant possible de poser une question à un modèle local depuis la
CLI SSH et d'obtenir une réponse réellement générée. Ce chat utilise le modèle
tiers temporaire **BOOTSTRAP**, pas CORE-80M.

Le checkpoint CORE-MINI actuel prouve que l'entraînement CPU, la sauvegarde et
la reprise fonctionnent. Il a appris sur des identifiants de tokens synthétiques
et ne possède aucun savoir linguistique. CORE-80M n'est pas entraîné et aucun
tokenizer final, poids linguistique, moteur de génération ou chat bout en bout
n'existe encore pour CORE.

Un runner CPU/NUMA synthétique et fail-closed est maintenant implémenté pour
produire une preuve répétée d'un placement externe. Il n'a pas encore produit
de preuve conforme documentée sur le nœud CPU et ne compare pas deux
placements ; il ne ferme donc pas le gate G4.

CORE-MINI possède maintenant un second chemin, nommé explicitement
`authorized-text`. La validation du bundle, la tokenisation, le contrat, le
journal et la construction du checkpoint sont couverts par des tests unitaires
et structurels. Aucun entraînement PyTorch de bout en bout avec un corpus réel
approuvé n'a encore été exécuté par ce chemin, qui n'a donc produit aucun poids
linguistique.

Le MCP Knowledge est utilisable séparément comme recherche lexicale dans un
petit catalogue synthétique. Il retourne des résumés et leur provenance ; il ne
génère pas une réponse d'IA.

## Matrice des composants

| Composant | État exact | Ce qui fonctionne | Limite actuelle |
| --- | --- | --- | --- |
| PyTorch CPU hors ligne | Installé et vérifié | Environnement isolé sur le nœud de calcul, calcul CPU, aucune dépendance CUDA/ROCm | Runtime technique, pas un assistant |
| Chat BOOTSTRAP | CLI locale fonctionnelle | Qwen2.5-1.5B-Instruct Q4_K_M génère réellement en français sur CPU avec llama.cpp | Modèle tiers temporaire, aucun outil/RAG/agent, pas CORE |
| CORE-MINI-1M | Harness synthétique validé ; chemin `authorized-text` structurellement testé | Modèle de 1 328 256 paramètres ; entraînement synthétique et checkpoint atomique ; modes explicitement séparés et contrôles stricts locaux | Aucun run `authorized-text` de bout en bout, aucun langage appris, aucune question possible ; compatibilité du checkpoint historique avec le nouveau chargeur à confirmer sur Linux |
| Runner CORE-MINI NUMA | Implémenté, sans preuve matérielle conforme publiée | Contrat privé strict hors Git, archive source et runtime offline vérifiés, contrôle du placement externe et des sockets flux/datagrammes INET, attestations par phase, 3 à 10 répétitions fraîches et preuve publique minimisée | Linux et isolation externe requis ; un placement par preuve, aucun comparateur multi-placement, aucune mesure complète pour G4 |
| CORE-80M | Architecture CPU vérifiée | Configuration candidate, comptage et instanciation CPU exacte de 81 444 480 paramètres | Aucun tokenizer final, corpus approuvé ou poids |
| Corpus / tokenizer | Prototype expérimental rejouable | Manifeste `0.2.0`, split `train` lié par taille/compte/SHA, Byte-BPE ordonné, NFC partagé, encode/decode et validation stricte | Aucun corpus ou tokenizer final approuvé ; qualité et passage à l'échelle restent à traiter |
| Moteur d'inférence CORE | Garde-fou inactif | Validation des entrées et refus sûr quand le runtime CORE n'est pas disponible | Aucun poids ou génération CORE ; BOOTSTRAP utilise un runtime séparé |
| MCP Knowledge | Prototype `stdio` fonctionnel | Handshake MCP, état et recherche lexicale bornée avec provenance | Trois notices synthétiques, pas de RAG vectoriel ni de réponse générée |
| Collector de conversations | Ingress write-only fonctionnel | Endpoint HTTPS de santé et dépôt authentifié vers RAW | Aucune lecture interne ni promotion automatique vers `VALIDATED` |
| Synology | Stockage préparé | Coffre chiffré monté et essais synthétiques de copie/restauration | Pas encore le corpus réel ni la mémoire conversationnelle validée du modèle |
| Orchestrateur | Préparation fail-closed | Chargement du registre et validation partielle d'enveloppes/permissions | Aucun appel de modèle, d'outil ou de file d'exécution |
| 60 profils d'agents | Configurés mais désactivés | Identifiants, permissions minimales et contrats versionnés | Tous sont `draft`; aucun agent n'est actif |
| Interface Web | Coquille locale testable | Page statique, santé, Bearer prototype et validation partielle des requêtes | Non démarrée par défaut; `/v1/chat` renvoie toujours HTTP 503 |
| Authentification/RBAC | Prototype non intégré | Politique de rôles testable séparément | Aucun compte, session, annuaire ou contrôle RBAC branché à l'interface |

## Vérifications confirmées

- PyTorch annonce un build CPU et `torch.cuda.is_available()` vaut `False` ;
- un checkpoint CORE-MINI a été produit puis repris sur Linux avec le chargeur
  borné antérieur ; sa compatibilité avec les nouveaux contrôles stricts reste
  à prouver ;
- CORE-80M s'instancie en RAM CPU avec son nombre exact de paramètres ;
- le harness et la future inférence partagent maintenant la même définition
  CPU-only du decoder, sans modifier le format des checkpoints existants ;
- le trainer et le vérificateur lisent, valident et hachent la configuration
  CORE-MINI depuis une seule copie d'octets bornée, avec architecture et
  comptage exacts ; leurs parseurs publics n'exposent pas les chemins reçus ;
- le tokenizer expérimental normalise, encode et décode de façon déterministe,
  refuse les fusions ou couvertures d'octets incohérentes et borne les entrées ;
- le chargeur de texte autorisé refuse toute partition autre que `train` et lie
  corpus, manifeste et tokenizer sans recopier leur contenu dans la lignée ;
- `train_core_mini.py` n'active ce chargeur que par
  `--data-mode authorized-text`, exige les trois artefacts, vérifie le
  vocabulaire exact et ne bascule jamais implicitement vers les données
  synthétiques ;
- le journal `authorized-text` refuse les clés ou valeurs inattendues, lie
  chaque mesure au SHA-256 du contrat et vérifie la continuité avant reprise ;
  son préfixe exact est haché dans le checkpoint puis exigé lors d'une reprise ;
- le harness et le vérificateur partagent les contrôles stricts de l'état du
  modèle et de l'optimiseur, y compris les strides, stockages et alias AdamW ;
  la reprise d'un ancien checkpoint réel n'a pas encore été prouvée, car la
  tentative distante a été interrompue par l'instabilité SSH ;
- le summarizer de métriques `v2` valide strictement un journal synthétique ou
  `authorized-text`, publie le SHA-256 exact de ses octets et calcule, après
  chauffe, moyenne, médiane, minimum, maximum, écart-type de population, MAD et
  débit ; il exige un journal commençant à l'étape 1, ne recompose pas une
  reprise, n'agrège pas plusieurs runs et ne constitue pas une preuve de
  benchmark NUMA complet ;
- le runner NUMA exige un nouveau répertoire de run absolu, un contrat privé
  strict hors Git, une session `session-<UUID v4>` et une archive Git source
  canonique ; les répétitions, étapes, chauffe, lot, séquence,
  threads, graine et délais sont bornés ;
- avant tout run, il exige que les sockets flux et datagrammes des familles
  `AF_INET` et `AF_INET6` soient déjà refusées, compare exactement affinité et
  politique mémoire au contrat privé, puis confirme l'environnement CPU-only
  dans un processus enfant ;
- chaque répétition emploie des processus frais sans shell, relit le résumé
  `v2`, reprend le checkpoint une étape avec le vérificateur offline et refuse
  toute dérive d'empreinte, de placement ou de source ; la sortie publique ne
  contient aucun hostname, détail CPU exact, commande ou chemin ;
- BOOTSTRAP charge ses poids GGUF vérifiés et génère du texte français localement ;
- un premier échange français a été généré localement, sans écoute réseau ;
- le MCP Knowledge répond actuellement en `stdio` et voit trois notices
  synthétiques ;
- une recherche `stockage hybride` retourne des résumés avec `provenance_id` ;
- aucun serveur Web de chat n'est démarré par défaut sur le nœud de calcul ;
- le relais HTTPS du Collector répond en mode `write-only` ; son expéditeur
  refuse les redirections, valide chaque payload en file et ne le supprime
  qu'après écriture atomique et vérification locale d'un reçu concordant ;
- le coffre Synology chiffré est monté.

Le relais HTTPS et le coffre restent des preuves opérationnelles réversibles de
phase 0. Ils ne valident ni l'orientation P-002, ni la topologie cible, ni un
gate de mise en production.

Ces contrôles ne prouvent pas encore l'isolation réseau complète de la future
zone IA-CORE, la qualité d'un modèle linguistique ou la disponibilité d'un
service de production.

## Utilisable aujourd'hui

Le chat BOOTSTRAP se lance dans une session SSH avec le lanceur décrit dans
[le runbook CLI](../operations/bootstrap-chat-cli.md). La commande ouvre une
conversation interactive réelle ; `/exit` ou `Ctrl+C` la termine.

Depuis la racine du dépôt :

```bash
# Vérifier le socle
python3 -B -m unittest discover -s tests -q

# Vérifier les nombres de paramètres
python3 -B tools/count_core_parameters.py \
  --config configs/models/core-mini.candidate.json
python3 -B tools/count_core_parameters.py \
  --config configs/models/core-80m.candidate.json
```

Dans l'environnement PyTorch CPU préparé, CORE-MINI peut être entraîné sur un
répertoire neuf :

```bash
python -B -m tools.train_core_mini \
  --config configs/models/core-mini.candidate.json \
  --output-dir runs/core-mini-demo \
  --steps 20 \
  --batch-size 4 \
  --sequence-length 64 \
  --threads 20
```

Cette commande produit une preuve technique, pas un modèle auquel parler.

Le runner NUMA est lui aussi un outil de preuve de phase 0, pas une commande
d'activation. Sa CLI et ses préconditions sont décrites dans le
[protocole CORE-MINI NUMA](../model/core-mini-numa-protocol.md). Les arguments
obligatoires sont `--run-root`, `--placement-contract`,
`--benchmark-session-id` et `--source-archive`. Une instance réelle du contrat
de placement reste privée et ne doit jamais être ajoutée au dépôt.

Le mode `authorized-text` est volontairement inutilisable sans les trois
artefacts approuvés et concordants. Sa forme de commande est documentée dans
[le gate corpus et tokenizer](../model/corpus-and-tokenizer-gate.md) ; elle ne
doit pas être exécutée avec un contenu réel avant l'approbation du gate.

Le MCP Knowledge peut être interrogé par un client MCP compatible `stdio` avec
les outils suivants :

- `knowledge_status {}` ;
- `search_validated {"query": "stockage hybride"}`.

## Pour rendre le chat CORE utilisable

Il reste à réaliser, dans cet ordre :

1. approuver et construire le corpus et le tokenizer ;
2. entraîner puis évaluer des poids linguistiques utiles ;
3. implémenter le chargement des poids, la génération autorégressive et le
   décodage des tokens ;
4. relier l'interface, l'authentification, l'orchestrateur et le MCP Knowledge ;
5. activer seulement les profils d'agents approuvés ;
6. valider l'isolation réseau, les droits, l'audit, les sauvegardes et la
   restauration avant tout service persistant.

BOOTSTRAP fournit le chat immédiat, mais ne franchit aucune de ces étapes et ne
doit jamais être présenté comme CORE. Aucune inférence distante n'est utilisée.
