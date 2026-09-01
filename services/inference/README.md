# Runtime d’inférence local

`runtime.py` fixe la frontière CPU-only du futur moteur CORE. Il expose un
statut local et refuse actuellement **toute** génération. Sans poids, l'état est
`awaiting_local_weights`; si un fichier est détecté, l'état devient
`weights_detected_runtime_disabled`, car aucun chargeur, tokenizer ni décodeur
autorégressif n'est encore activé. Aucun fallback distant, GPU ou téléchargement
automatique n’est permis.

`model.py` contient désormais la définition commune du decoder CORE utilisée
par le harness d'entraînement et destinée au futur runtime. Elle préserve les
noms et formes des poids existants, exige les embeddings liés, vérifie le
comptage et refuse un build CUDA/ROCm ou un runtime CUDA actif.

`tokenizer.py` charge et valide le format Byte-BPE expérimental `0.2.0`. Il
partage avec l'outil d'apprentissage la normalisation NFC et l'application des
fusions ordonnées. Son état validé est immuable et ses entrées sont bornées.
Cette capacité permet de tester un aller-retour texte/tokens ; elle n'autorise
pas encore le chargement de poids linguistiques ni la génération.

Le candidat `CORE-80M` reste une configuration d’architecture, pas un modèle
prêt à charger. L’implémentation complète attend le tokenizer, le corpus, des
poids linguistiques validés, la génération, le mini-benchmark et la politique
de précision définis aux gates correspondants. Le champ déclaratif
`network=disabled` décrit le contrat du runtime ; il ne remplace pas la preuve
de segmentation réseau exigée par le gate d'architecture.
