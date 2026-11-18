package com.example.localinventory.framework.system;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Role-based access of the common system framework: roles of a user, the menu tree
 * (system / module / menu) those roles may see, and what each role may do in a program.
 */
@Service
public class SystemAccessService {
    public static final String ADMIN_ROLE = "ADMIN";
    public static final String ADMIN_AUTHORITY = "workspace:admin";

    public record ProgramPermission(boolean query, boolean create, boolean save, boolean delete, boolean print) {
        public static final ProgramPermission ALL = new ProgramPermission(true, true, true, true, true);
        public static final ProgramPermission NONE = new ProgramPermission(false, false, false, false, false);
    }
    /** A menu node: type FOLDER (children) or PROGRAM (programCode). */
    public record MenuView(Long id, String type, String programCode, String name, int order, String icon, List<MenuView> children) {
        public MenuView(String programCode, String name, int order) { this(null, "PROGRAM", programCode, name, order, null, List.of()); }
    }
    public record ModuleView(String code, String name, String icon, List<MenuView> menus) {}
    public record SystemView(String code, String name, List<ModuleView> modules) {}
    public record ProgramInput(String code, String name, List<String> apiPaths, boolean systemProgram) {}

    private final JdbcTemplate jdbc;
    public SystemAccessService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public List<String> rolesOf(String username) {
        return jdbc.queryForList("""
            SELECT ur.role_code FROM sys_user_roles ur JOIN sys_roles r ON r.role_code = ur.role_code
            WHERE ur.username = ? AND r.enabled ORDER BY ur.role_code""", String.class, username);
    }

    public boolean isAdmin(String username, java.util.Collection<String> authorities) {
        return authorities.contains(ADMIN_AUTHORITY) || authorities.contains("ROLE_" + ADMIN_ROLE) || rolesOf(username).contains(ADMIN_ROLE);
    }

    /**
     * Menu tree the user's roles may see (an administrator sees every enabled menu). A folder appears
     * when at least one program below it is visible.
     */
    public List<SystemView> menuTree(String username, boolean admin) {
        List<Map<String, Object>> rows = jdbc.queryForList("""
            SELECT s.system_code, s.system_name, m.module_code, m.module_name, m.icon,
                   mn.menu_id, mn.parent_id, mn.menu_type, mn.program_code, mn.menu_name, mn.sort_order, mn.icon AS menu_icon,
                   (mn.menu_type = 'FOLDER' OR ? OR EXISTS (
                       SELECT 1 FROM sys_role_menus rm JOIN sys_user_roles ur ON ur.role_code = rm.role_code
                       JOIN sys_roles r ON r.role_code = rm.role_code AND r.enabled
                       WHERE rm.menu_id = mn.menu_id AND ur.username = ?)) AS visible
            FROM sys_menus mn
            JOIN sys_modules m ON m.module_code = mn.module_code AND m.enabled
            JOIN sys_systems s ON s.system_code = m.system_code AND s.enabled
            WHERE mn.enabled
            ORDER BY s.sort_order, s.system_code, m.sort_order, m.module_code, mn.sort_order, mn.menu_name""", admin, username);
        Map<String, SystemView> systems = new LinkedHashMap<>();
        Map<String, ModuleView> modules = new LinkedHashMap<>();
        Map<Long, MenuView> nodes = new LinkedHashMap<>();
        Map<Long, Long> parents = new LinkedHashMap<>();
        Map<Long, String> moduleOf = new LinkedHashMap<>();
        for (Map<String, Object> row : rows) {
            if (!Boolean.TRUE.equals(row.get("visible"))) continue;
            SystemView system = systems.computeIfAbsent((String) row.get("system_code"),
                    code -> new SystemView(code, (String) row.get("system_name"), new ArrayList<>()));
            modules.computeIfAbsent((String) row.get("module_code"), code -> {
                ModuleView created = new ModuleView(code, (String) row.get("module_name"), (String) row.get("icon"), new ArrayList<>());
                system.modules().add(created);
                return created;
            });
            Long id = ((Number) row.get("menu_id")).longValue();
            nodes.put(id, new MenuView(id, (String) row.get("menu_type"), (String) row.get("program_code"), (String) row.get("menu_name"),
                    ((Number) row.get("sort_order")).intValue(), (String) row.get("menu_icon"), new ArrayList<>()));
            if (row.get("parent_id") != null) parents.put(id, ((Number) row.get("parent_id")).longValue());
            moduleOf.put(id, (String) row.get("module_code"));
        }
        for (Map.Entry<Long, MenuView> entry : nodes.entrySet()) {
            MenuView parent = nodes.get(parents.get(entry.getKey()));
            if (parent != null) parent.children().add(entry.getValue());
            else modules.get(moduleOf.get(entry.getKey())).menus().add(entry.getValue());
        }
        // Drop folders with no visible program underneath, then modules and systems left empty.
        for (ModuleView module : modules.values()) prune(module.menus());
        for (SystemView system : systems.values()) system.modules().removeIf(module -> module.menus().isEmpty());
        systems.values().removeIf(system -> system.modules().isEmpty());
        return new ArrayList<>(systems.values());
    }

    private static void prune(List<MenuView> menus) {
        for (MenuView menu : menus) if ("FOLDER".equals(menu.type())) prune(menu.children());
        menus.removeIf(menu -> "FOLDER".equals(menu.type()) && menu.children().isEmpty());
    }

    /** What the user may do per program (union over roles). Administrators are not listed: they may do everything. */
    public Map<String, ProgramPermission> programPermissions(String username) {
        Map<String, ProgramPermission> result = new LinkedHashMap<>();
        jdbc.query("""
            SELECT rp.program_code, bool_or(rp.can_query) q, bool_or(rp.can_create) c, bool_or(rp.can_save) s,
                   bool_or(rp.can_delete) d, bool_or(rp.can_print) p
            FROM sys_role_programs rp JOIN sys_user_roles ur ON ur.role_code = rp.role_code
            JOIN sys_roles r ON r.role_code = rp.role_code AND r.enabled
            WHERE ur.username = ? GROUP BY rp.program_code ORDER BY rp.program_code""",
            row -> { result.put(row.getString("program_code"), new ProgramPermission(row.getBoolean("q"), row.getBoolean("c"),
                    row.getBoolean("s"), row.getBoolean("d"), row.getBoolean("p"))); }, username);
        return result;
    }

    /** Programs not yet placed in a menu (shown to administrators so new screens are never lost). */
    public List<MenuView> unassignedPrograms() {
        return jdbc.query("""
            SELECT p.program_code, p.program_name FROM sys_programs p
            WHERE NOT EXISTS (SELECT 1 FROM sys_menus mn WHERE mn.program_code = p.program_code)
            ORDER BY p.program_name""", (row, index) -> new MenuView(row.getString(1), row.getString(2), index));
    }

    /** Screens report themselves; new ones become unassigned programs, known ones refresh their name and APIs. */
    @Transactional
    public int syncPrograms(List<ProgramInput> programs) {
        int added = 0;
        List<String> present = new ArrayList<>();
        for (ProgramInput program : programs) {
            if (program.code() == null || !program.code().matches("[A-Za-z0-9_-]{1,50}") || program.name() == null || program.name().isBlank()) continue;
            present.add(program.code());
            String apis = String.join(",", program.apiPaths() == null ? List.<String>of()
                    : program.apiPaths().stream().filter(path -> path != null && path.matches("/api/[A-Za-z0-9/_-]{1,80}")).distinct().sorted().toList());
            int updated = jdbc.update("UPDATE sys_programs SET program_name = ?, api_paths = ?, system_program = ? WHERE program_code = ?",
                    program.name().trim(), apis, program.systemProgram(), program.code());
            if (updated == 0) {
                jdbc.update("INSERT INTO sys_programs (program_code, program_name, api_paths, system_program) VALUES (?, ?, ?, ?)",
                        program.code(), program.name().trim(), apis, program.systemProgram());
                added++;
            }
        }
        // A screen that no longer exists and was never placed in a menu is forgotten (placed ones stay for the administrator).
        if (!present.isEmpty()) {
            String marks = String.join(",", java.util.Collections.nCopies(present.size(), "?"));
            jdbc.update("DELETE FROM sys_programs p WHERE p.program_code NOT IN (" + marks + ") AND NOT EXISTS (SELECT 1 FROM sys_menus mn WHERE mn.program_code = p.program_code)",
                    present.toArray());
        }
        return added;
    }

    /**
     * Whether a non-administrator may call this API. A path owned by no program is open to any
     * signed-in user; otherwise one of the owning programs must grant the action for one of the roles.
     */
    public boolean allowed(String username, String method, String path) {
        List<Map<String, Object>> owners = jdbc.queryForList("SELECT program_code, api_paths FROM sys_programs WHERE api_paths <> ''");
        List<String> programs = new ArrayList<>();
        for (Map<String, Object> owner : owners)
            for (String prefix : ((String) owner.get("api_paths")).split(","))
                if (path.equals(prefix) || path.startsWith(prefix + "/")) programs.add((String) owner.get("program_code"));
        if (programs.isEmpty()) return true;
        Map<String, ProgramPermission> granted = programPermissions(username);
        for (String program : programs) {
            ProgramPermission permission = granted.get(program);
            if (permission == null) continue;
            boolean ok = switch (method) {
                case "GET", "HEAD", "OPTIONS" -> permission.query();
                // A status action (…/{id}/actions/{name}) changes a record that is there: it goes with 저장, not with 신규.
                // So does attaching a file to it (…/{id}/files).
                case "POST" -> path.matches(".*/\\d+/(actions/[^/]+|files)") ? permission.save() : permission.create();
                case "PUT", "PATCH" -> permission.save();
                case "DELETE" -> path.matches(".*/\\d+/files/\\d+") ? permission.save() : permission.delete();   // taking a file off a record is a change of it
                default -> false;
            };
            if (ok) return true;
        }
        return false;
    }
}
