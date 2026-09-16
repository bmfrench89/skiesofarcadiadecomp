import sys, pickle, json, collections, struct
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode as _dec
class PD:
    decode=staticmethod(_dec)

SCR = r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d = D.parse(open('extracted/sys/main.dol','rb').read())
funcs = pickle.load(open(SCR+r'\skies_funcs.pkl','rb'))
funcs.sort()
fstarts = [f[0] for f in funcs]
import bisect
def func_of(a):
    i = bisect.bisect_right(fstarts, a)-1
    if i<0: return None
    f=funcs[i]
    if f[0] <= a < f[0]+f[1]: return f
    return f  # nearest preceding even if size mismatched
def func_exact(a):
    i = bisect.bisect_right(fstarts, a)-1
    if i<0: return None
    f=funcs[i]
    return f if f[0] <= a < f[0]+f[1] else None

TEXT = [s for s in d.sections if s.is_text]
print("text sections:", [(s.name,hex(s.address),s.size) for s in TEXT])

# decode everything once
insns = {}   # addr -> Insn
words  = {}
for s in TEXT:
    blob = d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0, s.size, 4):
        a = s.address+i
        w = struct.unpack_from('>I', blob, i)[0]
        words[a]=w
        insns[a]=PD.decode(w,a)
print("decoded words:", len(insns))

# branch targets (for resetting const-prop)
targets=set()
for a,ins in insns.items():
    if ins.valid and ins.is_direct_branch:
        try:
            t=ins.target
        except Exception:
            t=None
        if t is not None: targets.add(t)
targets |= set(fstarts)
print("branch targets:", len(targets))

STORE_INT = {'stw','stwu','stwx','stwux','stb','stbu','stbx','stbux','sth','sthu','sthx','sthux',
             'stmw','stswi','stswx','stwbrx','sthbrx'}
STORE_FP  = {'stfs','stfsu','stfsx','stfsux','stfd','stfdu','stfdx','stfdux','stfiwx'}
STORE_PS  = {'psq_st','psq_stu','psq_stx','psq_stux'}
LOAD_INT  = {'lwz','lwzu','lwzx','lwzux','lbz','lbzu','lbzx','lbzux','lha','lhau','lhz','lhzu',
             'lhax','lhaux','lhzx','lhzux','lmw','lwbrx','lhbrx'}
LOAD_FP   = {'lfs','lfsu','lfsx','lfsux','lfd','lfdu','lfdx','lfdux'}
LOAD_PS   = {'psq_l','psq_lu','psq_lx','psq_lux'}
ALLST = STORE_INT|STORE_FP|STORE_PS
ALLLD = LOAD_INT|LOAD_FP|LOAD_PS

DFORM_MEM = ALLST|ALLLD  # d-form ones have imm; x-form have rb

def is_dform(m):
    return not m.endswith('x')

# ---- constant propagation over a linear walk of each text section ----
# regs: dict r -> int value (32-bit)
memops = []   # (addr, mnem, ea, base_reg, how)
lis_sites = collections.defaultdict(list)  # value -> [addr]

for s in TEXT:
    regs = {}
    a = s.address
    while a < s.address + s.size:
        if a in targets:
            regs = {}
        ins = insns[a]
        m = ins.mnemonic
        if ins.valid:
            # record memory op EA if base known
            if m in DFORM_MEM:
                ra = ins.ra
                if is_dform(m):
                    if ra == 0:
                        ea = ins.imm & 0xFFFFFFFF
                        memops.append((a,m,ea,ra,'ra0'))
                    elif ra in regs:
                        ea = (regs[ra] + ins.imm) & 0xFFFFFFFF
                        memops.append((a,m,ea,ra,'const'))
                else:
                    if ra in regs and ins.rb in regs:
                        ea = (regs[ra]+regs[ins.rb]) & 0xFFFFFFFF
                        memops.append((a,m,ea,ra,'constx'))
                    elif ra==0 and ins.rb in regs:
                        memops.append((a,m,regs[ins.rb]&0xFFFFFFFF,ra,'constx0'))
            # update regs
            if m=='lis' or (m=='addis' and ins.ra==0):
                v=(ins.imm<<16)&0xFFFFFFFF
                regs[ins.rd]=v
                if (v>>16) in (0xCC00,0xCC01,0xCC02,0xCD00,0xCD01,0xC800,0xC000,0xCC80):
                    lis_sites[v].append(a)
            elif m=='li' or (m=='addi' and ins.ra==0):
                regs[ins.rd]=ins.imm & 0xFFFFFFFF
            elif m=='addi' and ins.ra in regs:
                regs[ins.rd]=(regs[ins.ra]+ins.imm)&0xFFFFFFFF
            elif m=='addis' and ins.ra in regs:
                regs[ins.rd]=(regs[ins.ra]+(ins.imm<<16))&0xFFFFFFFF
            elif m=='ori' and ins.ra in regs:
                regs[ins.rd]=(regs[ins.ra]|(ins.imm&0xFFFF))&0xFFFFFFFF
            elif m=='oris' and ins.ra in regs:
                regs[ins.rd]=(regs[ins.ra]|((ins.imm&0xFFFF)<<16))&0xFFFFFFFF
            elif m in ('or','mr') and ins.ra in regs and (ins.rb==ins.ra or m=='mr'):
                regs[ins.rd]=regs[ins.ra]
            else:
                # invalidate destinations
                if m in ALLLD:
                    regs.pop(ins.rd, None)
                    if m.endswith('u') and ins.ra>=0: regs.pop(ins.ra,None)
                elif ins.rd >= 0 and m not in ALLST and not ins.is_branch and not m.startswith('cmp') and not m.startswith('st'):
                    regs.pop(ins.rd, None)
                if ins.is_call:
                    # volatile regs clobbered
                    for r in list(regs):
                        if r==0 or 3<=r<=12: regs.pop(r,None)
        else:
            regs={}
        a+=4

print("memops with known EA:", len(memops))
pickle.dump({'memops':memops,'lis_sites':dict(lis_sites)}, open('scratch/gx/memops.pkl','wb'))

# --- gather pipe stores ---
GP = 0xCC008000
gp = [x for x in memops if x[2]==GP and x[1] in ALLST]
print("=== stores with EA == 0xCC008000:", len(gp))
c=collections.Counter(x[1] for x in gp)
print("by mnemonic:", dict(c.most_common()))
gpl = [x for x in memops if x[2]==GP and x[1] in ALLLD]
print("loads from 0xCC008000:", len(gpl), collections.Counter(x[1] for x in gpl))
