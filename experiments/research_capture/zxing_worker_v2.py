#!/usr/bin/env python3
"""Fixed optional native decoder comparator, isolated by the DEV runner."""
import json
import sys
import cv2
import numpy as np
from PIL import Image
import zxingcpp
cv2.setNumThreads(1)
image = cv2.imread(sys.argv[1])
if image is None:
    with Image.open(sys.argv[1]) as loaded:
        image = cv2.cvtColor(np.array(loaded.convert("RGB")),cv2.COLOR_RGB2BGR)
result = zxingcpp.read_barcodes(image,try_rotate=True,try_downscale=True,try_invert=True,text_mode=zxingcpp.TextMode.HRI,binarizer=zxingcpp.Binarizer.LocalAverage,is_pure=False,ean_add_on_symbol=zxingcpp.EanAddOnSymbol.Ignore,return_errors=False)
print(json.dumps({'barcodes':[{'format':str(b.format).lower().replace(' ','').replace('_','').replace('-',''),'text':b.text} for b in result]}))
