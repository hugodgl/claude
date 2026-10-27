---
slug: lettre-de-mission
title: "Mettre à jour la lettre de mission pour dire ce que l'IA fait (et ne fait pas)"
themes: [reglementation, relation_client, revision]
summary: "Une clause type « outils d'intelligence artificielle » et le prompt pour l'adapter au cabinet, à faire valider par le conseil habituel du cabinet."
duration: "une heure, une fois"
tools: "traitement de texte ; modèle de langage ; relecture juridique"
---
**Le problème.** Les cabinets utilisent déjà des outils d'IA (pré-saisie, OCR, assistants de rédaction, analyse de balance) sans que la lettre de mission en dise un mot. Le client a le droit de savoir comment son dossier est traité ; le cabinet a intérêt à écrire qui relit et qui signe.

**Le workflow.**

1. Lister les outils effectivement utilisés sur les dossiers : nom, éditeur, ce qu'il fait, où sont traitées les données (France, UE, hors UE), s'il sert à l'entraînement du fournisseur.
2. Décider de la règle du cabinet : quelles données peuvent être soumises à un outil externe, lesquelles jamais (pièces d'identité, données de santé, données bancaires nominatives).
3. Générer une première clause avec le prompt ci-dessous.
4. La faire relire par le conseil habituel du cabinet (avocat, assureur RC pro) et la confronter aux recommandations de l'Ordre. Ce numéro n'est pas un avis juridique.
5. Insérer la clause dans le modèle de lettre de mission et dans la note d'information RGPD ; prévenir les clients existants par un avenant ou un mail d'information.

**Le prompt prêt à copier.**

```text
Tu es juriste rédacteur pour un cabinet d'expertise comptable français. Rédige une clause
« Recours à des outils d'intelligence artificielle » destinée à une lettre de mission
(norme professionnelle de l'Ordre des experts-comptables), en français juridique clair,
250 mots maximum, structurée en 4 points : (1) le cabinet peut recourir à des outils
d'automatisation et d'intelligence artificielle pour la tenue, la révision et la
rédaction ; (2) chaque travail issu de ces outils est relu, validé et signé par un
professionnel du cabinet qui en conserve la responsabilité ; (3) les données du client
sont traitées conformément au RGPD, avec la liste des catégories de données exclues
de tout outil externe ; (4) le client peut demander la liste des outils utilisés et
s'opposer à l'usage d'outils externes pour son dossier, avec les conséquences éventuelles
sur les délais. Ne cite aucun texte de loi que tu ne connais pas avec certitude ;
écris [À VÉRIFIER] à la place.

Outils utilisés par le cabinet : {liste : nom, fonction, localisation des données}
Données exclues de tout outil externe : {liste}
```

**Ce qu'il faut garder en tête.**
- La clause protège surtout en expliquant : qui relit, qui signe, ce qui ne sort jamais du cabinet.
- Un outil local (Ollama sur un Mac du cabinet) simplifie le point 3 : aucune donnée ne quitte les locaux.
- À revoir à chaque nouvel outil. Tenir la liste à jour dans le registre des traitements.
