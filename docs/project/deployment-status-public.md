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
- **CORE-MINI : harness d'entraînement fonctionnel.** Entraînement synthétique,
  checkpoint et reprise sont validés ; le checkpoint n'a aucun savoir
  linguistique.
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

## Preuves techniques actuelles

- PyTorch CPU est installé dans un environnement isolé sur le nœud de calcul ;
- CUDA et ROCm ne font pas partie du runtime ;
- 66 tests passent sur Linux ;
- 110 tests passent dans la préparation publique locale actuelle ; un test d'intégration
  PyTorch est ignoré sur les postes qui ne possèdent pas le bundle CPU vérifié ;
- CORE-80M s'instancie en CPU avec son nombre candidat exact, sans poids ;
- le cycle CORE-MINI entraînement → checkpoint → reprise réussit ;
- le manifeste et le tokenizer expérimentaux sont maintenant liés au seul
  split `train` par taille, compte et SHA-256 ;
- la nouvelle vérification renforcée d'un checkpoint historique reste à
  terminer sur Linux : la première tentative a été interrompue par le transport
  SSH, sans modification du checkpoint source ;
- le MCP Knowledge répond et retourne des résultats synthétiques avec
  `provenance_id` ;
- un premier benchmark NUMA existe, mais il reste préliminaire et ne permet pas
  d'extrapoler CORE-80M.

## Non revendiqué

Le projet ne revendique pas encore : modèle conversationnel, qualité
linguistique CORE, RAG sémantique, agents autonomes, interface utilisateur finale,
authentification de production, service IA persistant, gate réseau achevé ou
entraînement CORE-80M.

Aucun secret ni paramètre d'accès n'est versionné dans le dépôt.
