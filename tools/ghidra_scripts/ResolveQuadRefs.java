// Resolve V810 MOVHI + MOVEA string addresses for QUADIDX/INFO strings and export their code context.
//@category DX
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.lang.Register;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

public class ResolveQuadRefs extends GhidraScript {
    private Register destination(Instruction ins) {
        for (int operand = ins.getNumOperands() - 1; operand >= 1; operand--) {
            Register reg = ins.getRegister(operand);
            if (reg != null) return reg;
        }
        return null;
    }
    private boolean uses(Instruction ins, Register reg) {
        for (int operand = 0; operand < ins.getNumOperands(); operand++) {
            if (reg.equals(ins.getRegister(operand))) return true;
        }
        return false;
    }
    @Override
    public void run() throws Exception {
        Path out = Path.of(getScriptArgs().length > 0 ? getScriptArgs()[0] : "analysis/quadidx-code");
        Files.createDirectories(out);
        String[] needles = {"QUADIDX.DAT", "INFO.TXT", "CONFIG.SYS", "CAT"};
        Map<Address, String> targets = new HashMap<>();
        Memory memory = currentProgram.getMemory();
        for (String needle : needles) {
            byte[] bytes = needle.getBytes(StandardCharsets.US_ASCII);
            Address cursor = currentProgram.getMinAddress();
            while (cursor != null) {
                Address hit = memory.findBytes(cursor, bytes, null, true, monitor);
                if (hit == null) break;
                // CAT as needle matches inside other words; require boundary for short needles
                if (needle.equals("CAT")) {
                    byte before = memory.getByte(hit.subtract(1));
                    byte after = memory.getByte(hit.add(3));
                    if ((before >= 'A' && before <= 'Z') || (before >= 'a' && before <= 'z')
                        || (after >= 'A' && after <= 'Z') || (after >= 'a' && after <= 'z')) {
                        cursor = hit.add(1);
                        continue;
                    }
                }
                targets.put(hit, needle);
                cursor = hit.add(1);
            }
        }
        Listing listing = currentProgram.getListing();
        StringBuilder index = new StringBuilder();
        StringBuilder contexts = new StringBuilder();
        Set<Function> functions = new HashSet<>();
        for (Instruction ins : listing.getInstructions(true)) {
            if (!ins.getMnemonicString().equalsIgnoreCase("MOVHI")) continue;
            Scalar high = ins.getScalar(0);
            Register reg = destination(ins);
            if (high == null || reg == null) continue;
            Instruction next = ins.getNext();
            for (int distance = 0; distance < 8 && next != null; distance++, next = next.getNext()) {
                if (!next.getMnemonicString().equalsIgnoreCase("MOVEA") || !uses(next, reg)) continue;
                Scalar low = next.getScalar(0);
                if (low == null) continue;
                long address = (((high.getUnsignedValue() & 0xffffL) << 16)
                    + (short)(low.getUnsignedValue() & 0xffff)) & 0xffffffffL;
                Address target = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(address);
                if (!targets.containsKey(target)) continue;
                index.append(targets.get(target)).append(" @ ").append(target).append(" referenced by ")
                    .append(ins.getAddress()).append(" / ").append(next.getAddress()).append('\n');
                Function f = getFunctionContaining(ins.getAddress());
                if (f != null) {
                    functions.add(f);
                    index.append("  function ").append(f.getName()).append(" @ ").append(f.getEntryPoint()).append('\n');
                }
                contexts.append("\n=== ").append(targets.get(target)).append(" @ ").append(ins.getAddress())
                    .append(" function ").append(f == null ? "none" : f.getName()).append(" ===\n");
                Instruction cursor = ins;
                for (int i = 0; i < 20 && cursor != null; i++) cursor = cursor.getPrevious();
                for (int i = 0; i < 65 && cursor != null; i++, cursor = cursor.getNext()) {
                    contexts.append(cursor.getAddress()).append("  ").append(cursor).append('\n');
                }
                break;
            }
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        int number = 0;
        for (Function f : functions) {
            String name = String.format("v810_%03d_%s_%s", number++, f.getName(), f.getEntryPoint())
                .replaceAll("[^A-Za-z0-9_.-]", "_");
            StringBuilder asm = new StringBuilder();
            for (Instruction instruction : listing.getInstructions(f.getBody(), true)) {
                asm.append(instruction.getAddress()).append("  ").append(instruction).append('\n');
            }
            Files.writeString(out.resolve(name + ".asm"), asm.toString(), StandardCharsets.UTF_8);
            DecompileResults result = decompiler.decompileFunction(f, 120, monitor);
            String text = result.decompileCompleted()
                ? result.getDecompiledFunction().getC()
                : "Decompilation failed: " + result.getErrorMessage() + "\n" + asm;
            Files.writeString(out.resolve(name + ".c"), text, StandardCharsets.UTF_8);
        }
        decompiler.dispose();
        Files.writeString(out.resolve("resolved-index.txt"), index.toString(), StandardCharsets.UTF_8);
        Files.writeString(out.resolve("resolved-contexts.asm"), contexts.toString(), StandardCharsets.UTF_8);
        println("Resolved references, exported " + functions.size() + " functions to " + out.toAbsolutePath());
    }
}
