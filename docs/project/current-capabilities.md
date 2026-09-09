# Capacités réellement disponibles

Dernière vérification : 2026-09-09.

Ce document est la source de vérité publique sur l'état exécutable du projet.
Il distingue ce qui fonctionne aujourd'hui de l'architecture visée.

## Réponse courte

Il est possible de poser une question à BOOTSTRAP depuis une CLI SSH ou une
interface HTTPS privée de tailnet et d'obtenir une réponse réellement générée.
L'agent de programmation Qwen2.5-Coder-7B est décidé mais pas encore acquis ni
déployé. CORE-30M valide l'entraînement CPU ; il n'est pas un chat.

Le checkpoint CORE-MINI actuel prouve que l'entraînement CPU, la sauvegarde et
la reprise fonctionnent. CORE-30M poursuit séparément sa validation de pipeline
avec un budget cible de 600 M tokens. Ni CORE-MINI, ni CORE-30M, ni CORE-700M
ne sont présentés comme moteur conversationnel ou de programmation utilisable.

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
| Runtime tensoriel CPU hors ligne | Installé et vérifié dans le conteneur CORE | PyTorch `2.13.0+cpu` et NumPy `2.5.2` ont été réinjectés depuis des wheels vérifiés ; CUDA est indisponible et non compilé | Runtime technique isolé, pas un assistant ni des poids CORE |
| Chat BOOTSTRAP | CLI et passerelle HTTPS privée fonctionnelles | Qwen2.5-1.5B-Instruct Q4_K_M génère réellement sur CPU avec llama.cpp en boucle locale ; la passerelle authentifiée nomme le moteur, conserve localement les échanges masqués et peut joindre des références lexicales avec provenance | Modèle tiers temporaire, pas CORE ; aucun outil ou agent, aucun RAG sémantique ; première configuration propriétaire encore requise |
| CORE-MINI-1M | Entraînement `authorized-text` borné et reprise vérifiés | Modèle de 1 328 256 paramètres ; 50 étapes sur le corpus approuvé, checkpoint durable, puis reprise contrôlée de 10 étapes jusqu'à 60 avec journal continu et empreintes ; modes explicitement séparés | 60 étapes ne produisent pas un assistant : aucune évaluation linguistique ni question CORE possible ; aucun checkpoint CORE-700M |
| Runner CORE-MINI NUMA | Deux preuves A/B et comparateur strict exécutés | Contrats privés hors Git, archive source et runtimes offline vérifiés, placement externe, sockets INET refusées, trois répétitions fraîches par placement et comparaison fermée | Mesures mémoire/NUMA élargies et décision G4 encore absentes |
| Zone de calcul CORE | Invité non privilégié actif | Runtime CPU hors ligne isolé, stockage de travail local et accès borné au stockage durable ; aucun téléchargement à l'exécution ; deux paliers CORE-700M exécutés | Aucun service de génération CORE ; preuve d'isolation après redémarrage reste à compléter |
| CORE-700M | Preuves mécaniques archivées | Configuration, tokenizer et checkpoints techniques sont conservés pour traçabilité | Aucun entraînement long ni objectif de chat ou code ; cette voie est remplacée par D-034 |
| Agent Qwen2.5-Coder-7B | Acquisition décidée, non déployée | Lock candidat, licence Apache-2.0 et politique d'historique additif sont documentés | Le GGUF doit encore être acquis en RAW, haché, promu explicitement et déployé sur le nœud séparé |
| Corpus / tokenizer | Candidat 32k traçable | Manifeste `0.2.0`, split `train` lié par taille/compte/SHA, Byte-BPE ordonné, NFC partagé, encode/decode et promotion `experimental` → `candidate_core` avec reçu | Qualité, couverture française et passage à l'échelle restent à traiter |
| Moteur d'inférence CORE | Runtime expérimental CPU actif | Checkpoint d'inférence compact validé, contrat configuration/tokenizer/manifeste/préflight vérifié, API privée authentifiée sur `192.168.0.143:9000`, génération gloutonne bornée et déterministe | Vingt étapes ne constituent pas une qualité linguistique ; aucune promesse d'assistant général. Le runtime ne reçoit ni Internet ni outil arbitraire |
| MCP Knowledge | Prototype `stdio` fonctionnel | Handshake MCP, état, recherche lexicale et récupération bornée d'une provenance exacte | Trois notices synthétiques ; l'index hybride testé n'est pas encore alimenté ni raccordé au chat |
| RAG | Recherche lexicale locale approuvée, avec gate de reconstruction | L'index SQLite/FTS5 fournit à BOOTSTRAP des extraits bornés et citations depuis quatre documents internes approuvés ; toute reconstruction exige un manifeste exact, son empreinte et une référence d'audit | Aucun moteur d'embeddings, index sémantique, conversation, RAW ou VALIDATED n'est indexé |
| Collector de conversations | Ingress write-only fonctionnel | Endpoint HTTPS de santé et dépôt authentifié vers RAW | Aucune lecture interne ni promotion automatique vers `VALIDATED` |
| Synology | Stockage durable monté et persistant sur l'hôte de calcul | SMB 3.1.1 chiffré, compte de service limité, montage activé au démarrage, lecture/écriture CORE et aller-retour synthétique vérifiés via un point de montage contrôlé ; mémoire, index lexical et checkpoint CORE-MINI sont sauvegardés et restaurés avec empreintes vérifiées | Le remplacement d'une base active, la restauration d'un checkpoint CORE-700M et le test de droits négatifs restent à faire |
| Orchestrateur | Préparation fail-closed | Chargement du registre et validation partielle d'enveloppes/permissions | Aucun appel de modèle, d'outil ou de file d'exécution |
| 60 profils d'agents | Configurés mais désactivés | Identifiants, permissions minimales et contrats versionnés | Tous sont `draft`; aucun agent n'est actif |
| Mémoire conversationnelle | SQLite local actif avec sauvegarde durable | Masquage de secrets, empreintes, historique, export, suppression avec reçu sans contenu et sauvegarde SQLite vérifiée vers le NAS | Pas encore raccordée au RAG ; restauration applicative de remplacement reste manuelle |
| Interface Web du projet | Passerelle installée et active derrière le HTTPS privé | Première configuration, login, CSRF, historique réouvrable, export, suppression et `/v1/chat` vers llama.cpp ou CORE ; le sélecteur marque en permanence CORE-700M comme expérimental et conserve le moteur utilisé | CORE reste expérimental et BOOTSTRAP demeure la valeur par défaut |
| Authentification/RBAC | Argon2id et sessions déployés | Secret propriétaire créé dans le navigateur, jetons de session hachés, cookie sécurisé et CSRF | Compte propriétaire pas encore initialisé ; politiques des agents non raccordées |

## Vérifications confirmées

- PyTorch `2.13.0+cpu` et NumPy `2.5.2` ont été vérifiés contre leurs locks puis
  installés hors ligne dans un runtime isolé ; CUDA est indisponible et non
  compilé, et quatre tests CPU ciblés passent dans ce runtime ;
- après cette installation, CORE ne présente aucune route par défaut ; une
  résolution DNS externe et une connexion TCP directe de contrôle vers Internet
  sont refusées ;
- un entraînement CORE-MINI `authorized-text` de 50 étapes a produit un
  checkpoint durable, puis a repris 10 étapes jusqu'à l'étape 60 sur Linux ;
  les métriques restent continues et liées au même corpus et tokenizer. Ce
  palier prouve la reprise technique, pas une capacité conversationnelle ;
- CORE-700M a été instancié et entraîné sur CPU pour une étape réelle, puis
  restauré depuis ce checkpoint et entraîné jusqu'à l'étape 2 ; les deux
  checkpoints sont persistés. Ce test prouve le chemin technique, pas la
  qualité du modèle ni une capacité conversationnelle ;
- le harness et la future inférence partagent maintenant la même définition
  CPU-only du decoder, sans modifier le format des checkpoints existants ;
- le trainer et le vérificateur lisent, valident et hachent la configuration
  CORE-MINI depuis une seule copie d'octets bornée, avec architecture et
  comptage exacts ; leurs parseurs publics n'exposent pas les chemins reçus ;
- le tokenizer Byte-BPE normalise, encode et décode de façon déterministe,
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
- le service d'index local a construit la base SQLite/FTS5 depuis les vingt
  documents Markdown livrés avec la révision installée ; une recherche lexicale
  locale a renvoyé des documents et leurs empreintes de provenance ;
- une sauvegarde de l'index lexical a été créée puis vérifiée et restaurée dans
  un fichier de contrôle, avec empreinte identique ; ce fichier de contrôle a
  été supprimé sans remplacer la base active ;
- le manifeste RAG interne `project-internal-v1` a été approuvé et reconstruit
  atomiquement depuis quatre documents versionnés (capacités, décisions,
  architecture et modèle de menace) ; son empreinte de contenu est
  `f2176bce068c4da8eb89cb0ef615c3d2a36a33756d4da7f345cbbdaa30189de5` ;
- la sauvegarde durable de cet index approuvé a été restaurée dans un fichier
  de contrôle isolé ; le vérificateur a confirmé son empreinte, puis le fichier
  de contrôle a été supprimé sans remplacer la base active ;
- un run CORE-MINI synthétique frais de vingt étapes a produit un checkpoint,
  copié vers le stockage durable puis restauré dans un fichier de contrôle avec
  la même empreinte ; le vérificateur offline a repris cette copie à l'étape 21
  et l'a déclarée compatible CPU-only, réseau désactivé ;
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

Après réinjection et vérification hors ligne du bundle PyTorch CPU, CORE-MINI
peut être entraîné sur un répertoire neuf :

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
