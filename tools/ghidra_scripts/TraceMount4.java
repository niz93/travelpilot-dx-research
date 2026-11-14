// Trace mount phase 4: callers of request handlers + writers of name slots.
//@category DX
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.TreeSet;

public class TraceMount4 extends GhidraScript {
    @Override public void run() throws Exception {
        Path out=Path.of(getScriptArgs()[0]); Files.createDirectories(out);
        long[] callTargets={0xffd47d60L,0xffd5ab92L,0xffd5b0beL,0xffc3b770L,0xffd48650L,0xffc3d598L,0xffd5aa28L,0xffc4b484L,0xffd6644cL,0xffcebf34L,0xffd529a4L};
        // RAM globals: name slots and capability table inside the SDI state block DAT_ram_000013a8
        long[] dataTargets={0x191bL,0x1923L,0x192bL}; // 0x13a8+0x573/0x57b/0x583
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
        for(long value:dataTargets){
            Address target=toAddr(value); index.append("DATA_TARGET ").append(target).append('\n');
            for(Reference ref:getReferencesTo(target)){
                Address from=ref.getFromAddress(); Function f=getFunctionContaining(from);
                index.append("  ").append(ref.getReferenceType()).append(" from ").append(from)
                    .append(" function=").append(f==null?"none":f.getName()+" @ "+f.getEntryPoint()).append('\n');
                if(f!=null)functions.add(f);
            }
        }
        DecompInterface decompiler=new DecompInterface(); decompiler.openProgram(currentProgram);
        for(Function f:functions){
            String name=(f.getName()+"_"+f.getEntryPoint()).replaceAll("[^A-Za-z0-9_.-]","_");
            StringBuilder asm=new StringBuilder();
            for(Instruction ins:currentProgram.getListing().getInstructions(f.getBody(),true))
                asm.append(ins.getAddress()).append("  ").append(ins).append('\n');
            Files.writeString(out.resolve(name+".asm"),asm.toString(),StandardCharsets.UTF_8);
            DecompileResults result=decompiler.decompileFunction(f,120,monitor);
            String c=result.decompileCompleted()?result.getDecompiledFunction().getC():"Failed: "+result.getErrorMessage()+"\n"+asm;
            Files.writeString(out.resolve(name+".c"),c,StandardCharsets.UTF_8);
        }
        decompiler.dispose(); Files.writeString(out.resolve("index.txt"),index.toString(),StandardCharsets.UTF_8);
        println("Exported "+functions.size()+" caller functions");
    }
}
