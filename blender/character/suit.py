"""Suit and shoes. Stock suits01 shell until the scripted tailoring lands."""


def add(b):
    for fname in b.cfg["suit"]["clothes"]:
        b.mpfb.add_mhclo(b.basemesh, "clothes", fname, "Clothes")


def post(b):
    pass
