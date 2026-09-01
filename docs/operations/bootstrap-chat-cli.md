# Utiliser le chat bootstrap en CLI

Cette procédure concerne le modèle tiers temporaire BOOTSTRAP. Elle ne lance
aucun serveur Web et n'ouvre aucun port.

Depuis une session SSH vers le nœud de calcul, exécuter le lanceur installé dans
le répertoire bootstrap :

```bash
<bootstrap-root>/bootstrap_chat_cli.sh
```

Quitter avec `Ctrl+C`. Ne coller aucun secret, mot de passe ou export privé tant
que la politique de conservation des conversations n'est pas approuvée. Le
runtime reste local et ne doit jamais recevoir l'option de téléchargement `-hf`.
