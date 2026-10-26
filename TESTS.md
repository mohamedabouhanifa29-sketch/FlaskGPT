# Validation

## Tests automatisés

Dernière exécution locale : **34 tests réussis en 18,88 secondes**, sur Python 3.11 avec le SDK Groq 0.37.1.

Périmètre : persistance et migrations SQLite, isolation des conversations, CSRF, domaines, réglages des sources, lignes/paragraphes, uploads PDF/XLSX/CSV, imports SQLite, profils et règles, requêtes en lecture seule, exports et résumé, notes, mesures, erreurs de fournisseur et déconnexion.

Les tests du streaming utilisent le vrai client SDK avec httpx.MockTransport pour vérifier à la fois sa signature et les trames SSE. Les erreurs de modèle introuvable (404) et de paramètres refusés (400) sont couvertes. Les données sont fictives et temporaires ; aucun appel réseau ou secret n'est requis par cette suite.

## Vérification réelle séparée

Une réponse courte a été vérifiée via Flask puis dans un navigateur avec un modèle disponible du compte Groq : réponse terminée, texte et compteurs de tokens reçus. Aucun document ni conversation personnelle n'a été utilisé pour ces essais. Les vérifications réelles ne font pas partie de la suite automatique.

## Limites

Aucun test de charge, audit de sécurité indépendant, certification réglementaire, essai de base distante ou déploiement public n'a été réalisé. Le résumé PDF est extractif ; la vérification des citations contrôle les références et non la vérité des affirmations.
