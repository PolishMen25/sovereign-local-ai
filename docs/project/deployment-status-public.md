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
- Aucun secret ni paramètre d’accès n’est versionné dans ce dépôt.

La création de services persistants, l’ouverture de flux et l’allocation de
stockage font l’objet de changements séparés, réversibles et audités.
