---
slug: questions-recurrentes-clients
title: "Répondre aux questions récurrentes des clients avec une base de réponses validées"
themes: [relation_client, outils, social]
summary: "Constituer une base de 30 réponses validées par le cabinet et l'utiliser avec un modèle pour rédiger des réponses personnalisées, sans jamais répondre hors de la base."
duration: "2 heures de mise en place, puis 2 minutes par réponse"
tools: "document partagé (base de réponses) ; modèle de langage ; messagerie"
---
**Le problème.** « Puis-je déduire mon véhicule ? », « Quand dois-je payer la TVA ? », « Comment embaucher un apprenti ? » : les mêmes trente questions reviennent, et chaque collaborateur y répond différemment.

**Le workflow.**

1. Pendant deux semaines, noter toutes les questions reçues (mail, téléphone, rendez-vous). Garder les 30 plus fréquentes.
2. Pour chacune, écrire une réponse validée par un expert-comptable du cabinet : 5 à 10 lignes, datée, avec la source et les cas où il faut « demander au cabinet ». C'est la base de réponses. Elle vit dans un document partagé, revu tous les trimestres.
3. Quand une question arrive, coller la réponse validée correspondante et la question du client dans le prompt ci-dessous.
4. Relire la réponse produite (le modèle adapte le ton et la forme, pas le fond), l'envoyer, et consigner la question si elle n'était pas dans la base.
5. Si la question sort de la base : pas de génération. Un professionnel répond, et la base s'enrichit.

**Le prompt prêt à copier.**

```text
Tu es assistant dans un cabinet d'expertise comptable français. Rédige une réponse par
email à la question du client ci-dessous en t'appuyant UNIQUEMENT sur la réponse validée
par le cabinet. Contraintes : vouvoiement, 150 mots maximum, ton chaleureux et précis,
reprendre les éléments de la réponse validée sans en ajouter, terminer par une invitation
à appeler le cabinet si la situation du client présente une particularité. Si la question
du client dépasse le périmètre de la réponse validée, écris seulement :
« HORS BASE : à traiter par un professionnel » et rien d'autre.

Question du client : {colle la question, sans données sensibles}
Réponse validée par le cabinet (date, source) :
{colle la fiche de la base}
```

**Ce qu'il faut garder en tête.**
- Le modèle reformule, il ne répond pas sur le fond : la base est la seule source autorisée.
- Dater les fiches : une réponse sur un seuil de TVA de l'an dernier est une erreur en attente.
- Mesurer le temps de réponse moyen avant/après : c'est l'argument le plus concret pour l'équipe.
