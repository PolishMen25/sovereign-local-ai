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
- Le bundle candidat PyTorch `2.13.0+cpu` pour CPython `3.13` a été acquis
  depuis l'index CPU officiel, verrouillé sur 10 wheels, transféré hors ligne
  puis vérifié par empreinte. L'archive de `202 498 560` octets porte le
  SHA-256 `6a4fbffcbd0fbaee63d9f6d4a23ca088a383589d2bf972a8150bff1efac9dc25` ;
  elle n'est pas installée.
- Le harness CORE-MINI CPU, checkpoint et reprise est versionné. La suite
  locale élargie compte 47 tests réussis ; aucun entraînement miniature réel
  n'est encore présenté comme accompli.
- Un partage SMB dédié et un compte de service sans shell sont en place pour la
  synchronisation durable. Le catalogue synthétique y est copié avec empreinte
  identique ; aucune donnée sensible n’y est placée avant validation du
  chiffrement, des snapshots et de la restauration.
- Un second partage de préparation a été créé vide avec des ACL contrôlées.
  Son activation chiffrée a échoué sans migration : le partage précédent reste
  intact et le diagnostic DSM demeure un gate avant toute donnée sensible.
- Aucun secret ni paramètre d’accès n’est versionné dans ce dépôt.

La création de services persistants, l’ouverture de flux et l’allocation de
stockage font l’objet de changements séparés, réversibles et audités.
