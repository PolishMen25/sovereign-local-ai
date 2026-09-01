# ADR-0003 — Modèle de chat bootstrap séparé de CORE

- Statut : **ACCEPTÉ pour démonstration CLI locale**
- Date : 2026-09-01
- Autorité : propriétaire du projet

## Contexte

CORE-80M est créé dans ce projet mais ne possède encore ni corpus approuvé, ni
tokenizer final, ni poids linguistiques. Le propriétaire demande un chat local
réel utilisable sans présenter un micro-modèle mémorisé comme un assistant
général.

## Décision

Un modèle tiers instruct quantifié est autorisé temporairement sous le nom
**BOOTSTRAP**, strictement séparé de CORE : Qwen2.5-1.5B-Instruct GGUF Q4_K_M,
exécuté sur CPU avec llama.cpp. Les versions, tailles, licences et SHA-256 sont
verrouillés dans
`configs/runtime/bootstrap-qwen2.5-1.5b-q4km.lock.json`.

L'acquisition a lieu hors du futur domaine IA-CORE. Les fichiers sont vérifiés
avant et après transfert. Le runtime ne télécharge rien. La première utilisation
est une CLI via SSH, sans service persistant, port supplémentaire, outil, agent,
RAG ou journalisation des prompts.

## Limites

- BOOTSTRAP n'est pas CORE et ne doit jamais être présenté comme un modèle créé
  par ce projet ;
- ses poids proviennent d'un tiers et conservent les limites et risques du
  fournisseur ;
- cette démonstration ne valide aucun gate G3 à G7 ;
- les conversations privées ne deviennent ni corpus ni connaissance validée ;
- une exposition Web ou LAN exige toujours la décision réseau, l'identité et les
  tests d'isolation prévus.

## Retour arrière

Arrêter toute CLI en cours puis retirer le dossier bootstrap dédié. Aucun format
de données CORE, checkpoint CORE ou catalogue Knowledge ne dépend de ce modèle.
