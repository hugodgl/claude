---
type: audit
status: brouillon
projet: SaaS Certificats Acier
provenance: claude (session cloud du 27/10/2026, sans accès au dépôt)
tags: [eryon-certif, interface, demonstration, commercial, socle-technique, ai-generated]
created: 2026-10-27
---

#ai-generated

# Audit du logiciel : plus vendeur, plus parlant, plus simple (27/10/2026)

> **Demande de Hugo, 27/10/2026.** « Une analyse complète de mon logiciel, celui que je présente en démo et que j'ai refait il n'y a pas longtemps : tous les changements à faire pour qu'il soit plus vendeur, plus parlant, plus simple d'utilisation, au niveau technique, visuel, et le code, si tout le code va bien. »
>
> **Ce que j'ai regardé.** La capture de `Classeur › Certificats matière` envoyée le 27/10 (instance 8813, branche `refonte-tout-en-un`), et dix-sept notes du coffre : le check-up du 25/10, l'analyse bugs, marché et ludique du 25/10, les limites connues, les correctifs du moteur, les réponses techniques de référence, les 5 chiffres, le verdict app de bureau, le nom du logiciel, les engagements clients, les deux notes commerciales du 27/10, la procédure de démo du 03/11, le README GitHub, le README du socle technique, la note d'entrée du produit, le README de la démonstration visuelle, plus le texte de cinq écrans de la maquette tout en un.
>
> **Ce que je n'ai pas regardé : le code.** Il vit dans `~/eryon/poc-cert-acier-souverain` sur ton Mac, et cette session tourne dans un conteneur cloud qui ne peut pas atteindre ta machine. Tout ce qui concerne le code ici vient des notes, avec leur date, pas d'une lecture du dépôt. La section 08 dit comment me le donner.
>
> **En bref.**
>
> 1. **Le logiciel n'est pas ce qui bloque la vente.** Treize rendez-vous, zéro signature, et les prospects ont dit pourquoi : volume trop petit, décideur absent, pas de référence. Ta note du 27/10 conclut « geler le produit jusqu'à la première signature ». Je suis d'accord, avec une seule nuance : **deux jours sur ce qui se voit en démo**, pas un de plus, puis plus rien tant que personne n'a signé.
> 2. **Sur l'écran du 27/10, cinq choses coûtent de la crédibilité en moins de dix secondes** : la colonne « Fiabilité » vide sur dix lignes, le verdict « Refusé » sans sa raison, le même fournisseur écrit de deux façons, deux barres de recherche, et le logo d'une société de conseil à la place d'un nom de produit. Aucune ne demande plus d'une demi-journée.
> 3. **Le check-up du 25/10 a déjà le bon plan** (lots A, B, C). Trois choses n'y sont pas et comptent en démo : le « pourquoi » du verdict dans la liste, un jeu de démonstration qui raconte une seule histoire d'un écran à l'autre, et une phrase de confidentialité qui dit partout la même chose (la note du menu dit aujourd'hui l'inverse de l'accueil).
> 4. **Techniquement, le dépôt est mieux tenu que la plupart des produits de cet âge** : 2 611 contrôles, 72 pages passées au robot, versions épinglées, journal d'audit, mises à jour signées, mesures honnêtes. Mais quatre choses restent dangereuses pour un premier client : le démon moteur qui s'arrête sous charge sur 16 Go (17 documents sur 22 perdus en silence le 16/09), la connexion par HTTP Basic sans page de connexion ni déconnexion, les dépendances à failles connues avec des en-têtes de sécurité absents, et **le code qui n'existe que sur ton Mac** : le plan GitHub du 03/10 n'a jamais été lancé.
> 5. **« Est-ce que tout le code va bien ? »** Je ne peux pas le dire sans le lire. Ce que les notes disent : oui pour la méthode, non pour plusieurs défauts ouverts qui touchent ce qu'on vend (trois mentions du moteur jamais affichées sur la fiche, garde-fou « lecture non fiable » contourné au réenregistrement, correctifs présents sur `qualification` mais absents de `main` et des paquets). Donne-moi le dépôt et je te rends une revue fichier par fichier.

---

## 01. L'écran du 27/10, ligne par ligne

Ce que je vois sur la capture, ce qu'un prospect en déduit, et ce que je changerais. Les efforts sont des ordres de grandeur pour quelqu'un qui connaît le dépôt.

| # | Ce que je vois | Ce qu'un prospect en déduit | Correction | Effort |
|---|---|---|---|---|
| 1 | **Colonne « Fiabilité » vide sur les dix lignes.** Règle actuelle d'après le check-up : affichée seulement sous 80 % | « Une colonne cassée », ou « pas fini » | Deux options, jamais « laisser vide ». Soit toujours remplie, en trois mots plutôt qu'un pourcentage (« Sûre », « À relire », « Illisible »). Soit retirée de la liste, l'information restant sur la fiche et dans le verdict « À vérifier ». Ma préférence : la retirer de la liste | 1 h |
| 2 | **« REFUSÉ » sans la raison.** La fiche et la page À décider l'ont (« Carbone 0,34 % pour 0,17 % maximum, et 3 autres écarts »), la liste non | Il faut ouvrir pour comprendre ; en démo, c'est un clic de trop, et c'est la seule chose qu'un responsable qualité veut lire | Une ligne grise sous le badge avec l'écart principal, le détail au survol. C'est ce qui montre que le logiciel contrôle, pas qu'il range | 2 h |
| 3 | **« Acierie Demo A » ligne 3 et « ACIERIE DEMO A » ligne 5** | « Il ne reconnaît pas le même fournisseur » : l'argument traçabilité tombe, et les statistiques par fournisseur avec | Normaliser la casse à l'affichage tout de suite ; une entité fournisseur plus tard | 1 h |
| 4 | **Deux barres de recherche** aux textes presque identiques, plus un bouton « Filtres » isolé | Laquelle utiliser ? | Garder la recherche ⌘K. La barre de page devient des puces de filtre cliquables : Conformes 7 · Refusés 2 · À vérifier 1 · Attendus 4 | 1 h |
| 5 | **« 5 fiches vérifiées sur 10 »** à côté d'un seul badge « À vérifier » | Vérifiées par qui ? Et pourquoi 5 et pas 1 ? | « 1 à vérifier · 5 validées par un contrôleur », ou simplement les puces du point 4 | 30 min |
| 6 | **Les chiffres ne se recoupent pas** : menu « À décider 9 », « Relances 4 », liste de 10 avec 7 conformes, 2 refusés, 1 à vérifier | Un acheteur additionne de tête et ne retombe pas sur ses pieds | Un jeu de démonstration où chaque chiffre s'explique (3.2). C'est le bug n° 1 du 25/10, toujours visible | 2 h |
| 7 | **Logo « ERYON CONSULTING » en tête**, onglet « Certificats matière », entrée de menu « Ce que fait le logiciel » | « C'est l'outil d'un consultant », et pas de nom à répéter à son directeur | Tant que le nom n'est pas choisi : « Certificats matière » en tête, comme l'app installable du 12/10, « par Eryon Consulting » en petit dessous, et « Ce que fait le logiciel » dans l'aide (il y reste accessible en présentation) | 1 h |
| 8 | **« Certificats lus ici. Documents de production lus en ligne. »** en bas du menu | « Lus en ligne, par qui, où ? » C'est la crainte numéro un des dirigeants de PME (France Num : 52 %), et l'objection exacte d'Armor Méca, Haghebaert & Fremaux et ATS Laser | La phrase de l'accueil (« Lu sur ce boîtier. Rien ne sort de l'entreprise. »), vraie partout où elle s'affiche, et la vérité sur les documents de production dans une page « Vos données » (3.5) | 30 min |
| 9 | **« À jour à 20 h 07 · Plus »**, **« Exporter vers Excel » + « Autres sorties ▾ »** | À jour de quoi ? « Plus » ouvre quoi ? « Sorties » est un mot de l'équipe, pas du client | « Dernière lecture : 20 h 07 » ; un seul bouton « Exporter ▾ » avec Excel, CSV, PDF | 1 h |
| 10 | **« 4.0 mm »**, **« 25/10, 19:14 »**, année absente sur les lignes anciennes | Point décimal anglais à côté de « 20 h 07 » à la française ; un contrôleur le remarque | « 4,0 mm », « 25 oct. 19:14 », date complète au survol | 1 h |
| 11 | **Dix boutons « Ouvrir »**, pas de case à cocher, pas de colonne Commande ou BL | Clics inutiles, pas d'action groupée, traçabilité invisible depuis la liste | Ligne cliquable avec chevron, cases et actions groupées (valider, exporter, dossier FAI), colonne Commande | après signature |
| 12 | **Chasse fixe** sur les badges, les compteurs du menu et l'horodatage ; **badges en majuscules** ; **ambre de marque** identique à l'ambre « À vérifier » | Look « outil de développeur » plutôt que logiciel métier ; l'entrée de menu active ressemble à une alerte, le bouton principal à un avertissement | Chasse fixe réservée aux identifiants (n° de certificat, coulée) ; badges en casse normale avec leur icône ; état actif du menu en gris, l'or gardé pour le seul bouton « Déposer » | après signature |
| 13 | **Safari avec les onglets personnels**, « 127.0.0.1 » dans la barre d'adresse | Hygiène de démo | L'app installable faite le 12/10 (Safari › Fichier › Ajouter au Dock) donne une fenêtre sans barre d'adresse : s'en servir pour les démos | 0 |

Les points 1 à 10 font environ douze heures de travail. C'est le périmètre des « deux jours » de la section 07.

---

## 02. Ce qui est déjà bon, à ne pas casser

1. **Le vocabulaire métier** : Classeur, Coulée, Nuance, Dossiers FAI, Relances, À décider. Aucun concurrent regardé le 25/10 ne montre l'usine entière aussi lisiblement ; c'est ton point fort « parlant ».
2. **Le verdict avec la valeur, la limite et la clause** sur la fiche, le document d'origine à côté, « Voir dans le document ». C'est la preuve, et c'est ce qui convainc.
3. **Déposer d'un geste**, toujours au même endroit, et le volet qui suit la lecture étape par étape (vérifié le 25/10 : 2 min 04 du dépôt au classement).
4. **Les règles de contrôle en trois gestes**, avec « Tester sur mes certificats » avant d'enregistrer : le moment le plus fort de la démo du 03/11.
5. **La recherche ⌘K** sur tous les identifiants.
6. **Les verdicts à trois niveaux** avec icône et couleur, lisibles sans la couleur.
7. **Le mode Présentation, le mode sombre, l'app installable** : rares dans un logiciel métier.
8. **Un seul bouton doré par écran** : le lot A du 25/10 est visiblement passé par là.
9. **La discipline technique** : versions épinglées, test §44 qui refuse toute dépendance non épinglée, journal d'audit avec valeur avant et après, mises à jour signées avec retour arrière, mesures datées et avouées (« le produit ne lit pas mieux que son modèle, il sait mieux quand se taire »).

---

## 03. Plus vendeur

### 3.1 Le logiciel n'est pas ce qui bloque, et la seule conséquence qui compte

Le constat est dans tes deux notes du 27/10, je le résume en quatre lignes : 673 entreprises contactées, 13 premiers rendez-vous, 4 à 5 seconds, 0 diagnostic signé. Les causes données par les prospects eux-mêmes : 50 à 80 certificats par mois là où l'abonnement en demande près de 200 pour se rembourser, un interlocuteur qualité qui ne signe pas, aucune référence, 2 500 € demandés avant la preuve, des promesses au-delà du produit (écriture ERP, FAI, relance automatique, manuscrit), des prix dits à l'oral hors grille. Les remèdes y sont aussi : offre client fondateur datée, lecture gratuite de 20 documents réels avant toute signature, qualifier le volume avant la démo, vendre le risque évité plutôt que les minutes, pas de second rendez-vous sans le décideur, ne montrer que ce qui existe, une date et une décision demandée à chaque fin de rendez-vous, et geler le produit.

Je n'ai rien à y ajouter, sauf ceci : **l'écran pèse dans les dix premières secondes et pendant les cinq minutes de démo, pas au-delà.** Donc deux jours sur l'écran (section 07), avant Biogroupe le 30/10 si possible, avant Léo François le 03/11 sinon. Ensuite, plus une ligne de code tant que personne n'a signé, sauf un bug qui casse une démo.

### 3.2 Le jeu de démonstration raconte une seule histoire

Le jeu du 03/11 (D conforme, E refusé sur Re 401 pour 420, F conforme, G scanné avec tampon) est juste pour Léo François : des bobines, sa matière, lus en vrai par le moteur. Ce que je changerais, pour ce jeu et pour celui de l'instance 8813 :

1. **Chaque chiffre du menu s'explique par la liste.** Si le menu dit « À décider 9 », la page À décider montre 9 lignes et l'accueil dit « 9 documents attendent votre décision ». Une seule définition du chiffre, celle du check-up : les documents qui attendent une décision, jamais les commandes incomplètes additionnées.
2. **Des fournisseurs crédibles, une seule casse.** « Aciéries de Moselle », « Négoce Métal Rhône », « Laminoirs du Nord », « Inox Service Lyon » plutôt que « ACIERIE DEMO B » et « FOURNISSEUR B ». Aucun nom réel, la mention « SPECIMEN » en pied de page reste, et un seul bandeau discret « Données de démonstration » sur l'accueil suffit.
3. **Une histoire de bout en bout** : une commande client, un BL, trois certificats, un refusé avec sa raison, une relance préparée, un certificat de remplacement reçu « hier », un « à vérifier » sur un scan que tu valides en direct, puis l'export Excel. Le prospect doit pouvoir la raconter à son directeur le soir même.
4. **G refabriqué** avec le tampon dans une zone vide (méthode de MTR-2026-10788 J, 18 valeurs sur 18 le 22/10), ou jamais ouvert : la note du 03/11 le dit déjà, je le répète parce que c'est la fiche qu'un prospect curieux ouvrira.

### 3.3 Le déroulé de cinq minutes, et trois ajouts

Le déroulé du 03/11 est bon : À traiter, dépôt de E en direct, fiche de D pendant la lecture, fiche de E refusée avec le PDF à côté, une règle client testée puis annulée, la décision demandée. Trois ajouts, sans rallonger :

| Minute | Ajout | Pourquoi |
|---|---|---|
| 0 | La première phrase est « Rien ne sort de votre entreprise : tout est lu sur ce boîtier. » avant même de montrer l'écran | C'est la crainte numéro un, et c'est l'avantage le plus rare du produit, « sous-exploité dans le discours » selon ta propre note |
| 3 | Sur la fiche de E, cliquer « Voir dans le document » et montrer la valeur surlignée dans le PDF | La preuve vaut plus que le verdict. Vérifier la veille que la mention s'affiche (section 06, ligne 8) |
| 5 | La décision demandée est la lecture gratuite de 20 de leurs documents en 5 jours, pas le diagnostic | « Un premier essai concret avec des documents en live, ce sera déterminant » (Armor Méca). Le pilote se vend après la preuve |

Et deux règles de sécurité qui existent déjà, à garder : répétition la veille sur le code du jour, jamais le matin ; si le démon moteur ne répond pas, rien n'est lu en direct, on montre les fiches déjà lues.

### 3.4 Ce qu'on ne montre pas, ce qu'on ne promet plus, et ce que l'écran ne doit pas laisser croire

Déjà écrit dans tes notes, consolidé ici parce que l'écran lui-même peut trahir :

| Sujet | État réel | Ce que dit l'écran ou la bouche | Ce qu'il faut dire |
|---|---|---|---|
| Documents de production | Lus par une IA en ligne en production | « Documents de production lus en ligne » dans le menu ; « Rien ne sort de l'entreprise » sur l'accueil | Pas de démo dessus tant que ce n'est pas local ; une seule phrase vraie partout (3.5) |
| Relance fournisseur | BR-14 jamais mise en service : la relance est préparée, pas envoyée | « Relances fournisseurs 4 » dans le menu, « ça relance automatiquement » dit chez Serre | Menu « Relances à envoyer », phrase « relance préparée, envoyée par vous » |
| Dossiers FAI | Dit « automatisé » à Serre, jamais livré ; Serre l'a lui-même écarté | Entrée « Dossiers FAI » dans le menu | Montrer ce qui existe (le dossier affaire), écrire « à valider au pilote » pour le reste |
| Écriture dans l'ERP | Question posée par quatre entreprises sur quatre, jamais de réponse ferme | « Vers votre ERP » dans la maquette | « Établi au diagnostic » ou « à valider au pilote », jamais « faisable » |
| Lecture manuscrite, lecture de plans | Modèle entraîné sur 87 manuscrits, aucun jeu d'évaluation, surcharges manuscrites fragiles | « Faisable » dit à Armor Méca | « Essai sur vos fiches avant de le promettre » |
| Débit | 13 à 51 documents par heure selon les conditions, jamais mesuré sur un Mac mini | Tentation de donner un chiffre | « Un toutes les soixante-dix secondes, sans pause ; nous calibrons à l'installation » |
| Onglet Commandes | Cite un aciériste réel dans l'exemple | | Corriger l'exemple avant d'ouvrir l'onglet |
| Fiche G, certificat démo B | G : valeurs fausses sous le tampon ; B : S235JR lu au lieu de S235JRH | | Ne pas ouvrir, ou refabriquer |

### 3.5 La confidentialité : une seule phrase, vraie partout

Trois formulations coexistent : « Certificats lus ici. Documents de production lus en ligne. » (menu), « Lu sur ce boîtier. Rien ne sort de l'entreprise. » (accueil), et la page « Vos données » écrite le 16/10 pour Haghebaert & Fremaux (propriété, lecture sans IA tierce, fin de contrat). Un prospect qui lit les deux premières dans la même minute retient la contradiction.

Ce que je ferais : la phrase de l'accueil partout où elle est vraie, la page « Vos données » dans le logiciel (Aide › Vos données) et accessible depuis la note du menu, et, pour les documents de production tant qu'ils sont lus en ligne, soit on ne les montre pas, soit la page dit « analysés par [fournisseur], hébergé en [pays], sans conservation », comme l'exige ta réponse technique de référence n° 1. La règle « dans la version boîtier, rien ne sort ; dans la version en ligne, la page part chez tel fournisseur dans tel pays, et je vous le dis avant de signer » est excellente : il faut que l'écran la respecte.

### 3.6 Le nom

La décision est ouverte depuis le 30/09 (favori : Équerre, « vos documents, d'équerre » ; second : Jauge sous réserve de l'avocat ; ERYON déposé par un tiers en classe 42). Tant qu'elle n'est pas prise, l'écran ne peut pas montrer le logo de la société de conseil à la place du nom du produit : un prospect ne demande pas de devis pour « Eryon Consulting ». Le titre neutre « Certificats matière » que porte déjà l'app installable fait l'affaire d'ici là. Quand le nom sera choisi : dépôt INPI en classes 9 et 42 pour environ 230 €, puis le renommage en une fois (une vingtaine d'emplacements dans le code, 52 notes du coffre, d'après ta note).

### 3.7 Montrer l'argent et le risque, pas les minutes

Ta note du 27/10 dit « vendre le risque évité ». L'écran peut le porter sans inventer de chiffre :

1. Sur l'accueil, une ligne calculée sur des réglages du client : « Cette semaine : 37 certificats lus, 2 non-conformités arrêtées avant usinage, environ 6 h de saisie évitées ». Le temps par certificat est celui que le client a donné en rendez-vous, jamais un chiffre à nous (proposition 4 du 25/10).
2. Dans Analyse, un bulletin des fournisseurs (certificats conformes, complets, arrivés à temps, tendance sur trois mois) : il intéresse les achats, et un acheteur est souvent dans la salle (proposition 6 du 25/10).
3. En rendez-vous, le coût d'une matière non conforme partie en production : retour client facturé 150 à 350 € (chiffre de DEPRECQ), audit, livraison bloquée. Le temps gagné devient le bonus.

### 3.8 Après le rendez-vous

Ce qui existe : la vidéo du vrai logiciel sur certificats fictifs (1 min 42), le cas d'usage anonymisé, la page « Vos données », l'hébergement chez Eryon autorisé pour démo et essai. Ce qui manque : une adresse de démonstration stable, réinitialisée chaque nuit, que le prospect peut rouvrir devant son directeur. C'est la seule pièce qui remplace une référence qu'on n'a pas encore, avec les vidéos LinkedIn de 60 secondes prévues dans ta note.

---

## 04. Plus simple : où en est le plan du 25/10, et ce que j'y ajoute

### 4.1 Ce que la capture du 27/10 permet de constater

| Proposition du check-up du 25/10 | Vu le 27/10 |
|---|---|
| Un seul bouton doré par écran | Fait sur le classeur : « Déposer » seul |
| Actualiser, Recharger, MAJ, Auto 5min retirés, ligne « à jour à » | Fait : « À jour à 20 h 07 » |
| Badge « 30 » retiré de « Ce que fait le logiciel » | Fait |
| Une seule recherche par écran | Pas fait : deux barres |
| « 4 à vérifier » plutôt que « restent à relire » | Pas fait : « 5 fiches vérifiées sur 10 » |
| « Ce que fait le logiciel » dans l'aide | Pas fait : toujours dans le menu |
| Mots techniques et note du menu remplacés | Pas fait : la note « lus ici / lus en ligne » est là |
| Traçabilité comme vrai écran, menu en trois groupes | Pas vérifiable sur la capture |
| Le geste « décidé » (lot C) | Pas vérifiable ; à trancher (4.2) |

### 4.2 Le geste « décidé » : ma recommandation sur tes quatre questions

C'est le point le plus important du check-up, et je le confirme de l'extérieur : « et là, je fais quoi ? » est la première question d'un visiteur devant une liste rouge, et une liste qui ne se vide jamais ne vaut rien au bout d'un mois.

1. **Les trois réponses** (Refuser la matière, Accepter par dérogation avec motif, Corriger une valeur lue) : oui. La dérogation réservée à l'administrateur, motif obligatoire, visible dans le rapport PDF. C'est ce qu'un auditeur ISO 9001 demande au chapitre 8.7 sur les éléments de sortie non conformes.
2. **Le mot rouge** : séparer le verdict du moteur et la décision de l'humain, parce que « le verdict n'est jamais produit par l'IA » est ton positionnement. Le moteur dit « Non conforme », « Conforme », « À vérifier », le mot habituel d'un service qualité et celui des rapports et des règles. L'humain décide « Refusé », « Accepté par dérogation » ou « Corrigé ». Aujourd'hui « Refusé » sert de verdict, ce qui mélange les deux. Avec cette séparation, le badge de la liste montre le verdict, et la décision s'affiche à côté quand elle est prise.
3. **Le circuit sur l'accueil** : la bande compacte, oui. C'est le point fort « parlant » de l'analyse marché, il doit rester visible au quotidien, pas seulement en présentation.
4. **L'ordre des lots** : A, B, C. Si C ne tient pas avant le 03/11, montrer « Marquer relu » et dire « la décision signée arrive au pilote », ce qui est vrai.

### 4.3 Ce que j'ajoute aux lots A à F

1. **La raison du verdict dans la liste** (point 2 de la section 01).
2. **Lignes cliquables, cases à cocher, actions groupées** : en démo, sélectionner trois certificats et sortir un dossier est un moment fort.
3. **« Validé par » et la date** sur la fiche et dans la liste, à partir des comptes et du journal qui existent déjà : la traçabilité des décisions est une exigence d'audit, et personne ne la voit à l'écran.
4. **La mise en route en six missions** (proposition 5 du 25/10) après la signature : c'est la réponse au « opérationnel en un jour, sans manuel » du concurrent le plus proche.
5. **Le mode rafale au clavier** (proposition 3 du 25/10) après la signature : c'est là que naît le plaisir d'utilisation, et c'est le geste le plus fréquent.

---

## 05. Visuel

Rien ici ne bloque une vente ; à faire après la signature, en une journée.

1. **Typographie** : la chasse fixe uniquement pour les identifiants. Partout ailleurs elle donne un air d'outil de développeur à un logiciel destiné à des responsables qualité.
2. **Badges** : casse normale, icône gardée (« ✓ Conforme »). Les icônes rendent le verdict lisible sans la couleur, c'est bien, ne pas y toucher.
3. **Couleur** : l'or de la marque pour le seul bouton principal ; l'état actif du menu en gris ; « À vérifier » dans un orange plus franc, distinct de l'or.
4. **Mise en page** : la carte de recherche, le trait et la carte du tableau font trois conteneurs pour une liste, environ 110 pixels perdus ; fusionner recherche, filtres et actions dans la barre d'outils du tableau.
5. **Accessibilité** : textes d'indication des champs en gris trop clair, contraste des badges verts et ambre à vérifier, flèches de tri minuscules, contour de focus clavier à vérifier.
6. **Téléphone** : les deux défauts du check-up (page de production coupée à droite, document qui recouvre le verdict sur la fiche).
7. **Libellés** : « Sorties » devient « Exports », « Analyse » devient « Tableau de bord », « Ce que fait le logiciel » rejoint l'aide.

---

## 06. Technique : « est-ce que tout le code va bien ? »

Je ne l'ai pas lu. Voici l'état d'après les notes, avec leur date, et pourquoi chaque point compte pour un premier client. Chaque ligne est à confirmer dans `git` : les notes elles-mêmes préviennent que les branches bougent vite.

| # | Sujet | État d'après les notes | Pourquoi ça compte | À faire |
|---|---|---|---|---|
| 1 | **Sauvegarde du code** | Le dépôt n'existe que sur ton Mac. Le plan GitHub du 03/10 (organisation privée, `mettre-en-place.sh`, vérification des secrets avant envoi) a été testé en bac à sable, **jamais lancé** | Un disque qui lâche emporte le produit. Et sans dépôt distant, aucune revue depuis le cloud | 10 minutes, cette semaine. Le § 01 du README GitHub dit tout |
| 2 | **Démon moteur tué sous charge** (défaut 1.6, 16/09) | 17 documents sur 22 perdus en silence sur 16 Go avec 9,3 Go de swap. Depuis `qualification` : reprise en file (3 tentatives) et comptage des arrêts. Cause non tranchée | « La liasse du matin », l'usage exact qu'on vend | Mesure sur un Mac mini 32 Go loué (6,96 €, une demi-journée), avant tout boîtier et avant d'annoncer un débit |
| 3 | **Trois lignes de code** | `main` (production du poste, `version.json` resté à 1.27.0), `qualification` (1.28.x, correctifs non fusionnés dans `main`, paquets construits depuis elle, multi-coulées absent des paquets jusqu'à 1.28.7), `refonte-tout-en-un` (l'interface montrée). Trois branches attendent un go : `ancrage-revalidation`, `inox-crni`, `validation-secours` | Une démo ou un boîtier sur un code auquel il manque un correctif connu | Une seule ligne de production et un seul paquet avant le premier client ; les go en attente tranchés |
| 4 | **Connexion** | HTTP Basic, pas de page de connexion ni de déconnexion, certificat auto-signé sans SAN, adresse en chiffres. Verdict du 12/10 : chantiers 2 (1 à 2 jours) et 3 (1 à 3 jours) | « Cette connexion n'est pas privée » devant une DSI est le pire signal pour un produit qui vend la confiance | Après la signature, avant le premier boîtier |
| 5 | **Sécurité du serveur** | Dépendances avec failles connues (Pillow, certifi, aiohttp, filelock, SheetJS), en-têtes de sécurité absents, fichier homonyme écrasé au dépôt. Connus depuis la refonte, toujours ouverts le 25/10 | Le questionnaire sécurité d'un acheteur | Une journée ; puis un contrôle des failles dans le portillon de release, à côté du test §44 |
| 6 | **Documents de production lus en ligne** | En production. L'essai hébergé héritait du moteur en ligne du poste : corrigé en branche, « existe encore en production » (28/09) | Contredit « rien ne sort » | Moteur local seul pour tout ce qu'on montre ; fusionner le correctif |
| 7 | **Précision et référentiel** | 99,3 % sur une famille vue, 84,6 % sur des certificats propres variés, 59 % sur l'inconnu ; 100 % en revue sur le corpus américain (30 normes ASTM absentes) ; doublons du référentiel (ASTM A106, A516, API 5L, P265GH) | Le premier mois d'un client est une déception si on ne prépare pas sa famille de fournisseurs et ses normes | 20 documents réels avant la démo, normes du prospect ajoutées, doublons unifiés |
| 8 | **La fiche** | Trois mentions calculées par le moteur jamais affichées (qualité du scan, page de l'écart, document tronqué : `build_payload` n'envoie pas `extraction_complete`), garde-fou « lecture non fiable » contourné au réenregistrement, avertissements du moteur invisibles (06/10) | C'est la preuve qu'on vend, et « Voir dans le document » est au script du 03/11 | Vérifier sur `refonte-tout-en-un` la veille ; corriger si toujours vrai |
| 9 | **Tests** | Suite Mac 2 611 OK ; robot sur 72 pages, 0 erreur ; mais la matrice des rôles ne teste que les GET (la panne de bascule de secteur a duré depuis la v1.16.0), et un piège sur les écarts chimiques n'a été vu qu'en rejouant 12 vrais documents | | Routes POST couvertes ; un banc de vrais certificats rejoué à chaque paquet, avec des cas en refus |
| 10 | **Verrous et copies** | Reprise d'un verrou orphelin par `rmdir` puis `mkdir` (deux repreneurs possibles) ; verrou périmé corrigé hors `main` ; `shutil.copy` d'une base SQLite en WAL dans `demo_agro.py` | Double traitement d'un lot, sauvegarde corrompue | `flock`, et l'API de sauvegarde de SQLite plutôt qu'une copie de fichier |
| 11 | **Plateforme** | Apple Silicon seulement (portage Windows en cours), un document à la fois, 13 à 51 documents par heure, pas de haute disponibilité, plafond de 8 pages désormais signalé | Ne pas vendre de SLA ni de débit | La mesure à 6,96 € ; le reste s'écrit dans l'offre |
| 12 | **Données et contrat** | Pas de rétention automatique, sauvegarde hors site optionnelle depuis 1.28, accord de sous-traitance signé avec personne, registre des traitements à faire | Le questionnaire RGPD du premier contrat | Avant la première signature, avec l'avocat |
| 13 | **Détails** | `src/regles_client.py` ne compile pas sous Python 3.14 (3.11 épinglée), `second_opinion.py` lit la mauvaise clé (effet prudent, ne promeut jamais), 9 fiches multi-coulées de juillet mal alignées au tableau de bord | | Quand on y passe |

**Ce que je peux dire sans avoir lu le code.** La méthode est sérieuse : les défauts sont trouvés, mesurés, datés et écrits, y compris ceux qui dérangent. Le risque n'est pas la qualité d'une fonction, c'est la **dispersion** : trois branches, des paquets en retard sur les correctifs, des instances d'essai qui héritent de réglages de production, et une seule machine qui porte le code, la production de démonstration, le dépôt de releases et le parc. Les deux actions techniques les plus rentables cette semaine ne sont pas du développement : sauvegarder le dépôt sur GitHub, et décider d'une seule ligne de production avant le premier client.

---

## 07. Plan : deux jours maintenant, le reste après la signature

### Maintenant, deux jours au plus, avant le 03/11

| # | Changement | Effort |
|---|---|---|
| 1 | Colonne « Fiabilité » retirée de la liste (ou toujours remplie) | 1 h |
| 2 | Raison du verdict sous le badge, détail au survol | 2 h |
| 3 | Casse des fournisseurs normalisée | 1 h |
| 4 | Une seule recherche, puces de filtre à la place de la barre de page et du bouton « Filtres » | 1 h |
| 5 | « 1 à vérifier · 5 validées » à la place de « 5 fiches vérifiées sur 10 » | 30 min |
| 6 | Jeu de démonstration cohérent : chiffres qui se recoupent, noms crédibles, une histoire, G refabriqué | 3 h |
| 7 | « Certificats matière » en tête à la place du logo, « Ce que fait le logiciel » dans l'aide | 1 h |
| 8 | Note du menu remplacée par la phrase de l'accueil ; page « Vos données » liée | 1 h |
| 9 | « Dernière lecture : 20 h 07 », un seul bouton « Exporter ▾ » | 1 h |
| 10 | « 4,0 mm », dates françaises | 1 h |
| 11 | Menu « Relances à envoyer », exemple de l'onglet Commandes corrigé | 30 min |
| 12 | Sauvegarde GitHub lancée (§ 01 du README GitHub) | 10 min |
| 13 | Répétition la veille sur le code du jour, fenêtre de l'app installable, « Voir dans le document » vérifié sur E | 30 min |

### Après la première signature, dans le mois

1. Le geste « décidé » (lot C), avec la séparation verdict / décision.
2. Accueil et À décider synthétisés (lot B), menu en trois groupes et Traçabilité à l'écran (lot D).
3. Page de connexion avec session, certificat avec SAN et nom reconnu (chantiers 2 et 3 du 12/10).
4. Dépendances à jour, en-têtes de sécurité, homonymes au dépôt.
5. Une seule ligne de production ; les trois branches en attente tranchées ; mesure sur Mac mini 32 Go.
6. Lignes cliquables, actions groupées, « Validé par », ligne « temps gagné » réglée par le client, bulletin des fournisseurs.
7. Mise en route en six missions, aide dans le logiciel et à jour.
8. Typographie, couleurs, téléphone (section 05).
9. Rétention paramétrable, accord de sous-traitance et registre des traitements relus par l'avocat.
10. Adresse de démonstration stable, réinitialisée chaque nuit.

### Plus tard

Classeur unifié (lot E), Analyse en cinq graphiques (lot F), mode rafale, portage Windows, multi-site, écriture ERP et API, routes POST dans la matrice des rôles, banc de vrais certificats à chaque paquet, usine isométrique en présentation.

---

## 08. Pour la revue de code

Cette session ne peut pas atteindre ton Mac ni `127.0.0.1:8813`. Trois façons de me donner le dépôt, de la plus utile à la plus simple :

1. **GitHub, le plan du 03/10** (10 minutes, et c'est aussi la sauvegarde qui manque). Créer l'organisation, puis sur le Mac : `bash "…/_meta/GitHub/mettre-en-place.sh" eryon-consulting`, qui refuse d'envoyer tant qu'un secret, un document client ou un modèle traîne dans l'historique. Ensuite installer l'application Claude sur l'organisation depuis https://claude.ai/connect-github, et ouvrir une session cloud sur `eryon-certif`. Je peux alors travailler Mac éteint.
2. **Claude Code sur le Mac**, dans `~/eryon/poc-cert-acier-souverain`, comme pour les analyses du 25/10. Consigne à coller :

   > Lis d'abord l'audit du 27/10 (`audit-logiciel-certificats-matiere-2026-10-27.md` dans le dépôt `hugodgl/claude`, ou sa copie dans le coffre). Puis, sur la branche `refonte-tout-en-un`, sans rien modifier : 1. pour chaque ligne de la section 06, dis si c'est encore vrai, corrigé (avec le commit) ou faux ; 2. relis `server_local.py`, `src/validate.py`, `src/local_engine.py`, `auto_ingest.sh` et `updater.sh` pour la sécurité, les verrous, la gestion des erreurs et ce qui part sur le réseau ; 3. liste les routes POST non couvertes par la matrice des rôles ; 4. lance `pip-audit` ou l'équivalent sur les trois environnements et donne la liste des failles avec leur gravité ; 5. compare `main`, `qualification` et `refonte-tout-en-un` : quels correctifs manquent où ; 6. rends tout ça en une note datée, avec un commit ou un fichier par constat.

3. **Une archive** du dépôt déposée dans la conversation, sans `fleet.json`, `results/`, `model/`, `pdfs_test/`, `.env` ni clés.

Ce que je regarderai, dans l'ordre : structure et dépendances ; la chaîne de lecture (OCR, modèle, juge) et sa robustesse aux PDF piégés ; le moteur de règles et le versionnage des verdicts ; le modèle de données et les migrations ; l'authentification, les sessions et le journal ; la gestion des erreurs et des verrous ; les tests et leur couverture réelle ; les scripts d'installation et de mise à jour ; puis les écrans que je n'ai pas vus en vrai.

---

## 09. À trancher par toi

1. **Le nom du logiciel** : Équerre, ou autre, et le dépôt INPI dans la foulée.
2. **Le geste « décidé »** : les trois réponses, la dérogation réservée à l'administrateur.
3. **Verdict et décision séparés** : « Non conforme » pour le moteur, « Refusé » pour l'humain.
4. **La sauvegarde GitHub** cette semaine, et l'application Claude sur l'organisation.
5. **Le gel** : deux jours sur la liste de la section 07, puis rien jusqu'à la première signature.

---

## Voir aussi

Check-up du logiciel, simplicité et compréhension (2026-10-25) · Analyse du logiciel, marché et ludique (2026-10-25) · Logiciel tout en un, analyse et plan (2026-10-24) · Limites connues et ce qui reste à mesurer · Correctifs du moteur et défauts connus (octobre 2026) · Réponses techniques de référence · Les 5 chiffres à connaître par cœur · App de bureau ou navigateur, verdict du 12-10-2026 · Nom du logiciel, analyse marques et recommandation · Demandes clients et engagements pris · Pourquoi les rendez-vous ne signent pas (2026-10-27) · Le meilleur chemin vers le premier client (2026-10-27) · Démonstration du 03/11, procédure · GitHub, README.
