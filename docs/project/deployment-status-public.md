# État public du déploiement

> Résumé expurgé destiné au dépôt GitHub. Les détails d’adressage, de stockage,
> de comptes et de chemins d’administration restent dans l’inventaire privé.

## 2026-08-31

- Le socle du projet a été synchronisé sur les deux nœuds Proxmox actifs.
- Les contrôles automatisés du dépôt passent sur les environnements Linux.
- La stratégie hybride est appliquée comme cible : calcul local temporaire et
  conservation durable sur le stockage souverain.
- Le collecteur de conversations reste en écriture seule ; les originaux sont
  conservés en `RAW` et aucune promotion automatique n’est effectuée.
- Le serveur MCP Knowledge local répond au handshake JSON-RPC sur le nœud
  principal, en transport `stdio`, sans accès réseau ni capacité d’écriture.
- Le relais HTTPS public répond sur son endpoint de santé ; la file locale de
  synchronisation est vide après reprise.
- Le registre préparatoire des agents contient 60 profils logiques distincts,
  tous désactivés (`draft`) et limités à la proposition ; aucun modèle n'est
  dupliqué par profil.
- Un premier harness CPU borné est exécuté sur le nœud de calcul ; il fournit
  un relevé reproductible de l’hôte, mais pas encore une mesure de tokens/s.
  L’identité matérielle déclarée et celle mesurée doivent être réconciliées.
- Aucun secret ni paramètre d’accès n’est versionné dans ce dépôt.

La création de services persistants, l’ouverture de flux et l’allocation de
stockage font l’objet de changements séparés, réversibles et audités.
