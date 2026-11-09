import com.sun.source.tree.*;
import com.sun.source.util.*;
import javax.tools.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.stream.Collectors;

public class JavaMethodAst {

    record Parsed(CompilationUnitTree unit, JavacTask task) {}

    public static void main(String[] args) {
        if (args.length < 3) {
            System.out.println(escapeJson("Missing arguments: sourcePath, membersPath, className"));
            System.exit(1);
        }

        try {
            String sourcePath = args[0];
            String membersPath = args[1];
            String targetClassName = args[2];

            String source = Files.readString(Path.of(sourcePath), StandardCharsets.UTF_8);
            String members = Files.readString(Path.of(membersPath), StandardCharsets.UTF_8);

            Parsed original = parse(source, sourcePath);
            ClassTree targetClass = findTargetClass(original.unit(), targetClassName);

            String probeSource = "class __MemberProbe__ {\n" + members + "\n}";
            Parsed probeParsed = parse(probeSource, "Probe.java");
            ClassTree probeClass = findTargetClass(probeParsed.unit(), "__MemberProbe__");

            Set<String> existingSigs = targetClass.getMembers().stream()
                    .filter(m -> m instanceof MethodTree)
                    .map(m -> getSignature((MethodTree) m))
                    .collect(Collectors.toSet());

            List<MethodTree> newMethods = methodsOnly(probeParsed.unit(), probeClass);

            if (newMethods.isEmpty()) throw new RuntimeException("No valid methods found in members");

            Set<String> newSigs = new HashSet<>();
            List<String> addedNames = new ArrayList<>();

            for (MethodTree m : newMethods) {
                String sig = getSignature(m);
                if (existingSigs.contains(sig) || newSigs.contains(sig)) {
                    throw new RuntimeException("Duplicate method signature detected: " + sig);
                }
                newSigs.add(sig);
                addedNames.add(m.getName().toString());
            }

            long end = Trees.instance(original.task()).getSourcePositions().getEndPosition(original.unit(), targetClass);
            if (end <= 0 || end > source.length() || source.charAt((int) end - 1) != '}') {
                throw new RuntimeException("Could not determine precise end position for class");
            }

            int insertByteLen = source.substring(0, (int) end - 1).getBytes(StandardCharsets.UTF_8).length;

            System.out.printf("{\"ok\":true,\"insert_byte\":%d,\"class_name\":\"%s\",\"added_methods\":[%s]}%n",
                    insertByteLen, targetClassName, addedNames.stream().map(JavaMethodAst::escapeJson).collect(Collectors.joining(",")));

        } catch (Exception e) {
            System.out.printf("{\"ok\":false,\"error\":%s}%n", escapeJson(e.getMessage()));
            System.exit(1);
        }
    }

    private static Parsed parse(String text, String filename) throws Exception {
        DiagnosticCollector<JavaFileObject> collector = new DiagnosticCollector<>();
        JavaCompiler tool = ToolProvider.getSystemJavaCompiler();
        StandardJavaFileManager fm = tool.getStandardFileManager(null, null, null);
        JavaFileObject file = new SimpleJavaFileObject(java.net.URI.create("string:///" + filename), JavaFileObject.Kind.SOURCE) {
            @Override public CharSequence getCharContent(boolean ignoreEncodingErrors) { return text; }
        };

        JavacTask task = (JavacTask) tool.getTask(null, fm, collector, List.of("-proc:none"), null, List.of(file));
        Iterable<? extends CompilationUnitTree> units = task.parse();
        CompilationUnitTree unit = units.iterator().next();

        for (Diagnostic<? extends JavaFileObject> d : collector.getDiagnostics()) {
            if (d.getKind() == Diagnostic.Kind.ERROR) {
                throw new RuntimeException(d.getMessage(java.util.Locale.ROOT));
            }
        }
        return new Parsed(unit, task);
    }

    private static ClassTree findTargetClass(CompilationUnitTree unit, String name) throws Exception {
        List<ClassTree> classes = unit.getTypeDecls().stream()
            .filter(t -> t instanceof ClassTree && ((ClassTree) t).getSimpleName().toString().equals(name))
            .map(t -> (ClassTree) t).toList();
        if (classes.size() != 1) throw new Exception("Expected exactly one class: " + name);
        return classes.get(0);
    }

    private static String getSignature(MethodTree m) {
        String params = m.getParameters().stream()
                .map(p -> p.getType().toString())
                .collect(Collectors.joining(","));
        return m.getName().toString() + "(" + params + ")";
    }

    private static String escapeJson(String s) {
        StringBuilder sb = new StringBuilder();
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\b' -> sb.append("\\b");
                case '\f' -> sb.append("\\f");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < 32) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
                }
            }
        }
        return "\"" + sb.toString() + "\"";
    }
private static List<MethodTree> methodsOnly(CompilationUnitTree unit, ClassTree probe) {
    if (unit.getTypeDecls().size() != 1) {
        throw new RuntimeException("Unit must contain exactly one type declaration");
    }
    if (unit.getPackageName() != null) {
        throw new RuntimeException("Package declaration is not allowed");
    }
    if (probe.getMembers().isEmpty()) {
        throw new RuntimeException("Class members must not be empty");
    }

    List<MethodTree> methods = new ArrayList<>();
    for (Tree member : probe.getMembers()) {
        if (!(member instanceof MethodTree method)) {
            throw new RuntimeException("Only method declarations are allowed");
        }
        if (method.getReturnType() == null || method.getName().contentEquals("<init>")) {
            throw new RuntimeException("Only method declarations are allowed");
        }
        methods.add(method);
    }
    return methods;
}

}
