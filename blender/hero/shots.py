"""The hero shot list (bench/m1/v2/direction.md §5, plus the brief's bust,
back and walk shots).

Each shot: camera spec (a rig.CAMERAS name or a custom spec string), pose,
resolution at 100 %, beads (water drops per shoulder), gaze (eyes to camera,
deg off it; None = the pose's own), neon (sign-tube brightness, 1 = the set's;
dimmer behind faces so the bokeh doesn't compete), light overrides on rig.HERO_LIGHTS (name -> tuple, or
None to drop a light), extra desaturated twins of the rim / kicker (twin: {"cloth" | "skin":
(saturation fraction, energy factor)}; see rig.PROP_SAT), haze density, rain streak count, a horizontal frame
shift (rule of thirds; + moves the subject left), exposure offset (EV), and
the grade's painterly strength. Shifts are fractions of the frame
height (vertical sensor fit): shift_y -0.16 puts the aim point at the upper third. Light tuples: (colour or K, ratio, (w, h) m,
azimuth deg from the camera axis (+ = camera-left), elevation deg, distance).
"""

from hero.rig import KEY_K
from hero.sets import NEON

LAND = (1920, 1080)
# Stronger neon rims for the hero shots than the shared rig (1.4 / 0.8): in
# the set the rims must also beat the sign spill to separate hair and suit.
RIMS = {"rim": (NEON["magenta"], 2.2, (0.3, 1.5), -125.0, 20.0, 1.5),
        "kicker": (NEON["teal"], 1.2, (0.3, 1.2), 135.0, 15.0, 1.6)}
POSTER = (1152, 2048)

SHOTS = {
    # 1. Rain portrait: 85 mm head and shoulders, 3/4, f/2 on the near eye.
    "portrait": dict(cam="lens=85,az=30,el=2,aim=eyes,frame=0.42,f=2", pose="stand", res=LAND, shift=-0.07,
                     shift_y=-0.16, haze=0.008, rain=700, beads=35, gaze=0.0, neon=0.4,
                     lights=dict(RIMS), ev=0.0),
    # 2. Under the sign: 50 mm full body, camera at 1.1 m; the magenta sign
    # above-right is the key, the teal sign across the street 0.5, sodium 0.3.
    "sign": dict(cam="lens=50,az=20,h=1.1,aim=body,frame=3.4,f=4", pose="stand", res=POSTER, shift=0.0,
                 shift_y=0.06, flag=("eye",),
                 haze=0.012, rain=2200,
                 lights={"key": (NEON["magenta"], 1.3, (1.2, 0.4), -35.0, 35.0, 1.6),
                         "kicker": (NEON["teal"], 0.5, (0.6, 1.2), 100.0, 12.0, 2.5),
                         "fill": (2000, 0.3, (0.6, 0.6), 160.0, 40.0, 3.0),
                         "rim": (NEON["magenta"], 0.9, (0.3, 1.5), -125.0, 20.0, 1.5),
                         "wrap": None},
                 ev=0.5),
    # 3. Profile, teal: 100 mm bust profile; teal rim 0.9 from behind the
    # face, amber key 0.3. The silhouette shot. The rim sits at az 160 (20 deg
    # off the back axis, not 40): at 140 it reached the forward-facing cheek
    # plane through the gap under the hair and blew out to a pale blob below
    # the eye; at 160 it grazes the nose, brow and beard edge only. The skin
    # gets a softer twin (70 % saturation, 0.8 energy) so the brow ridge
    # holds a teal line, not a cyan streak.
    "profile": dict(cam="lens=100,az=90,el=0,aim=head,frame=0.6,f=2.8", pose="stand_profile", res=LAND,
                    shift=0.12, haze=0.01, rain=500, beads=35,
                    lights={"key": (KEY_K, 0.3, (0.3, 0.3), 40.0, 25.0, 1.5), "wrap": None,
                            "rim": (NEON["teal"], 2.5, (0.3, 1.5), 160.0, 15.0, 1.4),
                            "kicker": (NEON["magenta"], 0.35, (0.3, 1.2), -135.0, 20.0, 1.6)},
                    twin={"skin": (0.7, 0.8)}, ev=0.4),
    # 4. The draw: 35 mm full body, camera at 1.2 m, az 20 (Track H: at az 5
    # the muzzle points down the lens and the gun reads as a dark square);
    # bladed high-ready holding the pistol two-handed (poses.HOLD); a hard
    # 4,300 K source 0.2 m off the ground, low right (a headlight), magenta top.
    # Its 100 % crop is the hands on the gun (crop_at, 0.3 of the frame).
    "draw": dict(cam="lens=35,az=20,h=1.2,aim=body,frame=2.5,f=5.6", pose="ready", res=LAND, shift=0.0,
                 flag=("eye",), crop_at=("hands", 0.3),
                 haze=0.012, rain=1600,
                 lights={"key": (4300, 1.0, (0.18, 0.12), -50.0, -22.0, 3.0), "wrap": None,
                         "top": (NEON["magenta"], 0.4, (1.0, 1.0), 0.0, 80.0, 2.0)},
                 ev=0.0),
    # 5. Hands and cuff: 100 mm, the right hand at the left cuff, shoe and
    # trouser break in frame (a tall frame from the cuff to the floor).
    "hands": dict(cam="lens=100,az=28,h=0.8,aim=cuff_feet,frame=1.45,f=5.6", pose="cuff", res=POSTER, shift=0.0,
                  shift_y=0.1, haze=0.006, rain=0, lights={"key": (KEY_K, 0.8, (0.3, 0.3), 55.0, 30.0, 1.5)}, ev=0.0),
    # 6. Eye close-up: 135 mm from 0.73 m, eyes and brow, gaze 5 deg off
    # camera; the base (skin-direction) key, eye light 0.3. f/8 focused 6 mm in
    # front of the near cornea (~14 mm in focus: far cornea -3 mm to +13 mm,
    # the brow ridge is +19 mm, the nose +34 mm), so both eyes and the brows
    # are crisp and the nose softens. skin-direction.md's f/4 on the cornea
    # held ~7 mm and left the brows and forehead soft (main7 eye A/B).
    "eye": dict(cam="lens=135,az=8,el=0,aim=eyes,frame=0.13,f=8,fo=6", pose="stand", res=LAND, shift=0.0, haze=0.0,
                rain=0, gaze=5.0, neon=0.4,
                lights={"eye": (6500, 0.3, (0.05, 0.05), 0.0, 0.0, None)}, ev=0.0),
    # brief: bust 3/4, back 3/4 (hair and suit back), walk.
    "bust": dict(cam="lens=50,az=35,el=3,aim=chest,frame=0.95,f=2.8", pose="stand", res=LAND, shift=-0.12,
                 shift_y=0.1, haze=0.008, rain=500, beads=35, gaze=0.0, neon=0.6, lights=dict(RIMS), ev=0.0),
    # back: from behind, the magenta rim lands on the broad back of the jacket
    # (plum, not black) and the teal kicker on the near elbow (a cyan glint);
    # the suit gets a cloth twin of both at 30 % saturation, 0.75 energy.
    "back": dict(cam="lens=50,az=150,el=4,aim=chest,frame=1.15,f=2.8", pose="stand", res=LAND, shift=0.1, shift_y=0.1,
                 haze=0.008, rain=500, beads=35, lights=dict(RIMS), twin={"cloth": (0.3, 0.75)}, ev=0.2),
    "walk": dict(cam="lens=35,az=-35,h=1.0,aim=body,frame=2.4,f=5.6", pose="walk", res=LAND, shift=-0.1,
                 haze=0.012, rain=1600, lights=dict(RIMS), ev=0.0),
}
ORDER = ["portrait", "sign", "profile", "draw", "hands", "eye", "bust", "back", "walk"]
# shots that get a 100 % crop with --crop close (preview renders at 50 %)
CLOSE = ["portrait", "profile", "hands", "eye"]

# Turntable (shot 7): 8 views at 45 deg, A-pose and the hero stand, beauty +
# clay + normal; honest light, no haze, grade or DOF.
TT_VIEWS = [f"tt{a}" for a in range(0, 360, 45)]
TT_POSES = ["rest", "stand"]
TT_PASSES = ["beauty", "clay", "normal"]
TT_RES = (1080, 1620)
