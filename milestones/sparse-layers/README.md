# Couches sparse sûres — prototype NX2 00.006.000

## Intégration

Le chemin de création des images originales du cache Vulkan appelle maintenant
`TryMakeSparseLayerImage` avant l'allocateur ordinaire. Il ne s'exécute que si
`EDEN_NX2_SPARSE_LAYERS=1` est explicitement présent. Variable absente, vide ou
avec une autre valeur : chemin ordinaire. Le paquet ne définit pas cette option.

Cette première intégration est volontairement **entièrement résidente avant
publication** : une allocation par couche, plus une allocation unique si le mip
tail est partagé, et binding de tous les sous-niveaux visibles. Aucun shader,
upload, décodage ASTC, rendu ou téléchargement ne reçoit une image à moitié liée.
Il n'existe pas d'API d'éviction d'une couche d'une image publiée. Cela évite de
supposer que les trous du pilote PS5 se lisent à zéro. **Ce jalon n'apporte pas
encore le streaming sélectif des couches ni un gain mémoire mesuré.**

Les images rescalées restent sur le chemin ordinaire. Les formats et usages
réellement fournis par le cache, y compris les substitutions ASTC et les vues
mutables, sont conservés. L'admission exige une image 2D color à plusieurs couches,
un seul sample, le support sparse 2D et la queue appropriée. La création Vulkan
et les requirements réels déterminent le support du format. Plusieurs aspects,
metadata, blocs non standard et dispositions non couvertes sont refusés avant bind.

## Allocations et durée de vie

`vk_sparse_layers.h` planifie les offsets et tailles avec des calculs bornés :
granularité en texels, couches/mips, tails individuels ou partagés, alignement,
limites des ranges et budgets. Les allocations utilisent uniquement un type
mémoire device-local autorisé par `memoryTypeBits`, sans débordement vers un
budget PC. Plafonds conservateurs du laboratoire : **64 Mio par image et 128 Mio
sparse cumulés dans le processus**. Ce ne sont pas les budgets de tout le moteur.

États : Empty → Allocated → Binding → Resident → Retired ; Quarantined si
l'achèvement GPU n'est pas confirmé. Les couches ne deviennent accessibles au
cache qu'après réussite du bind et de sa fence.

Pour changer/détruire les mappings, le backend termine les commandes enregistrées,
attend le worker de soumission, puis attend le device sous le mutex de soumission.
Le bind est soumis sous ce même mutex ; sa fence doit aboutir avant publication.
Ce choix est volontairement global et peut coûter du temps de trame. Le mutex
n'est jamais tenu pendant `Scheduler::Finish`, car le worker doit pouvoir le prendre.
Ce backend est destiné au cache actuel, propriétaire unique des commandes GPU.
Une future utilisation depuis d'autres producteurs/queues doit étendre le protocole.

En cas d'échec partiel, on attend le GPU, détruit la ressource virtuelle (et sa
fence), puis libère les allocations physiques. On ne suppose pas que BindSparse
est atomique. Si l'attente échoue, les handles et allocations restent conservés,
le budget reste débité, les nouvelles admissions sparse sont bloquées et l'erreur
remonte comme perte du device. Cette quarantaine est volontairement non récupérable
dans le processus : il n'y a pas de libération hasardeuse ni de retry silencieux.
Elle peut retenir jusqu'au budget expérimental jusqu'à la fin du processus.

`vk::Image` possède un propriétaire de backing spécifique pour ces images :
les déplacements et remplacements transmettent cette propriété, et le destructeur
ne les transmet jamais à `vmaDestroyImage`. Elles ne sont pas marquées Unbacked.
Les chemins VMA ordinaires conservent leur comportement.

Si l'admission ou une allocation sparse échoue avec une récupération confirmée,
le cache essaie une image ordinaire. Lorsque l'option expérimentale est active,
ce repli ne peut pas devenir l'ancien fallback sparse sans backing du fork ; si
l'image ordinaire ne tient pas, l'erreur d'allocation est remontée. Le comportement
historique de ce fallback reste inchangé lorsque l'option expérimentale est désactivée.

## Vérifications

- Tests de la politique par défaut et du gestionnaire de production sous ASan/UBSan :
  mips/couches RGBA et BC, tails partagés/individuels et image entièrement en tail,
  débordements, limites, budget global, échec d'allocation, bind partiel, exception,
  attente échouée, quarantaine, retrait et ordre destruction/libération.
- Test du véritable `vk::Image` et du corps de `Image::Release` extrait des sources :
  déplacement, remplacement, auto-déplacement, reset, une seule libération et
  distinction avec le backing ordinaire, sous ASan/UBSan.
- Suite moteur ciblée : 380 cas, 1 870 846 assertions réussies.
- Compilation native et contrôles finaux : résultats définitifs dans `TEST-REPORT.md`.

Les tests utilisent des mocks pour le device, les allocations et la fin des
travaux GPU. Ils ne prouvent pas le comportement des appels kernel PS5 ni le
rendu sur console. Le banc RADV de `experiments/sparse-textures/` complète ces
tests par les calculs de mappings extraits du pilote épinglé.

## Étape suivante

Pour économiser la mémoire par couche : suivre réellement les accès des vues,
les couches lues et écrites, le filtrage et les sous-niveaux accessibles ; ne
publier que des ensembles résidents prouvés, ou fournir une sémantique sûre pour
les trous. Remplacer ensuite les attentes globales par des dépendances ciblées
avec une preuve de durée de vie pour chaque utilisateur. Ne pas activer ces
optimisations par simple modification du flag PRT ou du budget.
