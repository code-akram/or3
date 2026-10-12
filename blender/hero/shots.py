"""The hero shot list (bench/m1/v2/direction.md §5, plus the brief's bust,
back and walk shots).

Each shot: camera spec (a rig.CAMERAS name or a custom spec string), pose,
resolution at 100 %, light overrides on rig.HERO_LIGHTS (name -> tuple, or
None to drop a light), haze density, rain streak count, a horizontal frame
shift (rule of thirds; + moves the subject left), exposure offset (EV), and
the grade's painterly strength. Light tuples: (colour or K, ratio, (w, h) m,
azimuth deg from the camera axis (+ = camera-left), elevation deg, distance).
"""

from hero.sets import NEON

LAND = (1920, 1080)
# Stronger neon rims for the hero shots than the shared rig (1.4 / 0.8): in
# the set the rims must also beat the sign spill to separate hair and suit.
RIMS = {"rim": (NEON["magenta"], 2.2, (0.3, 1.5), -140.0, 25.0, 1.5),
        "kicker": (NEON["teal"], 1.2, (0.3, 1.2), 135.0, 15.0, 1.6)}
POSTER = (1152, 2048)

SHOTS = {
    # 1. Rain portrait: 85 mm head and shoulders, 3/4, f/2 on the near eye.
    "portrait": dict(cam="lens=85,az=30,el=2,aim=eyes,frame=0.55,f=2", pose="stand", res=LAND, shift=-0.16,
                     shift_y=-0.08, haze=0.008, rain=700,
                     lights=dict(RIMS), ev=0.0),
    # 2. Under the sign: 50 mm full body, camera at 1.1 m; the magenta sign
    # above-right is the key, the teal sign across the street 0.5, sodium 0.3.
    "sign": dict(cam="lens=50,az=20,h=1.1,aim=body,frame=3.4,f=4", pose="stand", res=POSTER, shift=0.0,
                 shift_y=0.06, flag=("eye",),
                 haze=0.012, rain=2200,
                 lights={"key": (NEON["magenta"], 1.3, (1.2, 0.4), -35.0, 35.0, 1.6),
                         "kicker": (NEON["teal"], 0.5, (0.6, 1.2), 100.0, 12.0, 2.5),
                         "fill": (2000, 0.3, (0.6, 0.6), 160.0, 40.0, 3.0),
                         "rim": (NEON["magenta"], 0.9, (0.3, 1.5), -140.0, 25.0, 1.5)},
                 ev=0.5),
    # 3. Profile, teal: 100 mm bust profile; teal rim 0.9 from behind the
    # face, amber key 0.3. The silhouette shot.
    "profile": dict(cam="lens=100,az=90,el=0,aim=head,frame=0.6,f=2.8", pose="stand_profile", res=LAND,
                    shift=0.12, haze=0.01, rain=500,
                    lights={"key": (3000, 0.3, (0.8, 0.8), 40.0, 25.0, 1.5),
                            "rim": (NEON["teal"], 2.5, (0.3, 1.5), 140.0, 15.0, 1.4),
                            "kicker": (NEON["magenta"], 0.35, (0.3, 1.2), -135.0, 20.0, 1.6)},
                    ev=0.4),
    # 4. The draw: 35 mm 3/4 full body, camera at 1.2 m, high-ready; a hard
    # 4,300 K source 0.2 m off the ground, low right (a headlight), magenta top.
    "draw": dict(cam="lens=35,az=35,h=1.2,aim=body,frame=2.5,f=5.6", pose="ready", res=LAND, shift=0.0,
                 flag=("eye",),
                 haze=0.012, rain=1600,
                 lights={"key": (4300, 1.0, (0.18, 0.12), -50.0, -22.0, 3.0),
                         "top": (NEON["magenta"], 0.4, (1.0, 1.0), 0.0, 80.0, 2.0)},
                 ev=0.0),
    # 5. Hands and cuff: 100 mm on the hands.
    "hands": dict(cam="lens=100,az=55,el=8,aim=hand_l,frame=0.36,f=4", pose="stand", res=LAND, shift=0.0,
                  haze=0.006, rain=0, lights={"key": (3000, 0.8, (0.8, 0.8), 40.0, 25.0, 1.5)}, ev=0.0),
    # 6. Eye close-up: 135 mm, eyes and brow; soft key, eye light 0.3.
    "eye": dict(cam="eye", pose="stand", res=LAND, shift=0.0, haze=0.0, rain=0,
                lights={"key": (3000, 1.0, (1.2, 1.2), 40.0, 25.0, 1.5),
                        "eye": (6500, 0.3, (0.1, 0.1), 0.0, 0.0, None)}, ev=0.0),
    # brief: bust 3/4, back 3/4 (hair and suit back), walk.
    "bust": dict(cam="lens=50,az=35,el=3,aim=chest,frame=0.95,f=2.8", pose="stand", res=LAND, shift=-0.12, shift_y=0.1, haze=0.008, rain=500, lights=dict(RIMS), ev=0.0),
    "back": dict(cam="lens=50,az=150,el=4,aim=chest,frame=1.15,f=2.8", pose="stand", res=LAND, shift=0.1, shift_y=0.1,
                 haze=0.008, rain=500, lights=dict(RIMS), ev=0.2),
    "walk": dict(cam="lens=35,az=-35,h=1.0,aim=body,frame=2.4,f=5.6", pose="walk", res=LAND, shift=-0.1,
                 haze=0.012, rain=1600, lights=dict(RIMS), ev=0.0),
}
ORDER = ["portrait", "sign", "profile", "draw", "hands", "eye", "bust", "back", "walk"]

# Turntable (shot 7): 8 views at 45 deg, A-pose and the hero stand, beauty +
# clay + normal; honest light, no haze, grade or DOF.
TT_VIEWS = [f"tt{a}" for a in range(0, 360, 45)]
TT_POSES = ["rest", "stand"]
TT_PASSES = ["beauty", "clay", "normal"]
TT_RES = (1080, 1620)
