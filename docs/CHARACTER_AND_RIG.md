# Character & Rig Spec (decided)

The character + rig choices the render pipeline is built around. Follow this and your
first Blender render will lip-sync correctly with no code changes.

## The character: Milo (single hero)

- **Milo** — a friendly young **fox cub**: bright orange fur, blue scarf, big round
  eyes, cheerful. Your channel's star, on screen every episode.
- **Start with one character, not two.** One rig is dramatically less work to build,
  animate, and light than two — and a single recurring hero is exactly how channels
  like NuNu Tv are structured. Add **Lulu (the owl)** as a co-star later, once Milo's
  rig and render loop are proven.
- Animal (not human toddler) on purpose: avoids the uncanny-valley problem and is
  cheaper to make appealing.

## The rig standard: Oculus visemes + Mixamo skeleton

Two things the character MUST have for this pipeline:

1. **Oculus visemes** (15 mouth shape keys: `viseme_sil`, `viseme_PP`, `viseme_FF`,
   `viseme_TH`, `viseme_DD`, `viseme_kk`, `viseme_CH`, `viseme_SS`, `viseme_nn`,
   `viseme_RR`, `viseme_aa`, `viseme_E`, `viseme_I`, `viseme_O`, `viseme_U`).
   `scripts/render_episode.py` maps Rhubarb's output to these names already.
2. **A Mixamo-compatible humanoid skeleton**, so the Mixamo body clips
   (idle/gesture/wave) retarget onto it.

> ⚠️ **The catch with Meshy/Tripo:** they generate a great 3D *model* but usually **no
> facial visemes** — so Rhubarb lip-sync has nothing to drive. You need a character
> that *includes* visemes. That's why the recommended route below matters.

## Fastest route to a lip-syncable Milo: Ready Player Me (free)

Ready Player Me avatars ship with **Oculus visemes built in** and a Mixamo-compatible
skeleton — exactly what this pipeline needs, at no cost.

1. Go to [readyplayer.me](https://readyplayer.me), create an avatar, style it toward
   Milo (orange/warm tones, friendly). Stylized/cartoon body type.
2. Export as **GLB**, then in Blender **import the GLB and export FBX** (or use a
   GLB→FBX step). Confirm the mesh's **Shape Keys** panel lists `viseme_*` names.
3. Retarget your Mixamo clips onto its skeleton (Mixamo auto-rigs to a standard
   humanoid; Blender's Rokoko/Auto-Rig Pro or manual retarget works).
4. Point the render at it:
   ```bash
   blender --background scene_template.blend --python scripts/render_episode.py -- \
     --episode 2 --character /path/to/milo.fbx --audio audio/ep2.mp3 --clip idle_gesture
   ```

## Alternative route: Meshy/Tripo model + add visemes

If you want a more custom Milo from Meshy/Tripo:

1. Generate the model. Example prompt:
   > *"Cute stylized 3D cartoon fox cub character for a toddler educational show,
   > bright orange fur, big friendly eyes, small blue scarf, soft rounded shapes,
   > Pixar-like, T-pose, full body, clean topology."*
2. Auto-rig the body (Mixamo, or Meshy's rigging) for a humanoid skeleton.
3. **Add facial visemes in Blender** — the model won't have them. The
   [Faceit](https://faceit-doc.readthedocs.io/) addon generates ARKit/Oculus
   viseme shape keys on a mesh. Generate the Oculus viseme set and name them to match
   the list above.
4. Same render command as above.

This route is more work (step 3 especially) but gives you a bespoke character.

## Verify the visemes match before rendering

Open the character in Blender → select the face mesh → **Object Data Properties →
Shape Keys**. You should see `viseme_PP`, `viseme_aa`, etc. If the names differ, either
rename them to the standard, or edit `VISEME_TO_SHAPEKEY` at the top of
`scripts/render_episode.py` to your names. On a mismatch the script prints
`WARNING: shape keys not found on '<mesh>': [...]` — fix those names.

## Scene template (visual style)

Build `scene_template.blend` once: a soft daytime lighting rig, a camera framed on
Milo at ~waist-up, and a simple background (a grassy "grove" — ground plane + sky +
a few trees/props). Every episode reuses it, so the look stays consistent. This is the
art-direction step that most affects how close you get to the NuNu Tv polish — and it's
yours to design.
