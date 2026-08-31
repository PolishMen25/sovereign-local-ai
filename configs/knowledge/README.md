# Catalogue RAG de préparation

`catalogue.synthetic.jsonl` est un catalogue **synthétique** de trois notices,
préparé uniquement pour tester le MCP Knowledge. L’interface Web n'est pas
encore reliée à ce catalogue. Il ne contient
ni conversation réelle, ni secret, ni chemin d’infrastructure.

Chaque ligne conserve un `document_id`, un résumé borné et un
`provenance_id`. Ce fichier n’est pas une promotion automatique des données
RAW : un catalogue de production devra être généré par une décision de
validation, avec manifeste, empreintes, ACL et audit séparés.
