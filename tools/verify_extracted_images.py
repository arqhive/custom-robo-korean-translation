"""Read every exported PNG and check dimensions and decoded pixel hashes."""
import json,hashlib
from PIL import Image
from survey_rom import ROOT

rows=json.loads((ROOT/'manifests/all-images.json').read_text(encoding='utf-8'))
errors=[]
for r in rows:
    try:
        with Image.open(ROOT/r['file']) as im:
            im.load()
            assert im.size==(r['width'],r['height']), 'dimensions'
            assert hashlib.sha256(im.convert('RGBA').tobytes()).hexdigest()==r['rgba_sha256'],'pixels'
    except Exception as e:errors.append({'id':r['id'],'error':str(e)})
report={'pngs_checked':len(rows),'errors':errors,'success':not errors}
(ROOT/'manifests/image-export-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
assert not errors
