---
slug: bilan-commente
title: "Préparer la trame du bilan commenté à partir de la balance"
themes: [revision, relation_client]
summary: "Faire produire au modèle une première trame de commentaires (variations, points d'attention, questions à poser au dirigeant) à partir d'une balance N / N-1 anonymisée."
duration: "15 minutes par dossier"
tools: "logiciel de révision (export balance) ; modèle de langage, de préférence local"
---
**Le problème.** Le rendez-vous bilan se prépare souvent la veille, à partir d'une balance brute. Les commentaires sont réécrits chaque année, et les mêmes questions sont oubliées.

**Le workflow.**

1. Exporter la balance comparative N / N-1 (comptes de classe 6 et 7 regroupés par poste, plus les principaux postes de bilan). Retirer le nom du client : un code dossier suffit.
2. Coller la balance dans le prompt ci-dessous, avec deux ou trois informations de contexte que seul le cabinet connaît (changement d'activité, embauche, investissement).
3. Récupérer la trame : variations commentées, points d'attention, questions à poser. La relire ligne à ligne : le modèle calcule mal, le réviseur vérifie chaque pourcentage.
4. Compléter avec l'analyse du réviseur, puis mettre en forme dans le modèle de plaquette du cabinet.
5. Après le rendez-vous, noter les questions qui ont fait réagir le dirigeant : elles enrichissent le prompt l'année suivante.

**Le prompt prêt à copier.**

```text
Tu es chef de mission en cabinet d'expertise comptable. À partir de la balance comparative
ci-dessous (exercice N et N-1, montants en euros), prépare une trame de bilan commenté
pour un dirigeant de TPE qui n'est pas comptable. Structure attendue :
1. Activité : chiffre d'affaires, marge, variation en % et en euros, une phrase d'explication
   possible par variation supérieure à 10 % (formulée comme une hypothèse à confirmer).
2. Charges : les 5 postes qui ont le plus varié, avec le montant et le %.
3. Résultat et trésorerie : résultat d'exploitation, résultat net, trésorerie de clôture,
   endettement, en phrases simples.
4. Points d'attention : au maximum 5, formulés sans alarmisme.
5. Questions à poser au dirigeant pendant le rendez-vous : 8 questions concrètes.
Règles : tous les pourcentages doivent être recalculés et vérifiables ; n'invente aucune
cause ; écris « à confirmer » quand tu formules une hypothèse ; pas de conseil fiscal.

Contexte connu : {2 ou 3 faits : changement d'activité, embauche, investissement…}
Balance comparative :
{colle ici la balance : compte ; libellé ; N ; N-1}
```

**Ce qu'il faut garder en tête.**
- Les modèles font des erreurs d'arithmétique. Faire calculer les variations par le tableur, et donner au modèle les pourcentages déjà calculés si possible.
- Une balance anonymisée reste une donnée confidentielle : modèle local ou compte professionnel sans entraînement, et mention dans la lettre de mission (voir le cas « lettre de mission »).
- La valeur est dans les questions à poser : c'est là que le rendez-vous change de nature.
