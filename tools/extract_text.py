from pathlib import Path
import json,struct,re,hashlib,html
from survey_rom import decode,ROOT

def main():
    rom=(ROOT/'Custom Robo (Japan).z64').read_bytes()
    count=struct.unpack_from('>I',rom,0x814e0)[0]
    offsets=struct.unpack_from('>'+str(count)+'I',rom,0x814e4)
    out=ROOT/'work/extracted/scripts';out.mkdir(parents=True,exist_ok=True)
    entries=[];files=[];errors=[]
    for i,relative in enumerate(offsets):
        offset=0x31c290+relative;raw,used=decode(rom,offset)
        size,n1,n2,start,extra=struct.unpack_from('>IHHII',raw)
        assert size==len(raw) and 16<=start<=len(raw)
        (out/f'{i:03d}.bin').write_bytes(raw)
        text=raw[start:].decode('euc_jp')
        assert text.encode('euc_jp')==raw[start:]
        position=start
        for index,value in enumerate(text.split('\0')):
            encoded=value.encode('euc_jp')
            if value:
                # These are extraction categories, not proof of every string's runtime use.
                kind='dialogue' if re.search(r'\$(?:W|R|P|F\d\d|C\d\d|A\d\d)',value) else 'label_or_internal'
                entries.append({'id':f'S{i:03d}-{index:04d}','script':i,'offset':position,'pool_offset':position-start,'bytes':len(encoded),'kind':kind,'source':value,'translation':None})
            position+=len(encoded)+1
        files.append({'id':i,'rom_offset':offset,'table_entry':0x814e4+i*4,'compressed_size':int.from_bytes(rom[offset:offset+4],'big'),'decoded_size':size,'string_pool':start,'header_count1':n1,'header_count2':n2,'header_extra_offset':extra,'sha256':hashlib.sha256(raw).hexdigest()})
    (ROOT/'manifests/script-files.json').write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding='utf-8')
    dest=ROOT/'work/translation';dest.mkdir(parents=True,exist_ok=True)
    (dest/'source-texts.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
    unique={}
    for e in entries:
        u=unique.setdefault(e['source'],{'id':'T'+hashlib.sha1(e['source'].encode()).hexdigest()[:12],'source':e['source'],'kind':e['kind'],'occurrences':[],'translation':None})
        u['occurrences'].append(e['id'])
    (dest/'unique-texts.json').write_text(json.dumps(list(unique.values()),ensure_ascii=False,indent=2),encoding='utf-8')
    report={'script_files':len(files),'string_occurrences':len(entries),'unique_strings':len(unique),'dialogue_unique':sum(x['kind']=='dialogue' for x in unique.values()),'unique_characters':sum(len(x['source']) for x in unique.values()),'script_pool_encoding_roundtrip':True,'other_text_sources_complete':False}
    (ROOT/'manifests/text-extraction.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
