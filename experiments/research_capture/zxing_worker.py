#!/usr/bin/env python3
"""Fixed optional native decoder comparator, isolated by the DEV runner."""
import json
import sys
import cv2
import zxingcpp
cv2.setNumThreads(1)
image = cv2.imread(sys.argv[1])
result = zxingcpp.read_barcodes(image,try_rotate=True,try_downscale=True,try_invert=True,text_mode=zxingcpp.TextMode.HRI,binarizer=zxingcpp.Binarizer.LocalAverage,is_pure=False,ean_add_on_symbol=zxingcpp.EanAddOnSymbol.Ignore,return_errors=False)
print(json.dumps({'barcodes':[{'format':str(b.format).lower().replace(' ','').replace('_','').replace('-',''),'text':b.text} for b in result]}))
