# Utiliser le chat bootstrap en CLI ou en HTTPS privé

Cette procédure concerne le modèle tiers temporaire BOOTSTRAP. Il reste
strictement distinct de CORE et n'utilise aucun outil, agent, RAG ni
téléchargement à l'exécution.

## HTTPS privé validé

Une démonstration persistante peut être exécutée dans un conteneur dédié : le
serveur llama.cpp écoute uniquement sur sa boucle locale, puis un relais HTTPS
Tailscale le rend accessible aux seules machines autorisées du tailnet. Ce
relais n'est pas Tailscale Funnel : aucun port n'est publié sur Internet.

La page servie est l'interface native de llama.cpp. Elle fournit un chat réel
avec le modèle BOOTSTRAP ; elle n'est ni l'interface Web du projet, ni CORE, ni
un accès aux services MCP. Ne coller aucun secret, mot de passe ou document
privé : aucune politique de conservation de conversations n'est encore
approuvée.

Le service doit rester lié à `127.0.0.1`, fonctionner sous un compte de service
non privilégié, être lancé avec `--offline` et sans outils, agent ou proxy MCP.
Le relais HTTPS doit rester privé au tailnet. Désactiver le relais avant toute
modification de la frontière réseau.

## CLI locale

Depuis une session SSH vers le nœud de calcul, exécuter le lanceur installé dans
le répertoire bootstrap :

```bash
<bootstrap-root>/bootstrap_chat_cli.sh
```

Quitter avec `Ctrl+C`. Le runtime reste local et ne doit jamais recevoir
l'option de téléchargement `-hf`.
