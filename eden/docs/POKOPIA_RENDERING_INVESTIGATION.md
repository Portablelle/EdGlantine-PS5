# Pokopia : historique du diagnostic de rendu

Mis à jour le **2 novembre 2026**. Essais effectués les 1er et 2 novembre.

## Règle pour les prochaines interventions

Lire ce document avant de choisir un nouvel essai. **Ne pas répéter les essais
ci-dessous à l’identique sans nouvel indice.** Une nouvelle scène, un compteur
qui s’active enfin ou une modification du code concerné peuvent justifier une
nouvelle mesure ; préciser alors ce qui change et ce que l’essai doit établir.

Un correctif valide sur CPU n’est pas une résolution du défaut visuel. L’absence
d’erreur dans les logs n’établit pas que les shaders produisent les bons pixels.
Mettre à jour ce document après chaque résultat console, y compris négatif.

## Problème toujours ouvert

- Pokopia : ID **0400A3A01EE4C000**, app **EdGlantine PS5**, titre **PPSA99862**.
- Des assets clignotent, notamment les lianes et les murs. Le joueur ne pouvait
  pas distinguer clairement disparition de géométrie et changement de texture.
- Une vidéo montre des changements de formes/placement apparent entre images.
  Cela ne mesure pas les positions réellement sorties du shader de sommets.
- Un ciel entièrement noir a également été signalé après progression dans le
  jeu. On ignore s’il était déjà noir avant la première capture.
- Environ 45–51 FPS en fonctionnement ordinaire. Le joueur considère environ
  35 FPS suffisants et privilégie la correction du rendu.
- Vulkan, échelle 1x, sortie frontend 1440p/60 Hz. Présentation native observée
  en 1920 × 1080 ; cela ne décrit pas toutes les cibles intermédiaires.

## Essais déjà réalisés

| Essai | Vérification / résultat | Décision à conserver |
|---|---|---|
| DMA normal au lieu du chemin unsafe forcé ; écritures CPU immédiates | Le réglage effectif de Pokopia est `unsafe_dma=false`, avec écritures différées désactivées. Les clignotements persistent. | Ne pas refaire ce simple changement de réglage comme nouveau correctif. |
| Textures ASTC complètes au lieu du mode compressé | Image toujours clignotante. Environ 49,57 FPS sur 60,14 s lors du relevé associé. | Les deux modes ont été essayés. Le mode complet est resté sélectionné. |
| Synchronisation des uniformes GPU avant recopie CPU pour réalignement | Défaut réel reproduit avec les méthodes originales de binding ; test ciblé graphics/compute ASan/UBSan réussi après correction. Sur console, aucun marqueur `NX2_UNIFORM_ALIGN_SYNC` pendant le relevé ; rendu inchangé, environ 50,8 FPS. | Correctif conservé, mais chemin non activé dans cet échantillon. Ne pas le présenter comme cause identifiée des flashs. |
| RADV `syncshaders` | Activation confirmée par `NX2_GPU_SYNC_DIAGNOSTIC ... applied=1`. 49,22 FPS sur 60,17 s. Clignotements inchangés. | La sérialisation des travaux de shaders n’a pas résolu le problème. |
| Correction des modificateurs abs/neg de FSEL pour Pokopia | 64 instructions capturées dans quatre shaders de pixels avaient ces modificateurs. Sur 2 064 vérifications ciblées : 776 résultats incorrects avec l’ancien comportement, zéro après correction. Sur console, marqueurs FSEL actifs, cache initial vide puis shaders reconstruits. Clignotements et ciel noir toujours présents. | Défaut sémantique réel corrigé, **sans résolution du problème visuel**. Ne pas répéter la vidange du cache ou réinstaller le même correctif en espérant un autre résultat. |
| RADV `fullsync` | Activation confirmée ; politique FSEL également active. Clignotements et ciel noir inchangés. **41,85 FPS sur 60,13 s**, 43,06 sur les 30,05 dernières secondes ; intervalles précédents sans fullsync autour de 50,8 FPS. | Ralentit sans gain visuel. Marqueur de démarrage archivé après le test : mode désactivé au prochain lancement complet. Une session déjà ouverte le conserve jusqu’à sa fermeture. |

Précisions importantes :

- ASTC **complet** = décodage GPU sans recompression BC3. Le mode compressé utilise
  le décodage CPU asynchrone et BC3. L’ancienne explication « complet = CPU » était
  erronée et a été corrigée.
- Avec l’accuracy GPU High de cette version, le DMA Default emprunte déjà le
  chemin sûr pertinent. Passer explicitement à Safe ne constituerait pas un
  nouveau test de ce comportement.
- Ni `syncshaders` ni `fullsync` ne permettent de déclarer toutes les erreurs de
  synchronisation, d’alias de ressources ou de durée de vie exclues. Leur résultat
  négatif signifie que ces deux modes ne sont pas des contournements efficaces ici.
- Les FPS de fenêtres différentes ne constituent pas une mesure contrôlée exacte
  du coût de chaque modification ; déplacements, compilations et pauses diffèrent.

## Analyses et captures déjà faites

| Relevé | Ce qu’il établit | Limite à ne pas oublier |
|---|---|---|
| Logs en jeu, avant/après FSEL et fullsync | Pas d’échec de compilation de shader ni d’erreur Vulkan signalés dans les relevés. | Des shaders traduits sans rejet peuvent produire un rendu incorrect. Les erreurs de titre manquant et `nacp_unique is null` existaient au démarrage ; aucune causalité visuelle établie. |
| Vidéo PS5, images 17 et 23 | Comparaison visuelle des assets à deux instants proches. | Pas une capture des sorties GPU de sommets. Ne pas conclure à une erreur de matrices uniquement sur cette base. |
| Première capture de 16 dessins | Trois shaders de sommets distincts ; **112 comparaisons de constantes CPU/GPU identiques**. | Snapshots après le dessin. Ne vérifie pas que le GPU a effectivement consommé ces mêmes données. |
| Audit des trois premiers shaders de sommets | **148 chemins d’opérandes FADD/FMUL/FFMA** concordants, y compris provenance et abs/neg. | Ce n’est ni une exécution complète des shaders ni une validation de toute l’arithmétique flottante. |
| Capture suivante de 32 dessins | A révélé les FSEL concernés ; constantes de sommets toujours concordantes. | Beaucoup de dessins visaient un viewport **720 × 720**. Ne pas attribuer automatiquement ces shaders au ciel de l’image principale. |
| Capture décalée de 128 dessins, puis 32 snapshots | Viewport **2048 × 1024**, shaders de profondeur simples. | C’était une passe secondaire ; le décalage arbitraire n’a pas ciblé le ciel. Ne plus multiplier ces captures non filtrées au hasard. |
| Capture filtrée, scope 3 | **8 paires de shaders** en viewport **1920 × 1080**, fin par budget de 2 048 dessins. Buffers de sommets observés entièrement mappés et continus ; constantes des deux stages graphics concordantes après synchronisation. | Le viewport seul n’identifie pas l’objet ou la fonction de chaque passe. Aucune sortie GPU de sommets capturée. |
| Conditions de rendu des premiers relevés | Aucun buffer de condition référencé dans les registres des 48 dessins examinés. | Échantillon de dessins exécutés, pas preuve sur les dessins éventuellement rejetés ailleurs. |
| Tables de textures de la capture filtrée | Les matériaux observés référencent des indices autour de **16 400**, pour une limite TIC **0x80ff**. L’ancienne capture ne gardait que 8 192 entrées. | **Limitation du diagnostic**, pas preuve d’une limite du moteur : `DescriptorTable` est dimensionnée selon la limite déclarée. |

### Pauses et « crashs »

- Un blocage initial de Pokopia s’est résorbé ; pas de crash confirmé par un
  nouveau rapport associé. Ne pas requalifier ce seul événement en crash/OOM.
- La capture de 16 dessins a provoqué environ **8,6 secondes sans présentation**,
  puis un retour autour de 51 FPS. Une autre capture a duré environ 9 secondes.
- Les écritures synchrones de nombreux petits fichiers et les readbacks peuvent
  fortement perturber la session. Le joueur a ensuite explicitement autorisé ces
  pauses pour poursuivre le diagnostic.

## État conservé et outils disponibles

- Correctifs d’uniformes et FSEL conservés. FSEL est sélectionné **par programme**
  pour Pokopia ; les autres titres gardent leur politique antérieure.
- La version du cache Vulkan de Pokopia ajoute **0x100** pour séparer les anciens
  environnements traduits et pipelines. L’ancien binaire et les deux caches ont
  été sauvegardés lors de l’installation du correctif FSEL.
- **Fullsync désactivé pour les prochains lancements complets.** Ne pas le
  réactiver sans une nouvelle hypothèse précise.
- La dernière version installée sait capturer jusqu’à **65 536 descripteurs TIC**
  et lire les demandes auxiliaires par des chemins absolus.
- Ne pas identifier les hotfixes uniquement par `00.065.000` : plusieurs binaires
  différents ont cette même version. Garder leur artefact et journal d’installation.

Demandes de capture, à publier par upload vers un nom temporaire puis renommage
FTP atomique :

```text
/data/eden-nx2/position-capture.request
0 32 3
```

Champs : skip, maximum de snapshots (32 au plus), scope. Scope 0 = non filtré ;
2 = viewport 1920 × 1080 à 1x ; 3 = même filtre, avec une capture par paire
d’adresses de programmes vertex/fragment. Un quatrième champ hexadécimal optionnel
filtre le hash des 256 premiers octets d’instructions du shader de pixels.

- Attendre `NX2_POSITION_CAPTURE complete draws=N` **avant** l’inventaire et le
  téléchargement. Une collecte trop précoce a déjà manqué des fichiers tardifs.
- Les noms sont réutilisés : ignorer les anciens fichiers au-delà de N et les
  fichiers non réécrits pendant le relevé. Télécharger avant de réarmer.
- `position-memory.request` accepte jusqu’à 16 couples adresse GPU/taille en
  hexadécimal, au plus 16 MiB par plage.
- `position-textures.request` accepte jusqu’à 16 indices décimaux de textures
  pour les readbacks d’images 2D supportées.
- Publier les demandes auxiliaires **avant** la demande principale : elles sont
  consommées lors du premier dessin capturé.
- Les anciens noms relatifs `native-memory.request` n’étaient pas consommés depuis
  le dossier de l’app. Le fichier d’essai a été supprimé. Une écriture tentée à la
  racine a été refusée, système de fichiers en lecture seule. Ne pas retenter ces
  chemins : utiliser les chemins absolus sous `/data/eden-nx2/`.

## Ce qui reste réellement à établir

1. Capturer et décoder les descripteurs effectivement référencés au-delà de 8 192,
   avec la version de capture complète désormais installée.
2. Identifier le ou les dessins responsables du ciel et des assets concernés,
   plutôt que les déduire du seul viewport ou du nombre d’instructions.
3. Comparer les images réellement présentes sur le GPU aux ressources attendues,
   notamment formats, mips, couches, alias et contenu ; les snapshots de constantes
   ne répondent pas à cette question.
4. Si nécessaire, vérifier les sorties effectives des shaders ou le binding
   consommé par le GPU. Cela n’a **pas encore été mesuré**.

Ne pas présenter l’une de ces pistes comme une cause déjà démontrée. Le ciel noir
et les clignotements peuvent aussi avoir des causes distinctes.

## Contexte à préserver

Le choix mémoire NX2 à 12 GiB avant construction de `Core::System`, ainsi que le
bornage des retours de pages, ont corrigé le démarrage noir des deux jeux :
Welcome Tour et Pokopia ont ensuite atteint le gameplay. Ne pas confondre cet
ancien écran noir de démarrage avec le **ciel noir en jeu** actuel.

Welcome Tour (**040057C02159A000**) reste une régression distincte : environ
8 FPS contre 21 auparavant dans la même scène, confirmation du joueur. La
réutilisation de gathers SSBO avait été désactivée pour une raison de cohérence ;
ne pas rétablir aveuglément l’ancien cache pour gagner des FPS.

## Preuves locales et provenance

Les captures et binaires sont dans `artifacts/`, ignoré par Git. Ces chemins sont
des preuves locales, pas des fichiers garantis dans un nouveau checkout :

- `artifacts/pokopia-media/` : vidéo et comparaison des images 17/23.
- `artifacts/pokopia-uniform-retest/` : absence d’activation du chemin de réalignement.
- `artifacts/pokopia-gpu-sync-retest/20261101-224117/` : essai syncshaders.
- `artifacts/pokopia-position-capture/` : premier relevé, audit des 148 opérandes.
- `artifacts/pokopia-position-sky-capture/` : relevé contenant les FSEL concernés.
- `artifacts/pokopia-main-pass-capture/` : relevé décalé, en fait passe de profondeur.
- `artifacts/pokopia-filtered-main-capture/` : huit paires en viewport principal.
- `artifacts/pokopia-fsel-retest/20261101-231704/` : FSEL actif, résultat visuel négatif.
- `artifacts/pokopia-fullsync-retest/20261102-000425/` : résultat et FPS fullsync.
- `artifacts/00.065.000-{uniform-alignment,gpu-sync-diagnostic,position-capture,pokopia-fsel,filtered-capture,full-cache-sync}/` : artefacts et journaux d’installation correspondants.

Sources principales : `eden/headless/native_shader_policy.h`,
`eden/tools/prepare-{uniform-alignment,float-select,position-capture}.py`.
Tests ciblés : `eden/tests-nx2/check-{uniform-alignment,float-select}.py` et
`eden/tests-nx2/position-capture-gate.cpp`.

Les compilations ont été réalisées sur **dedie**, dans le répertoire isolé
`/tmp/edglantine-game-library-20261101`. Les backups console exacts figurent dans
les journaux d’installation locaux. Ne pas modifier les saves, clés, dumps, ni
l’app Botty Switch 1 distincte pour poursuivre ce diagnostic.
