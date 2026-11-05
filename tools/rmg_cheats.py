"""Write RMG user cheats for a built ROM (test play only): enemy HP 1, player HP full.

Battle HP is a float per side (11/05 save state): side 1 max/current/shown at 0x8023A3F4/F8/FC,
side 2 at 0x8023A40C/10/14; game code addresses them as constants, so they stay put.
RMG names cheat files by the ROM header CRCs, which change with every build.
"""
import sys,struct
from pathlib import Path

RMG=Path.home()/'Desktop/RMG/Config/Cheats-User'

def write(rom_path):
    rom=Path(rom_path).read_bytes()
    c1,c2=struct.unpack_from('>II',rom,0x10);cc=rom[0x3e]
    name=f'{c1:08X}-{c2:08X}-{cc:02X}'
    body=f'''[{c1:08X}-{c2:08X}-C:{cc:02X}]
Name=Custom Robo (J) [KO]

$Enemy HP 1 (one hit)
8123A410 3F80
8123A412 0000

$Player HP Full
8123A3F8 447A
8123A3FA 0000
'''
    RMG.mkdir(parents=True,exist_ok=True)
    out=RMG/f'{name}.cht'
    out.write_text(body,encoding='utf-8')
    return out

if __name__=='__main__':
    print(write(sys.argv[1]))
