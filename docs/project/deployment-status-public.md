# État public du déploiement

Dernière vérification : 2026-09-01.

La source de vérité détaillée est la page
[Capacités réellement disponibles](current-capabilities.md). Ce résumé reste
volontairement au niveau des composants et n'expose ni adresse privée, ni
compte, ni secret, ni chemin d'administration.

## État essentiel

- **Chat BOOTSTRAP : disponible en CLI locale.** Des poids GGUF vérifiés sont
  chargés par llama.cpp sur CPU et produisent une vraie réponse en français.
  Ce modèle tiers temporaire est explicitement distinct de CORE.
- **CORE-MINI : harness synthétique fonctionnel.** Entraînement synthétique et
  checkpoint atomique sont validés. Le nouveau chargement strict et le mode
  explicite `authorized-text` sont implémentés et couverts par les tests locaux,
  mais aucun run `authorized-text` de bout en bout ni reprise du checkpoint
  historique avec ces nouveaux contrôles n'est encore confirmé sur Linux.
- **CORE-80M : conception seulement.** L'architecture et son comptage sont
  versionnés, mais aucun tokenizer final, corpus approuvé ou poids utilisable
  n'existe.
- **MCP Knowledge : prototype local fonctionnel.** Il expose en `stdio` un état
  et une recherche lexicale bornée dans trois notices synthétiques avec
  provenance. Ce n'est pas un RAG vectoriel ni une IA générative.
- **Interface Web : coquille de sécurité.** Elle est testable en boucle locale,
  mais n'est pas démarrée par défaut et `/v1/chat` renvoie toujours HTTP `503`.
- **Agents : configuration seulement.** Les 60 profils sont tous `draft` et
  aucun agent n'est actif.
- **Orchestrateur et autorisations : préparation seulement.** Les validateurs
  fail-closed existent, mais aucun modèle, outil, compte utilisateur ou RBAC
  réel n'est branché.
- **Collector : ingress write-only actif.** Son endpoint HTTPS de santé répond ;
  une entrée acceptée reste `RAW` et n'est jamais promue automatiquement.
- **Stockage : coffre chiffré monté.** Seules des données synthétiques ont servi
  aux validations actuelles ; elles ne constituent pas la mémoire du modèle.

Ces éléments restent des preuves opérationnelles réversibles de phase 0. Ils ne
valident ni l'orientation P-002, ni la topologie cible, ni un gate de mise en
production.

## Preuves techniques actuelles

- PyTorch CPU est installé dans un environnement isolé sur le nœud de calcul ;
- CUDA et ROCm ne font pas partie du runtime ;
- 66 tests passent sur Linux ;
- 160 tests réussissent dans la suite locale complète, désormais élargie au
  mode `authorized-text` et au chargement strict ; un test d'intégration PyTorch
  est ignoré sur les postes qui ne possèdent pas le bundle CPU vérifié ;
- CORE-80M s'instancie en CPU avec son nombre candidat exact, sans poids ;
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
- le premier passage NUMA reste préliminaire : aucune agrégation de
  répétitions, preuve d'affinité, mémoire de pointe ou série complète de
  compteurs NUMA ne permet encore d'extrapoler CORE-80M.

## Non revendiqué

Le projet ne revendique pas encore : entraînement sur un corpus réel approuvé,
poids linguistiques CORE, modèle conversationnel CORE, RAG sémantique, agents
autonomes, interface utilisateur finale, authentification de production,
service IA persistant, gate réseau achevé ou entraînement CORE-80M.

Le contenu de ce jalon ne versionne aucun secret, identifiant privé ni adresse
d'administration.
