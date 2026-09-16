import sys,pickle,struct,collections,bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
exec(open('scratch/gx/tables.py').read())
d=D.parse(open('extracted/sys/main.dol','rb').read())
print("data sections:")
for s in d.sections:
    if not s.is_text: print("  %s @0x%08X size %d (0x%X) end 0x%08X"%(s.name,s.address,s.size,s.size,s.end))
print("BSS 0x%08X size %d end 0x%08X"%(d.bss_address,d.bss_size,d.bss_address+d.bss_size))
# MMIO-looking constants in data
hits=[]
for s in d.sections:
    if s.is_text: continue
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size-3,4):
        v=struct.unpack_from('>I',b,i)[0]
        if 0xCC000000<=v<0xCC008200 or 0x0C000000<=v<0x0C008200 or 0xC8000000<=v<0xC8400000:
            hits.append((s.address+i,v,s.name))
print("\nMMIO-valued u32 in data sections:",len(hits))
R13=0x8034E720;R2=0x80350000
for a,v,sn in hits:
    print("  0x%08X = 0x%08X  (%s)  r13%+d  r2%+d"%(a,v,sn,a-R13,a-R2))
