# Runtime d’inférence local

`runtime.py` fixe la frontière CPU-only du futur moteur CORE. Il expose un
statut local et refuse actuellement **toute** génération. Sans poids, l'état est
`awaiting_local_weights`; si un fichier est détecté, l'état devient
`weights_detected_runtime_disabled`, car aucun chargeur, tokenizer ni décodeur
autorégressif n'est encore activé. Aucun fallback distant, GPU ou téléchargement
automatique n’est permis.

Le candidat `CORE-80M` reste une configuration d’architecture, pas un modèle
prêt à charger. L’implémentation complète attend le tokenizer, le corpus, des
poids linguistiques validés, la génération, le mini-benchmark et la politique
de précision définis aux gates correspondants. Le champ déclaratif
`network=disabled` décrit le contrat du runtime ; il ne remplace pas la preuve
de segmentation réseau exigée par le gate d'architecture.
