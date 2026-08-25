# Frontières des futurs services

Ce dossier réserve les contextes fonctionnels sans choisir encore leur langage, framework ou mode de déploiement.

| Service | Zone | Responsabilité | Interdiction principale |
|---|---|---|---|
| `research-gateway` | Internet/DMZ | Appeler les fournisseurs autorisés et normaliser leurs réponses. | Recevoir des secrets ou documents privés non déclassifiés. |
| `mcp-collector` | DMZ | Recevoir des paquets externes à privilèges minimaux. | Lire IA-CORE ou la base interne. |
| `quarantine` | DMZ/sas | Valider, analyser, nettoyer et préparer une promotion. | Déclarer seule une information vraie. |
| `knowledge` | IA privée | Servir documents validés, provenance et recherche interne. | Être exposé à Internet. |
| `orchestrator` | IA-CORE | Router les tâches vers agents, modèles et outils permis. | Contourner les permissions des agents. |
| `web` | réseau interne | Fournir l'interface utilisateur et l'authentification. | Devenir un proxy Internet pour IA-CORE. |

Chaque sous-dossier contient seulement un contrat de responsabilité. L'implémentation commence après les ADR de pile, réseau, stockage et identité.

