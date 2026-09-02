# État public du déploiement

Dernière vérification : 2026-09-01.

La source de vérité détaillée est la page
[Capacités réellement disponibles](current-capabilities.md). Ce résumé reste
volontairement au niveau des composants et n'expose ni adresse privée, ni
compte, ni secret, ni chemin d'administration.

## État essentiel

- **Chat BOOTSTRAP : disponible en CLI et HTTPS privé.** Des poids GGUF
  vérifiés sont chargés par llama.cpp sur CPU et produisent une vraie réponse.
  Le serveur reste lié à sa boucle locale et le relais HTTPS est restreint au
  tailnet ; aucune exposition Internet n'est activée. Ce modèle tiers
  temporaire est explicitement distinct de CORE.
- **CORE-MINI : harness synthétique fonctionnel.** Entraînement synthétique et
  checkpoint atomique sont validés. Le nouveau chargement strict et le mode
  explicite `authorized-text` sont implémentés et couverts par les tests locaux,
  mais aucun run `authorized-text` de bout en bout ni reprise du checkpoint
  historique avec ces nouveaux contrôles n'est encore confirmé sur Linux. Le
  runner NUMA répété est implémenté, mais aucune preuve conforme produite par ce
  runner n'est encore documentée sur le nœud CPU.
- **CORE-700M : conception seulement.** L'architecture candidate et son
  comptage exact de 691 160 320 paramètres sont versionnés. CORE-80M reste une
  référence historique ; aucun tokenizer final, corpus approuvé ou poids
  CORE-700M utilisable n'existe.
- **MCP Knowledge et RAG : implémentation locale partielle.** MCP expose en
  `stdio` l'état, la recherche lexicale et une provenance exacte. Un index
  hybride SQLite/FTS5/vecteurs est testé, sans moteur d'embeddings installé ni
  données réelles indexées.
- **Interface Web du projet : implémentée localement, non déployée.** Première
  configuration, Argon2id, sessions, CSRF, mémoire, historique et client
  llama.cpp loopback sont testés. L'interface native BOOTSTRAP reste le seul
  service HTTPS actuellement installé.
- **Agents : configuration seulement.** Les 60 profils sont tous `draft` et
  aucun agent n'est actif.
- **Orchestrateur et autorisations : préparation seulement.** Les validateurs
  fail-closed existent et le compte propriétaire local est implémenté, mais les
  profils, outils et confirmations ne sont pas encore raccordés au chat.
- **Collector : ingress write-only actif.** Son endpoint HTTPS de santé répond ;
  une entrée acceptée reste `RAW` et n'est jamais promue automatiquement.
- **Stockage : partage Synology préparé, non monté.** L'arborescence durable
  existe, mais le client SMB, le secret local et l'unité de montage ne sont pas
  actifs dans le conteneur de calcul. Aucune restauration n'est revendiquée.

Ces éléments restent des preuves opérationnelles réversibles de phase 0. Ils ne
valident ni l'orientation P-002, ni la topologie cible, ni un gate de mise en
production.

## Preuves techniques actuelles

- PyTorch CPU est installé dans un environnement isolé sur le nœud de calcul ;
- CUDA et ROCm ne font pas partie du runtime ;
- CORE-80M s'est historiquement instancié en CPU avec son nombre candidat exact ;
- CORE-700M possède une configuration et un comptage exacts, sans instanciation
  complète mesurée ni poids ;
- le cycle CORE-MINI entraînement → checkpoint → reprise a réussi sur Linux
  avec le chargeur borné antérieur ;
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
- la nouvelle vérification renforcée d'un checkpoint historique reste à
  terminer sur Linux : la première tentative a été interrompue par le transport
  SSH, sans modification du checkpoint source ;
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
  multi-placement conforme, mesure mémoire ou série complète de compteurs NUMA
  ne permet encore d'extrapoler CORE-700M.

## Non revendiqué

Le projet ne revendique pas encore : entraînement sur un corpus réel approuvé,
poids linguistiques CORE, modèle conversationnel CORE, RAG sémantique, agents
autonomes, interface utilisateur finale, authentification de production, gate
réseau achevé, preuve NUMA multi-placement acceptée ou entraînement CORE-700M.
Le service BOOTSTRAP privé est une démonstration bornée, pas un service CORE de
production.

Le contenu de ce jalon ne versionne aucun secret, identifiant privé ni adresse
d'administration.
