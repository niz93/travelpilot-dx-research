// Find references (including via pointer tables) to the QUADIDX.DAT string and export referring functions.
//@category DX
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;
import java.util.TreeSet;

public class FindStringXrefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        Path out = Path.of(getScriptArgs().length > 0 ? getScriptArgs()[0] : "analysis/quadidx-xrefs");
        String needle = getScriptArgs().length > 1 ? getScriptArgs()[1] : "QUADIDX.DAT";
        Files.createDirectories(out);
        Memory memory = currentProgram.getMemory();
        byte[] bytes = needle.getBytes(StandardCharsets.US_ASCII);
        Listing listing = currentProgram.getListing();
        StringBuilder report = new StringBuilder();
        Set<Function> functions = new HashSet<>();
        Set<Address> hits = new TreeSet<>();
        Address cursor = currentProgram.getMinAddress();
        while (cursor != null) {
            Address hit = memory.findBytes(cursor, bytes, null, true, monitor);
            if (hit == null) break;
            hits.add(hit);
            cursor = hit.add(1);
        }
        report.append("String '").append(needle).append("' found at:\n");
        for (Address hit : hits) report.append("  ").append(hit).append('\n');
        // 1) Ghidra references
        for (Address hit : hits) {
            ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(hit);
            for (Reference ref : refs) {
                report.append("  ref ").append(ref.getReferenceType()).append(" from ").append(ref.getFromAddress()).append('\n');
                Function f = getFunctionContaining(ref.getFromAddress());
                if (f != null) { functions.add(f); report.append("    function ").append(f.getName()).append('\n'); }
            }
        }
        // 2) raw u32 pointer scan over all memory (little-endian)
        for (Address hit : hits) {
            long ptr = hit.getOffset() & 0xffffffffL;
            byte[] pat = new byte[] { (byte) ptr, (byte) (ptr >> 8), (byte) (ptr >> 16), (byte) (ptr >> 24) };
            Address scan = currentProgram.getMinAddress();
            while (scan != null) {
                Address found = memory.findBytes(scan, pat, null, true, monitor);
                if (found == null) break;
                report.append("  u32 ptr 0x").append(Long.toHexString(ptr)).append(" stored at ").append(found).append('\n');
                Function f = getFunctionContaining(found);
                if (f != null) { functions.add(f); report.append("    function ").append(f.getName()).append('\n'); }
                // also: code that loads found (address of the pointer cell) via MOVHI/MOVEA
                scan = found.add(4);
            }
        }
        // export functions
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
        Files.writeString(out.resolve("xrefs.txt"), report.toString(), StandardCharsets.UTF_8);
        println(report.toString());
        println("Exported " + functions.size() + " functions to " + out.toAbsolutePath());
    }
}
