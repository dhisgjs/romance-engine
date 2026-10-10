# -*- coding: utf-8 -*-
try:
    import PIL
    from PIL import Image, features
    print("Pillow", PIL.__version__)
    try:
        print("heif:", features.check("heif"))
    except Exception as e:
        print("heif check err", e)
except Exception as e:
    print("no Pillow:", e)
try:
    import pillow_heif  # noqa: F401
    print("pillow_heif installed")
except Exception as e:
    print("no pillow_heif:", e)