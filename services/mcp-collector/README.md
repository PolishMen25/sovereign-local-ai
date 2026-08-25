# MCP Collector externe

Point de dépôt minimal pour les recherches externes. Le contrat V0 candidat expose une soumission atomique `submit_research_package` et renvoie uniquement son accusé de réception technique immédiat. Il n'expose ni consultation d'état différée, ni liste, ni lecture, ni modification. Un futur protocole fragmenté exigerait un ADR et les mêmes garanties d'absence de lecture.

Il ne fournit aucune recherche, lecture de document privé, mémoire d'agent, fichier de modèle, shell, chemin arbitraire ou accès au réseau interne. Son protocole et son authentification restent à décider.

