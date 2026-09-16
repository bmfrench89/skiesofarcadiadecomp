import sys, pickle, struct, collections, bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode

SCR = r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d = D.parse(open('extracted/sys/main.dol','rb').read())
funcs = sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')))
fstarts=[f[0] for f in funcs]
def func_of(a):
    i=bisect.bisect_right(fstarts,a)-1
    if i<0: return None
    f=funcs[i]
    return f if f[0]<=a<f[0]+f[1] else ('?',0,'<gap@%08X>'%f[0],'?')

TEXT=[s for s in d.sections if s.is_text]
TLO,THI = 0x80003100, 0x80005600+2781664

DEST_RD = set('''addi addis addic addic. subfic mulli lwz lwzu lbz lbzu lhz lhzu lha lhau
 lwzx lwzux lbzx lbzux lhzx lhzux lhax lhaux add addc adde addze addme subf subfc subfe
 subfze subfme neg mullw mulhw mulhwu divw divwu mfspr mfcr mfmsr mftb mfsr lwbrx lhbrx
 lswi lswx lwarx li lis mr'''.split())
DEST_RA = set('''ori oris xori xoris andi. andis. rlwinm rlwimi rlwnm and andc or orc nand
 nor xor eqv slw srw sraw srawi extsb extsh cntlzw'''.split())
NO_GPR = set('''stw stwu stwx stwux stb stbu stbx stbux sth sthu sthx sthux stmw stswi stswx
 stwbrx sthbrx stfs stfsu stfsx stfsux stfd stfdu stfdx stfdux stfiwx psq_st psq_stu psq_stx
 psq_stux b bc bclr bcctr sc rfi sync isync twi tw dcbt dcbst dcbf dcbi dcbz dcbz_l icbi
 cmp cmpi cmpl cmpli crand cror crxor crnand crnor creqv crandc crorc mcrf mcrxr mcrfs
 mtspr mtmsr mtsr mtsrin mtcrf mtfsf mtfsb0 mtfsb1 mtfsfi mffs fmr fneg fabs fnabs frsp
 fctiw fctiwz fadd fsub fmul fdiv fmadd fmsub fnmadd fnmsub fres frsqrte fsel fsqrt
 fcmpo fcmpu fadds fsubs fmuls fdivs fmadds fmsubs fnmadds fnmsubs
 lfs lfsx lfd lfdx psq_l psq_lx eieio tlbie tlbsync'''.split())
UPD_RA = set('''lwzu lwzux lbzu lbzux lhzu lhzux lhau lhaux stwu stwux stbu stbux sthu sthux
 lfsu lfsux lfdu lfdux stfsu stfsux stfdu stfdux psq_lu psq_lux psq_stu psq_stux'''.split())
PS = set(m for m in '''ps_mul ps_sum0 ps_madd ps_merge00 ps_muls0 ps_madds1 ps_madds0 ps_merge10
 ps_msub ps_merge11 ps_nmsub ps_sum1 ps_neg ps_muls1 ps_merge01 ps_sub ps_nmadd ps_cmpo0
 ps_cmpo1 ps_cmpu0 ps_cmpu1 ps_add ps_div ps_abs ps_nabs ps_res ps_rsqrte ps_sel'''.split())
NO_GPR |= PS

STORES = set(m for m in NO_GPR if m.startswith('st') or m.startswith('psq_st'))
LOADS  = set('''lwz lwzu lwzx lwzux lbz lbzu lbzx lbzux lhz lhzu lhzx lhzux lha lhau lhax lhaux
 lmw lwbrx lhbrx lfs lfsu lfsx lfsux lfd lfdu lfdx lfdux psq_l psq_lu psq_lx psq_lux'''.split())
MEM = STORES|LOADS
XFORM = set(m for m in MEM if m.endswith('x'))

# decode
insns={}
for s in TEXT:
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size,4):
        a=s.address+i; w=struct.unpack_from('>I',b,i)[0]
        insns[a]=decode(w,a)

# targets: direct branch targets + function starts + every word anywhere in the DOL
# that points into text (covers switch jump tables and function-pointer tables)
targets=set(fstarts)
for a,ins in insns.items():
    if ins.valid and ins.is_direct_branch and ins.target is not None:
        targets.add(ins.target)
ptrtab=0
for s in d.sections:
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size-3,4):
        v=struct.unpack_from('>I',b,i)[0]
        if TLO<=v<THI and (v&3)==0:
            if v not in targets: ptrtab+=1
            targets.add(v)
print("targets (branch+func+word-ptrs):",len(targets),"added-from-words:",ptrtab)

memops=[]   # (addr,mnem,ea,srcreg)
unresolved=collections.Counter()
lis_sites=collections.defaultdict(list)
for s in TEXT:
    regs={}
    a=s.address; end=s.address+s.size
    while a<end:
        if a in targets: regs={}
        ins=insns[a]; m=ins.mnemonic
        if not ins.valid:
            regs={}; a+=4; continue
        if m in MEM:
            ra=ins.ra
            ea=None
            if m in XFORM:
                if (ra==0 or ra in regs) and ins.rb in regs:
                    ea=((regs.get(ra,0) if ra else 0)+regs[ins.rb])&0xFFFFFFFF
            else:
                if ra==0: ea=ins.imm&0xFFFFFFFF
                elif ra in regs: ea=(regs[ra]+ins.imm)&0xFFFFFFFF
            if ea is not None: memops.append((a,m,ea,ra))
            else: unresolved[m]+=1
        # ---- update reg state ----
        if m=='lis' or (m=='addis' and ins.ra==0):
            v=(ins.imm<<16)&0xFFFFFFFF; regs[ins.rd]=v
            if (v>>24)in(0xCC,0xCD,0xC8,0xC0): lis_sites[v].append(a)
        elif m=='addi' and ins.ra==0: regs[ins.rd]=ins.imm&0xFFFFFFFF
        elif m=='addi' and ins.ra in regs: regs[ins.rd]=(regs[ins.ra]+ins.imm)&0xFFFFFFFF
        elif m=='addis' and ins.ra in regs: regs[ins.rd]=(regs[ins.ra]+(ins.imm<<16))&0xFFFFFFFF
        elif m=='ori' and ins.ra in regs: regs[ins.rd]=(regs[ins.ra]|(ins.imm&0xFFFF))&0xFFFFFFFF
        elif m=='oris' and ins.ra in regs: regs[ins.rd]=(regs[ins.ra]|((ins.imm&0xFFFF)<<16))&0xFFFFFFFF
        elif m=='or' and ins.rd==ins.rb and ins.rd in regs: regs[ins.ra]=regs[ins.rd]  # mr
        else:
            if m in DEST_RD:
                regs.pop(ins.rd,None)
                if m=='lmw':
                    for r in range(ins.rd,32): regs.pop(r,None)
            elif m in DEST_RA: regs.pop(ins.ra,None)
            elif m in NO_GPR: pass
            else: regs={}   # unknown mnemonic -> conservative
            if m in UPD_RA: regs.pop(ins.ra,None)
        if ins.valid and ins.is_call:
            for r in list(regs):
                if r==0 or 3<=r<=12: regs.pop(r,None)
        if ins.valid and (m=='b' or (m in('bclr','bcctr') and ins.is_unconditional)):
            regs={}
        a+=4

print("resolved memops:",len(memops)," unresolved:",sum(unresolved.values()))
pickle.dump({'memops':memops,'lis':dict(lis_sites),'targets':targets},open('scratch/gx/m2.pkl','wb'))

GP=0xCC008000
gp=[x for x in memops if x[2]==GP]
print("\n=== EA==0xCC008000 total ops:",len(gp))
print("   by mnemonic:",dict(collections.Counter(x[1] for x in gp).most_common()))
print("   stores:",sum(1 for x in gp if x[1] in STORES),"loads:",sum(1 for x in gp if x[1] in LOADS))
print("\n=== lis sites by value ===")
for v,ls in sorted(lis_sites.items()):
    print(f"  lis 0x{v:08X}  x{len(ls)}")
