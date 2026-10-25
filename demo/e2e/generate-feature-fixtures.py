"""Fictional browser fixtures; no user documents. Requires Pillow/numpy/zxing-cpp."""
import json,hashlib,os
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
import zxingcpp
ROOT=Path(__file__).resolve().parents[2]
OUT=Path('/tmp/docscan-feature-fixtures');OUT.mkdir(mode=0o700,exist_ok=True)
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
def luhn(prefix):
 ds=[int(c) for c in prefix+'0'];n=0
 for i,d in enumerate(reversed(ds)):
  if i%2:d=d*2;d=d-9 if d>9 else d
  n+=d
 return prefix+str((-n)%10)
GTIN='09506000134352'
items=[]
for i in range(2):
 serial=f'DEMO-BOX-{i+1:04d}';imeis=[luhn(f'35120412345{i}{j}0') for j in (1,2)]
 assert all(len(n)==15 for n in imeis)
 data=f'(01){GTIN}(21){serial}(8040){imeis[0]}(8041){imeis[1]}'
 b=zxingcpp.create_barcode(data,zxingcpp.BarcodeFormat.QRCode,gs1=True)
 qr=Image.fromarray(np.asarray(zxingcpp.write_barcode_to_image(b,scale=6)))
 box=Image.new('RGB',(600,800),'white');d=ImageDraw.Draw(box);d.rectangle((4,4,595,795),outline='black',width=3)
 d.text((25,28),f'FICTIONAL BOX {i+1}',fill='black',font=font)
 d.text((25,64),'Synthetic test only',fill='black',font=small)
 box.paste(qr,(25,110));d.text((25,600),f'SN: {serial}',fill='black',font=font)
 d.text((25,640),f'IMEI1: {imeis[0]}',fill='black',font=font);d.text((25,680),f'IMEI2: {imeis[1]}',fill='black',font=font)
 box.save(OUT/f'box-{i+1}.png');items.append({'serial':serial,'imei1':imeis[0],'imei2':imeis[1],'gtin':GTIN})
image=Image.new('RGB',(1280,880),(235,235,235));image.paste(Image.open(OUT/'box-1.png'),(20,30));image.paste(Image.open(OUT/'box-2.png'),(660,30));image.save(OUT/'items.png')
for name,fmt in [('gs1-dm',zxingcpp.BarcodeFormat.DataMatrix),('gs1-128',zxingcpp.BarcodeFormat.Code128)]:
 code=zxingcpp.create_barcode(f'(01){GTIN}(10)DEMOLOT(21)SERIAL-42',fmt,gs1=True)
 Image.fromarray(np.asarray(zxingcpp.write_barcode_to_image(code,scale=4))).save(OUT/f'{name}.png')
# Fixed virtual-camera pan: left item, both items, right item. YUV420 requires no ffmpeg.
views=[]
for which in ['left','both','right']:
 canvas=Image.new('RGB',(1280,720),(235,235,235))
 if which=='both':
  for i,x in enumerate([20,660]):canvas.paste(Image.open(OUT/f'box-{i+1}.png').resize((480,640)),(x,30))
 else:canvas.paste(Image.open(OUT/f'box-{1 if which=="left" else 2}.png').resize((480,640)),(400,30))
 y,cb,cr=canvas.convert('YCbCr').split()
 views.append(y.tobytes()+cb.resize((640,360),Image.Resampling.BOX).tobytes()+cr.resize((640,360),Image.Resampling.BOX).tobytes())
with (OUT/'items-pan.y4m').open('wb') as f:
 f.write(b'YUV4MPEG2 W1280 H720 F10:1 Ip A1:1 C420jpeg\n')
 for v in views:
  for _ in range(35):f.write(b'FRAME\n'+v)
with (OUT/'items-static.y4m').open('wb') as f:
 f.write(b'YUV4MPEG2 W1280 H720 F10:1 Ip A1:1 C420jpeg\n')
 for _ in range(10):f.write(b'FRAME\n'+views[0])
def pdf_fixture(name):
 fixture=json.loads((ROOT/f'experiments/financial_tables/fixtures/{name}.json').read_text())
 objs=['','','<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>'];kids=[]
 for p in fixture['pages']:
  width=p.get('width',1240);height=p.get('height',1754);commands=[]
  for line in p['lines']:
   text=line['text'].replace('\\','\\\\').replace('(','\\(').replace(')','\\)').replace('\n',' ')
   size=line['h']*.85;scale=line['w']/max(1,len(line['text']))/(size*.6)*100
   commands.append(f'BT /F1 {size:.4f} Tf {scale:.4f} Tz 1 0 0 1 {line["x"]:.4f} {height-line["y"]-size:.4f} Tm ({text}) Tj ET')
  stream='\n'.join(commands);objs.append(f'<< /Length {len(stream.encode())} >>\nstream\n{stream}\nendstream');sid=len(objs)
  objs.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Resources << /Font << /F1 3 0 R >> >> /Contents {sid} 0 R >>');kids.append(f'{len(objs)} 0 R')
 objs[0]='<< /Type /Catalog /Pages 2 0 R >>';objs[1]=f'<< /Type /Pages /Count {len(kids)} /Kids [{" ".join(kids)}] >>'
 body=b'%PDF-1.7\n';offsets=[0]
 for i,o in enumerate(objs):offsets.append(len(body));body+=f'{i+1} 0 obj\n{o}\nendobj\n'.encode()
 xref=len(body);body+=f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()+b''.join(f'{x:010d} 00000 n \n'.encode() for x in offsets[1:])+f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
 (OUT/f'{name}.pdf').write_bytes(body)
for name in ['invoice_basic','bank_basic_dmy','payslip_stacked']:pdf_fixture(name)
(OUT/'expected.json').write_text(json.dumps({'items':items,'gtin':GTIN},indent=2))
(OUT/'manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.name!='manifest.json'},indent=2))
print(f'Generated fictional fixtures in {OUT}')
