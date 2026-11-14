// Trace mount phase 2: callers of dispatcher; scan instructions for handle address materialization.
//@category DX
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.scalar.Scalar;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.TreeSet;

public class TraceMount2 extends GhidraScript {
    @Override public void run() throws Exception {
        Path out=Path.of(getScriptArgs()[0]); Files.createDirectories(out);
        long[] callTargets={0xffc4522cL,0xffc3d952L,0xffd48838L,0xffc3da5aL,0xffc489d8L,0xffc454feL,0xffc456f4L,0xffc48e5eL,0xffc50232L};
        StringBuilder index=new StringBuilder();
        Set<Function> functions=new TreeSet<>((a,b)->a.getEntryPoint().compareTo(b.getEntryPoint()));
        for(long value:callTargets){
            Address target=toAddr(value); index.append("CALL_TARGET ").append(target).append('\n');
            for(Reference ref:getReferencesTo(target)){
                Address from=ref.getFromAddress(); Function f=getFunctionContaining(from);
                index.append("  ").append(ref.getReferenceType()).append(" from ").append(from)
                    .append(" function=").append(f==null?"none":f.getName()+" @ "+f.getEntryPoint()).append('\n');
                if(f!=null)functions.add(f);
            }
        }
        // scan for scalar materializations of the NAV handle global 0xffc08edc
        index.append("SCAN scalars for 0xffc08edc (lo=0x8edc sign-ext 0xffff8edc; hi=0xffc1)\n");
        java.util.Iterator<Instruction> iter=currentProgram.getListing().getInstructions(true);
        while(iter.hasNext()){
            Instruction ins=iter.next();
            for(int i=0;i<ins.getNumOperands();i++){
                for(Object obj:ins.getOpObjects(i)){
                    if(obj instanceof Scalar){
                        long v=((Scalar)obj).getValue();
                        if(v==0xffc08edcL||v==0xffff8edcL||v==0x8edcL){
                            Function f=getFunctionContaining(ins.getAddress());
                            index.append("  HIT ").append(ins.getAddress()).append(" ")
                                .append(f==null?"none":f.getName()+" @ "+f.getEntryPoint())
                                .append(" :: ").append(ins).append('\n');
                        }
                    }
                }
            }
        }
        DecompInterface decompiler=new DecompInterface(); decompiler.openProgram(currentProgram);
        for(Function f:functions){
            String name=(f.getName()+"_"+f.getEntryPoint()).replaceAll("[^A-Za-z0-9_.-]","_");
            StringBuilder asm=new StringBuilder();
            for(Instruction fi:currentProgram.getListing().getInstructions(f.getBody(),true))
                asm.append(fi.getAddress()).append("  ").append(fi).append('\n');
            Files.writeString(out.resolve(name+".asm"),asm.toString(),StandardCharsets.UTF_8);
            DecompileResults result=decompiler.decompileFunction(f,120,monitor);
            String c=result.decompileCompleted()?result.getDecompiledFunction().getC():"Failed: "+result.getErrorMessage()+"\n"+asm;
            Files.writeString(out.resolve(name+".c"),c,StandardCharsets.UTF_8);
        }
        // also decompile requested bodies directly even if no callers found
        for(long extra:callTargets){
            Function f=getFunctionAt(toAddr(extra));
            if(f==null)continue;
            String name=(f.getName()+"_"+f.getEntryPoint()).replaceAll("[^A-Za-z0-9_.-]","_");
            if(!functions.contains(f)){
                StringBuilder asm=new StringBuilder();
                for(Instruction fi:currentProgram.getListing().getInstructions(f.getBody(),true))
                    asm.append(fi.getAddress()).append("  ").append(fi).append('\n');
                Files.writeString(out.resolve(name+".asm"),asm.toString(),StandardCharsets.UTF_8);
                DecompileResults result=decompiler.decompileFunction(f,120,monitor);
                String c=result.decompileCompleted()?result.getDecompiledFunction().getC():"Failed: "+result.getErrorMessage()+"\n"+asm;
                Files.writeString(out.resolve(name+".c"),c,StandardCharsets.UTF_8);
            }
        }
        decompiler.dispose(); Files.writeString(out.resolve("index.txt"),index.toString(),StandardCharsets.UTF_8);
        println("Exported "+functions.size()+" caller functions");
    }
}
