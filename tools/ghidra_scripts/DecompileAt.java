// Decompile specific functions by address.
//@category DX
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public class DecompileAt extends GhidraScript {
    @Override public void run() throws Exception {
        Path out=Path.of(getScriptArgs()[0]); Files.createDirectories(out);
        DecompInterface decompiler=new DecompInterface(); decompiler.openProgram(currentProgram);
        StringBuilder index=new StringBuilder();
        for(int i=1;i<getScriptArgs().length;i++){
            long value=Long.decode(getScriptArgs()[i]);
            Address addr=toAddr(value);
            Function f=getFunctionAt(addr);
            if(f==null){
                // try containing function after disassembling
                disassemble(addr);
                f=getFunctionContaining(addr);
            }
            index.append(String.format("0x%x -> ",value)).append(f==null?"NONE":f.getName()+" @ "+f.getEntryPoint()).append('\n');
            if(f==null)continue;
            String name=(f.getName()+"_"+f.getEntryPoint()).replaceAll("[^A-Za-z0-9_.-]","_");
            StringBuilder asm=new StringBuilder();
            for(Instruction ins:currentProgram.getListing().getInstructions(f.getBody(),true))
                asm.append(ins.getAddress()).append("  ").append(ins).append('\n');
            Files.writeString(out.resolve(name+".asm"),asm.toString(),StandardCharsets.UTF_8);
            DecompileResults result=decompiler.decompileFunction(f,120,monitor);
            String c=result.decompileCompleted()?result.getDecompiledFunction().getC():"Failed: "+result.getErrorMessage()+"\n"+asm;
            Files.writeString(out.resolve(name+".c"),c,StandardCharsets.UTF_8);
        }
        decompiler.dispose();
        Files.writeString(out.resolve("index.txt"),index.toString(),StandardCharsets.UTF_8);
        println("Done");
    }
}
