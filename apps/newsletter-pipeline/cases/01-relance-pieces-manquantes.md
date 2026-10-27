---
slug: relance-pieces-manquantes
title: "Relancer les pièces manquantes en vingt minutes au lieu de deux heures"
themes: [tenue, relation_client]
summary: "Transformer l'export « pièces manquantes » du logiciel de tenue en mails de relance personnalisés, relus avant envoi."
duration: "20 minutes par semaine après mise en place"
tools: "n'importe quel modèle (Ollama local, Claude, ChatGPT Team) ; tableur ; messagerie"
---
**Le problème.** Chaque semaine, un collaborateur passe une à deux heures à relancer les clients pour les relevés, factures et justificatifs manquants. Les mails sont répétitifs, parfois secs, souvent oubliés.

**Le workflow (une fois par semaine, le jeudi matin).**

1. Exporter depuis le logiciel de tenue la liste des pièces manquantes par dossier (CSV : client, période, type de pièce, montant si connu, date de première demande).
2. Ouvrir le tableur, supprimer les colonnes inutiles, garder une ligne par pièce. Ne jamais coller de données au-delà de ce qui est nécessaire (pas d'IBAN, pas de numéro de sécurité sociale).
3. Coller la liste d'un client dans le prompt ci-dessous. Un prompt par client, c'est plus fiable qu'un prompt pour tout le portefeuille.
4. Relire le mail produit (30 secondes), ajuster le ton si le client est fragile, envoyer depuis la messagerie du cabinet.
5. Noter la date de relance dans le tableur : à la troisième relance, c'est le chef de mission qui appelle.

**Le prompt prêt à copier.**

```text
Tu es assistant dans un cabinet d'expertise comptable français. Rédige un email de relance
pour les pièces manquantes ci-dessous. Contraintes : vouvoiement, ton cordial et ferme,
120 mots maximum, une liste à puces des pièces avec la période concernée, une phrase qui
rappelle pourquoi on en a besoin (clôture, TVA, bilan), une proposition concrète pour
envoyer les pièces (réponse à cet email, dépôt dans l'espace client, photo depuis le
téléphone). Pas de formule menaçante, pas de jargon. Signe « L'équipe du cabinet ».
Niveau de relance : {première | deuxième | troisième}.

Client : {prénom du dirigeant}, {société}
Pièces manquantes :
{colle ici les lignes du tableur : type de pièce ; période ; montant éventuel}
```

**Variante pour la troisième relance.** Ajouter : « Indique que sans ces pièces avant le {date}, la déclaration de TVA sera déposée sur la base des éléments disponibles, avec régularisation ultérieure. » Faire relire par le chef de mission.

**Ce qu'il faut garder en tête.**
- Le modèle ne connaît pas le dossier : il rédige, il ne décide pas. La liste des pièces vient du logiciel, pas de l'IA.
- Données personnelles : prénom et nom de société suffisent. Avec un modèle local (Ollama), rien ne sort du cabinet.
- Mesurer : nombre de pièces reçues dans les 7 jours avant/après. Si le taux ne bouge pas, le problème n'est pas le mail, c'est le canal (passer à l'appel ou au dépôt par photo).
