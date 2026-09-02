# Stockage Synology restreint

Ce dossier prépare le montage du partage `sovereign-ai` dans le conteneur de
calcul. Il ne contient aucun mot de passe, adresse interne ou clé privée.

Le compte DSM dédié doit être sans privilège d'administration, refusé sur tous
les autres partages et autorisé seulement en lecture-écriture sur
`sovereign-ai`. Le fichier de secrets local `/opt/sovereign/credentials/synology-smb`
est créé hors Git, avec le mode `0600` et les champs `username` et `password`.

Le nom d'une unité systemd de montage doit correspondre exactement à son point
de montage. Calculer le nom sur Linux avec
`systemd-escape -p --suffix=mount /mnt/sovereign-ai`, puis installer le contenu
de `sovereign-ai.mount.example` sous ce nom. Remplacer uniquement
`SYNOLOGY_HOST` par l'adresse privée du NAS, créer `/mnt/sovereign-ai` avec le
propriétaire du compte de service, puis démarrer l'unité. Ne jamais copier le
nom descriptif de l'exemple comme nom d'unité. Le montage reste volontairement
absent tant que le secret, l'ACL DSM et la connectivité SMB ne sont pas vérifiés.

Les options obligatoires limitent le montage : SMB 3.1.1 chiffré (`seal`),
aucune exécution, aucun périphérique, aucun bit setuid et démarrage après le
réseau. Les dossiers à utiliser sont `raw`, `validated`, `models` et `backups`.
`RAW` ne devient jamais `VALIDATED` par le simple fait d'être stocké ici.
