# Capacités réellement disponibles

Dernière vérification : 2026-09-06.

Ce document est la source de vérité publique sur l'état exécutable du projet.
Il distingue ce qui fonctionne aujourd'hui de l'architecture visée.

## Réponse courte

Il est maintenant possible de poser une question à un modèle local depuis une
CLI SSH ou une interface HTTPS privée de tailnet et d'obtenir une réponse
réellement générée. Ce chat utilise le modèle tiers temporaire **BOOTSTRAP**,
pas CORE-700M.

Le checkpoint CORE-MINI actuel prouve que l'entraînement CPU, la sauvegarde et
la reprise fonctionnent. Il a appris sur des identifiants de tokens synthétiques
et ne possède aucun savoir linguistique. CORE-700M n'est pas entraîné et aucun
tokenizer final, poids linguistique, moteur de génération ou chat bout en bout
n'existe encore pour CORE.

Un runner CPU/NUMA synthétique et fail-closed a produit deux preuves répétées
de trois runs sur le même commit et workload. Le placement A a une médiane
supérieure de 3,8 % à B sur ce mini-test. Ce résultat descriptif ne vaut ni
choix de placement final, ni estimation de durée CORE-700M ; le gate G4 reste
ouvert.

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
| Runtime tensoriel CPU hors ligne | Installé et vérifié | PyTorch `2.13.0+cpu` et NumPy `2.5.2` dans un environnement isolé, acquis par empreintes et installés sans index réseau ; aucune dépendance CUDA/ROCm | Runtime technique, pas un assistant |
| Chat BOOTSTRAP | CLI et passerelle HTTPS privée fonctionnelles | Qwen2.5-1.5B-Instruct Q4_K_M génère réellement sur CPU avec llama.cpp en boucle locale ; la passerelle authentifiée nomme le moteur et conserve localement les échanges masqués | Modèle tiers temporaire, aucun RAG/outil/agent, pas CORE ; première configuration propriétaire encore requise et mémoire non répliquée |
| CORE-MINI-1M | Harness synthétique validé ; chemin `authorized-text` structurellement testé | Modèle de 1 328 256 paramètres ; run strict de 20 étapes puis reprise de 5 étapes jusqu'à l'étape 25 ; modes explicitement séparés | Aucun run `authorized-text` de bout en bout, aucun langage appris, aucune question possible ; compatibilité d'un ancien checkpoint historique encore à confirmer |
| Runner CORE-MINI NUMA | Deux preuves A/B et comparateur strict exécutés | Contrats privés hors Git, archive source et runtimes offline vérifiés, placement externe, sockets INET refusées, trois répétitions fraîches par placement et comparaison fermée | Mesures mémoire/NUMA élargies et décision G4 encore absentes |
| Zone de calcul CORE | Invité non privilégié actif | Runtime CPU hors ligne, stockage de travail local et accès borné au stockage durable ; aucun téléchargement à l'exécution | Aucun poids, service de génération CORE ou entraînement long ; preuve d'isolation après redémarrage encore à compléter |
| CORE-700M | Architecture candidate et comptage exact vérifié | Configuration de 691 160 320 paramètres ; CORE-80M reste une référence historique | Aucune instanciation complète mesurée, aucun tokenizer final, corpus approuvé ou poids |
| Corpus / tokenizer | Prototype expérimental rejouable | Manifeste `0.2.0`, split `train` lié par taille/compte/SHA, Byte-BPE ordonné, NFC partagé, encode/decode et validation stricte | Aucun corpus ou tokenizer final approuvé ; qualité et passage à l'échelle restent à traiter |
| Moteur d'inférence CORE | Garde-fou inactif | Validation des entrées et refus sûr quand le runtime CORE n'est pas disponible | Aucun poids ou génération CORE ; BOOTSTRAP utilise un runtime séparé |
| MCP Knowledge | Prototype `stdio` fonctionnel | Handshake MCP, état, recherche lexicale et récupération bornée d'une provenance exacte | Trois notices synthétiques ; l'index hybride testé n'est pas encore alimenté ni raccordé au chat |
| RAG hybride | Module local testé, non déployé | SQLite, FTS5, vecteurs finis fournis hors module, score hybride et provenance | Aucun moteur d'embeddings vérifié installé, aucun catalogue réel indexé |
| Collector de conversations | Ingress write-only fonctionnel | Endpoint HTTPS de santé et dépôt authentifié vers RAW | Aucune lecture interne ni promotion automatique vers `VALIDATED` |
| Synology | Stockage durable monté et persistant sur l'hôte de calcul | SMB 3.1.1 chiffré, compte de service limité, montage activé au démarrage, lecture/écriture CORE et aller-retour synthétique vérifiés via un point de montage contrôlé | Aucune restauration complète de conversation, catalogue, index ou checkpoint ; réplication de mémoire et test de droits négatifs restent à faire |
| Orchestrateur | Préparation fail-closed | Chargement du registre et validation partielle d'enveloppes/permissions | Aucun appel de modèle, d'outil ou de file d'exécution |
| 60 profils d'agents | Configurés mais désactivés | Identifiants, permissions minimales et contrats versionnés | Tous sont `draft`; aucun agent n'est actif |
| Mémoire conversationnelle | SQLite local actif dans la passerelle | Masquage de secrets, empreintes, historique, export et suppression avec reçu sans contenu | Pas encore placée sur le stockage durable ni raccordée au RAG |
| Interface Web du projet | Passerelle installée et active derrière le HTTPS privé | Première configuration, login, CSRF, historique et `/v1/chat` réel vers llama.cpp avec moteur `BOOTSTRAP` explicite | Première configuration propriétaire et streaming encore à terminer ; aucun moteur CORE |
| Authentification/RBAC | Argon2id et sessions déployés | Secret propriétaire créé dans le navigateur, jetons de session hachés, cookie sécurisé et CSRF | Compte propriétaire pas encore initialisé ; politiques des agents non raccordées |

## Vérifications confirmées

- PyTorch annonce un build CPU et `torch.cuda.is_available()` vaut `False` ;
- un checkpoint CORE-MINI a été produit après 20 étapes puis repris 5 étapes
  sur Linux avec les contrôles stricts actuels ; la compatibilité d'un ancien
  checkpoint historique reste un test séparé ;
- CORE-80M s'est historiquement instancié en RAM CPU avec son nombre exact de paramètres ; CORE-700M possède seulement un comptage exact local et n'a pas encore été instancié sur le nœud ;
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
  la compatibilité d'un ancien checkpoint historique n'a pas encore été
  prouvée ;
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
- un premier échange français a été généré localement ;
- le service BOOTSTRAP persistant est lié à la boucle locale, fonctionne sans
  outils, agent, proxy MCP ou téléchargement à l'exécution ; la passerelle Web
  authentifiée l'appelle localement et est relayée en HTTPS privé au tailnet ;
- le MCP Knowledge répond actuellement en `stdio` et voit trois notices
  synthétiques ;
- une recherche `stockage hybride` retourne des résumés avec `provenance_id` ;
- la passerelle Web propre au projet est installée sur le sas ; son endpoint de
  chat appelle réellement BOOTSTRAP et sa mémoire SQLite locale prend en charge
  historique, export et suppression explicite ;
- 198 tests passent sur la révision `8071843` déployée, y compris le lock NumPy
  et la preuve NUMA renforcée ;
- le relais HTTPS du Collector répond en mode `write-only` ; son expéditeur
  refuse les redirections, valide chaque payload en file et ne le supprime
  qu'après écriture atomique et vérification locale d'un reçu concordant ;
- le stockage durable Synology est monté avec SMB 3.1.1 chiffré sur l'hôte de
  calcul, activé au démarrage puis fourni au conteneur CORE par un point de
  montage contrôlé ; une écriture de contrôle temporaire suivie de sa
  suppression et un aller-retour synthétique vérifié par empreinte ont réussi
  depuis CORE ; le conteneur ne conserve pas le secret SMB.

Le relais HTTPS et le coffre restent des preuves opérationnelles réversibles de
phase 0. Ils ne valident ni l'orientation P-002, ni la topologie cible, ni un
gate de mise en production.

Ces contrôles ne prouvent pas encore l'isolation réseau complète après tous les
scénarios de redémarrage, la qualité d'un modèle linguistique ou la
disponibilité d'un service de production.

## Utilisable aujourd'hui

Le chat BOOTSTRAP est disponible en CLI SSH. La passerelle Web est également
active sur le HTTPS privé décrit dans [le runbook
BOOTSTRAP](../operations/bootstrap-chat-cli.md), mais le propriétaire doit
d'abord activer son client tailnet puis terminer la première configuration du
compte dans le navigateur. La CLI ouvre une conversation interactive réelle ;
`/exit` ou `Ctrl+C` la termine.

Depuis la racine du dépôt :

```bash
# Vérifier le socle
python3 -B -m unittest discover -s tests -q

# Vérifier les nombres de paramètres
python3 -B tools/count_core_parameters.py \
  --config configs/models/core-mini.candidate.json
python3 -B tools/count_core_parameters.py \
  --config configs/models/core-700m.candidate.json
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

## Pour rendre le chat CORE-700M utilisable

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
