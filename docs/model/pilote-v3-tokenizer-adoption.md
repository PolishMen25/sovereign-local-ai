# Pilote-v3 — adoption contrôlée du tokenizer 32k

## Objet et état

Le pilote-v3 est un corpus technique bilingue matérialisé hors Git. Son manifeste
de déploiement a été relu par le validateur de manifeste et son contrat tokenizer
déclare UTF-8, `unicode-nfc-v1`, un vocabulaire candidat de 32 000 et un état de
revue `approved`. Il constitue l'autorisation d'entraînement dès lors que les
empreintes de ses splits correspondent aux octets lus.

Les empreintes rapportées et relues sur la cible de calcul sont :

| Élément | SHA-256 |
| --- | --- |
| Manifeste pilote-v3 | `d92478f0d4db0b9c85819130a28217599ddfcd60572b5934268ef8aed8eb1964` |
| Split `train` (228 860 719 octets) | `1875f4c573956ccf7b555768031c4628603cc0572c1e7bc0d6adb0b9875865d6` |
| Split `test` (27 378 212 octets) | `ceb608c3a2916671ca1a0715bc867e96da57482f8ac772c276d17db99aa483fd` |
| Split `validation` (17 521 350 octets) | `42019c5d0093a5ecb7b50f4c9199421ca78020ba3fa7448c795392a69a37047f` |

Les splits sont des JSONL stricts : une ligne contient uniquement `record_id` et
`text`. La provenance, les licences et les décisions restent dans le manifeste
et dans les reçus d'acquisition ; elles ne sont pas recopiées dans chaque ligne
d'entraînement.

## Compatibilité avec le gate de cette branche

CC-BY-4.0 est autorisée pour ce pilote avec conservation obligatoire de la
provenance et de la licence dans le manifeste. CC-BY-SA reste refusée. Le
préflight exige le manifeste validé, les empreintes exactes et le tokenizer lié
au split `train`; il ne dépend plus du fichier historique `.approved.json`.

## Optimisation Byte-BPE à sortie inchangée

La représentation interne de `train_byte_bpe` a été remplacée par des symboles
entiers chaînés, un comptage local des paires et un tas paresseux. Les règles de
sortie restent inchangées : normalisation NFC, seuil de fréquence, limite de
64 octets, départage lexicographique et fusions gauche-droite non recouvrantes.

Sur la cible de calcul, la preuve a comparé l'ancien algorithme de référence et
la nouvelle implémentation : 213 comparaisons, zéro divergence, y compris les
chevauchements (`aaa`, `aaaa`, `aaaaaaaaa`), égalités, UTF-8 et plusieurs
documents. Les tests locaux conservent un témoin indépendant de ces règles.

La lecture de corpus est bornée à 512 Mio par lancement ; chaque enregistrement
reste borné à 1 Mio et le nombre total à un million. Cette hausse couvre le split
`train` de pilote-v3 sans assouplir les autres limites. Elle ne modifie ni les
gates de provenance ni l'interdiction d'accès Internet de CORE.
