# État public du déploiement

Dernière vérification : 2026-09-07.

La source de vérité détaillée est la page
[Capacités réellement disponibles](current-capabilities.md). Ce résumé reste
volontairement au niveau des composants et n'expose ni adresse privée, ni
compte, ni secret, ni chemin d'administration.

## État essentiel

- **Chat BOOTSTRAP : disponible en CLI et via une passerelle HTTPS privée.** Des poids GGUF
  vérifiés sont chargés par llama.cpp sur CPU et produisent une vraie réponse.
  Le serveur reste lié à sa boucle locale ; la passerelle authentifiée appelle
  ce moteur, nomme chaque réponse `BOOTSTRAP` et est relayée dans le tailnet.
  La première configuration du propriétaire reste à terminer. Ce modèle tiers
  temporaire est explicitement distinct de CORE.
- **CORE-MINI : harness synthétique fonctionnel.** Entraînement synthétique et
  checkpoint atomique sont validés par un run de 20 étapes repris 5 étapes
  jusqu'à l'étape 25. Le nouveau chargement strict et le mode
  explicite `authorized-text` sont implémentés et couverts par les tests locaux,
  mais aucun run `authorized-text` de bout en bout ni reprise du checkpoint
  historique avec ces nouveaux contrôles n'est encore confirmé sur Linux. Le
  runner NUMA répété a produit deux preuves A/B de trois répétitions avec le
  même commit et workload, vérifiées par un comparateur strict. A est 3,8 % au-
  dessus de B en médiane sur ce mini-test ; aucun choix de placement ou délai
  CORE-700M n'en est déduit.
  Un checkpoint synthétique frais de vingt étapes est désormais copié sur le
  stockage durable, restauré dans un fichier de contrôle et repris offline avec
  succès à l'étape 21.
- **CORE-700M : conception seulement.** L'architecture candidate et son
  comptage exact de 691 160 320 paramètres sont versionnés. CORE-80M reste une
  référence historique ; aucun tokenizer final, corpus approuvé ou poids
  CORE-700M utilisable n'existe.
- **MCP Knowledge et RAG : recherche locale avec provenance.** MCP expose en
  `stdio` l'état, la recherche lexicale et une provenance exacte. La passerelle
  joint les extraits bornés de son index approuvé à BOOTSTRAP et retourne les
  citations. Le premier manifeste `project-internal-v1` couvre quatre documents
  internes versionnés et porte l'empreinte de contenu
  `f2176bce068c4da8eb89cb0ef615c3d2a36a33756d4da7f345cbbdaa30189de5`.
  Toute reconstruction exige un manifeste exact, son SHA-256 approuvé et une
  référence d'audit : aucun fichier Markdown n'est ajouté automatiquement.
  Aucun moteur d'embeddings ni index sémantique n'est installé ; conversations,
  RAW et VALIDATED restent hors de cet index.
- **Interface Web du projet : déployée derrière le HTTPS privé.** Argon2id,
  sessions, CSRF, mémoire SQLite locale, historique réouvrable, export,
  suppression et client llama.cpp loopback fonctionnent. Le navigateur affiche
  explicitement BOOTSTRAP et l'état de la réponse. L'initialisation du compte
  propriétaire reste à effectuer ; la mémoire est sauvegardée périodiquement
  sur le stockage durable avec vérification d'empreinte.
- **Agents : configuration seulement.** Les 60 profils sont tous `draft` et
  aucun agent n'est actif.
- **Orchestrateur et autorisations : préparation seulement.** Les validateurs
  fail-closed existent et le compte propriétaire local est implémenté, mais les
  profils, outils et confirmations ne sont pas encore raccordés au chat.
- **Collector : ingress write-only actif.** Son endpoint HTTPS de santé répond ;
  une entrée acceptée reste `RAW` et n'est jamais promue automatiquement.
- **Stockage : partage Synology monté et persistant.** L'arborescence durable
  est accessible au conteneur CORE depuis un montage hôte SMB 3.1.1 chiffré,
  activé au démarrage et contrôlé par un compte de service limité. Une écriture
  temporaire suivie de sa suppression et un aller-retour synthétique vérifié
  par empreinte ont été validés depuis CORE. Les sauvegardes SQLite de mémoire
  et d'index lexical ont été vérifiées et restaurées dans des fichiers de
  contrôle, sans remplacement de la base applicative active.
- **Zone CORE : invitée non privilégiée active.** Les flux et le stockage sont
  bornés. Le runtime PyTorch/NumPy CPU, reconstruit depuis des wheels vérifiés,
  est installé hors ligne et a passé son smoke test CPU. Aucun poids ni service
  de génération CORE n'est actif.

Ces éléments restent des preuves opérationnelles réversibles de phase 0. Ils ne
valident ni l'orientation P-002, ni la topologie cible, ni un gate de mise en
production.

## Preuves techniques actuelles

- PyTorch CPU et NumPy ont été vérifiés contre leurs locks, réinjectés hors
  ligne dans CORE et validés sans CUDA ni ROCm ;
- après cette réinjection, CORE ne possède pas de route par défaut ; les tests
  DNS externe et TCP direct vers Internet ont été refusés ;
- CUDA et ROCm ne font pas partie du runtime ;
- CORE-80M s'est historiquement instancié en CPU avec son nombre candidat exact ;
- CORE-700M possède une configuration et un comptage exacts, sans instanciation
  complète mesurée ni poids ;
- le cycle CORE-MINI entraînement → checkpoint → reprise a réussi sur Linux
  avec 20 étapes puis 5 étapes de reprise sous les contrôles stricts actuels ;
- le manifeste et le tokenizer expérimentaux sont maintenant liés au seul
  split `train` par taille, compte et SHA-256 ;
- la configuration CORE-MINI est lue, validée et hachée depuis une unique copie
  bornée, avec architecture et comptage exacts ; les erreurs CLI publiques
  n'exposent pas les chemins fournis ;
- le harness exige explicitement manifeste, JSONL `train` et tokenizer, vérifie
  le vocabulaire exact et lie métriques et checkpoint au contrat sans recopier
  le contenu ;
- le checkpoint `authorized-text` lie l'empreinte du préfixe exact du journal
  attendu à la reprise ;
- la reprise du modèle et de l'optimiseur utilise des contrôles CPU stricts
  partagés avec le vérificateur offline et refuse les strides, stockages ou
  alias AdamW anormaux ;
- la vérification renforcée d'un ancien checkpoint historique reste à terminer
  sur Linux ;
- le MCP Knowledge répond et retourne des résultats synthétiques avec
  `provenance_id` ;
- l'expéditeur du Collector refuse les redirections HTTP, valide les payloads
  en file et n'efface une entrée qu'après écriture atomique et vérification
  locale d'un reçu concordant ;
- le summarizer de métriques `v2` valide un journal borné et publie son SHA-256
  exact ainsi que moyenne, médiane, écart-type de population, MAD et débit
  après chauffe ;
- le runner NUMA phase 0 exige un nouveau répertoire absolu, un contrat de
  placement privé strict, une session UUID v4, une archive Git canonique et un
  lock de runtime offline ; ses paramètres de charge et délais sont bornés ;
- il refuse de démarrer si les sockets flux ou datagrammes des familles
  `AF_INET` et `AF_INET6` restent disponibles, vérifie l'égalité exacte du
  placement observé avec le contrat dans chaque phase enfant, puis exécute 3 à
  10 répétitions en processus frais ; chaque résumé est relu et chaque
  checkpoint est repris une étape sans modifier sa source ;
- sa preuve publique ne contient ni hostname, ni modèle ou liste CPU, ni
  commande ou chemin. Elle porte sur un seul placement ; aucune comparaison
  multi-placement strict, mesure mémoire ou série complète de compteurs NUMA
  ne permet encore d'extrapoler CORE-700M.

## Non revendiqué

Le projet ne revendique pas encore : entraînement sur un corpus réel approuvé,
poids linguistiques CORE, modèle conversationnel CORE, RAG sémantique, agents
autonomes, interface utilisateur finale, authentification de production, gate
réseau achevé, décision NUMA G4 acceptée ou entraînement CORE-700M.
Le service BOOTSTRAP privé est une démonstration bornée, pas un service CORE de
production.

Le contenu de ce jalon ne versionne aucun secret, identifiant privé ni adresse
d'administration.
