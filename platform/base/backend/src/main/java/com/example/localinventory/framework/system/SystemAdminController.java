package com.example.localinventory.framework.system;

import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Administration of the common system framework (administrators only; see WorkspaceSecurity):
 * users and approval, roles, modules, menus (메뉴 tree), menu and program permissions.
 */
@RestController
@RequestMapping("/api/system")
public class SystemAdminController {
    private final JdbcTemplate jdbc;
    private final PasswordEncoder encoder;
    private final PasswordPolicy policy;
    public SystemAdminController(JdbcTemplate jdbc, PasswordEncoder encoder, PasswordPolicy policy) { this.jdbc = jdbc; this.encoder = encoder; this.policy = policy; }

    private static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST, message); }
    private static ResponseStatusException conflict(String message) { return new ResponseStatusException(HttpStatus.CONFLICT, message); }
    private static String text(Object value) { return value == null ? "" : value.toString().trim(); }
    private static final int MAX_ICON = 80_000;  // characters of an SVG data: URL (about 58KB of SVG)
    /** An icon is a built-in name or an uploaded vector image (SVG as a data: URL); empty means the default. */
    private static String icon(String value) {
        String icon = text(value);
        if (icon.isEmpty() || icon.matches("[a-z][a-z0-9-]{0,29}")) return icon;
        if (icon.matches("data:image/svg\\+xml;base64,[A-Za-z0-9+/=]+") && icon.length() <= MAX_ICON) return icon;
        throw bad("아이콘은 내장 아이콘 이름이거나 60KB 이하의 SVG 이미지여야 합니다.");
    }
    private static void code(String value, String label) { if (!value.matches("[A-Za-z][A-Za-z0-9_]{1,49}")) throw bad(label + "는 영문으로 시작하는 2~50자의 영문·숫자·밑줄이어야 합니다."); }

    // ---- users and approval
    public record UserInput(String displayName, String email, String status, List<String> roles) {}
    public record PasswordInput(String password) {}

    @GetMapping("/users")
    public List<Map<String, Object>> users() {
        return jdbc.queryForList("""
            SELECT u.username, u.display_name AS "displayName", COALESCE(u.email, '') AS email, u.status,
                   COALESCE(TO_CHAR(u.requested_at, 'YYYY-MM-DD"T"HH24:MI:SS'), '') AS "requestedAt",
                   COALESCE(u.approved_by, '') AS "approvedBy",
                   COALESCE((SELECT STRING_AGG(ur.role_code, ',' ORDER BY ur.role_code) FROM sys_user_roles ur WHERE ur.username = u.username), '') AS roles
            FROM workspace_users u ORDER BY (u.status = 'PENDING') DESC, u.username""");
    }

    @PutMapping("/users/{username}")
    @Transactional
    public Map<String, Object> saveUser(@PathVariable String username, @RequestBody UserInput input, Authentication me) {
        String status = text(input.status());
        if (!List.of("PENDING", "ACTIVE", "REJECTED", "LOCKED").contains(status)) throw bad("상태 값이 올바르지 않습니다.");
        List<String> roles = input.roles() == null ? List.of() : input.roles().stream().map(String::trim).filter(role -> !role.isEmpty()).distinct().toList();
        if (username.equals(me.getName()) && (!status.equals("ACTIVE") || !roles.contains(SystemAccessService.ADMIN_ROLE)))
            throw conflict("자기 자신의 관리자 역할이나 사용 상태는 바꿀 수 없습니다.");
        String name = text(input.displayName());
        if (name.isEmpty() || name.length() > 200) throw bad("이름을 입력하세요.");
        int updated = jdbc.update("""
            UPDATE workspace_users SET display_name = ?, email = NULLIF(?, ''), status = ?,
                   approved_by = CASE WHEN status = 'PENDING' AND ? = 'ACTIVE' THEN ? ELSE approved_by END,
                   approved_at = CASE WHEN status = 'PENDING' AND ? = 'ACTIVE' THEN CURRENT_TIMESTAMP ELSE approved_at END
            WHERE username = ?""", name, text(input.email()), status, status, me.getName(), status, username);
        if (updated == 0) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.");
        jdbc.update("DELETE FROM sys_user_roles WHERE username = ?", username);
        for (String role : roles) {
            if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_roles WHERE role_code = ?", Integer.class, role) == 0) throw bad("없는 역할입니다: " + role);
            jdbc.update("INSERT INTO sys_user_roles (username, role_code) VALUES (?, ?)", username, role);
        }
        return Map.of("username", username);
    }

    @PostMapping("/users/{username}/password")
    public Map<String, Object> resetPassword(@PathVariable String username, @RequestBody PasswordInput input) {
        String password = input.password() == null ? "" : input.password();
        policy.check(password);
        if (jdbc.update("UPDATE workspace_users SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP WHERE username = ?", encoder.encode(password), username) == 0)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다.");
        return Map.of("username", username);
    }

    // ---- roles
    public record RoleInput(String roleCode, String roleName, String description, Boolean enabled) {}

    @GetMapping("/roles")
    public List<Map<String, Object>> roles() {
        return jdbc.queryForList("""
            SELECT r.role_code AS "roleCode", r.role_name AS "roleName", COALESCE(r.description, '') AS description, r.enabled,
                   (SELECT COUNT(*) FROM sys_user_roles ur WHERE ur.role_code = r.role_code) AS users
            FROM sys_roles r ORDER BY r.role_code""");
    }

    @PostMapping("/roles")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> createRole(@RequestBody RoleInput input) {
        String roleCode = text(input.roleCode()).toUpperCase();
        code(roleCode, "역할 코드");
        if (text(input.roleName()).isEmpty()) throw bad("역할 이름을 입력하세요.");
        if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_roles WHERE role_code = ?", Integer.class, roleCode) > 0) throw conflict("이미 있는 역할 코드입니다.");
        jdbc.update("INSERT INTO sys_roles (role_code, role_name, description, enabled) VALUES (?, ?, ?, ?)",
                roleCode, text(input.roleName()), text(input.description()), input.enabled() == null || input.enabled());
        return Map.of("roleCode", roleCode);
    }

    @PutMapping("/roles/{roleCode}")
    public Map<String, Object> saveRole(@PathVariable String roleCode, @RequestBody RoleInput input) {
        if (text(input.roleName()).isEmpty()) throw bad("역할 이름을 입력하세요.");
        boolean enabled = input.enabled() == null || input.enabled();
        if (roleCode.equals(SystemAccessService.ADMIN_ROLE) && !enabled) throw conflict("관리자 역할은 사용 중지할 수 없습니다.");
        if (jdbc.update("UPDATE sys_roles SET role_name = ?, description = ?, enabled = ? WHERE role_code = ?",
                text(input.roleName()), text(input.description()), enabled, roleCode) == 0) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "역할을 찾을 수 없습니다.");
        return Map.of("roleCode", roleCode);
    }

    @DeleteMapping("/roles/{roleCode}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteRole(@PathVariable String roleCode) {
        if (roleCode.equals(SystemAccessService.ADMIN_ROLE)) throw conflict("관리자 역할은 삭제할 수 없습니다.");
        if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_user_roles WHERE role_code = ?", Integer.class, roleCode) > 0)
            throw conflict("이 역할을 가진 사용자가 있어 삭제할 수 없습니다.");
        jdbc.update("DELETE FROM sys_roles WHERE role_code = ?", roleCode);
    }

    // ---- modules
    public record ModuleInput(String moduleCode, String moduleName, String icon, Integer sortOrder, Boolean enabled) {}

    @GetMapping("/modules")
    public List<Map<String, Object>> modules() {
        return jdbc.queryForList("""
            SELECT m.module_code AS "moduleCode", m.module_name AS "moduleName", COALESCE(m.icon, '') AS icon, m.sort_order AS "sortOrder", m.enabled,
                   (SELECT COUNT(*) FROM sys_menus mn WHERE mn.module_code = m.module_code) AS menus
            FROM sys_modules m ORDER BY m.sort_order, m.module_code""");
    }

    @PostMapping("/modules")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> createModule(@RequestBody ModuleInput input) {
        String moduleCode = text(input.moduleCode()).toUpperCase();
        code(moduleCode, "모듈 코드");
        if (text(input.moduleName()).isEmpty()) throw bad("모듈 이름을 입력하세요.");
        if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_modules WHERE module_code = ?", Integer.class, moduleCode) > 0) throw conflict("이미 있는 모듈 코드입니다.");
        jdbc.update("INSERT INTO sys_modules (module_code, system_code, module_name, icon, sort_order, enabled) VALUES (?, (SELECT system_code FROM sys_systems ORDER BY sort_order LIMIT 1), ?, NULLIF(?, ''), ?, ?)",
                moduleCode, text(input.moduleName()), icon(input.icon()), input.sortOrder() == null ? 10 : input.sortOrder(), input.enabled() == null || input.enabled());
        return Map.of("moduleCode", moduleCode);
    }

    @PutMapping("/modules/{moduleCode}")
    public Map<String, Object> saveModule(@PathVariable String moduleCode, @RequestBody ModuleInput input) {
        if (text(input.moduleName()).isEmpty()) throw bad("모듈 이름을 입력하세요.");
        boolean enabled = input.enabled() == null || input.enabled();
        if (moduleCode.equals("SYSTEM") && !enabled) throw conflict("시스템 모듈은 사용 중지할 수 없습니다.");
        if (jdbc.update("UPDATE sys_modules SET module_name = ?, icon = NULLIF(?, ''), sort_order = ?, enabled = ? WHERE module_code = ?",
                text(input.moduleName()), icon(input.icon()), input.sortOrder() == null ? 10 : input.sortOrder(), enabled, moduleCode) == 0)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "모듈을 찾을 수 없습니다.");
        return Map.of("moduleCode", moduleCode);
    }

    @DeleteMapping("/modules/{moduleCode}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteModule(@PathVariable String moduleCode) {
        if (moduleCode.equals("SYSTEM")) throw conflict("시스템 모듈은 삭제할 수 없습니다.");
        if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_menus WHERE module_code = ?", Integer.class, moduleCode) > 0)
            throw conflict("모듈에 메뉴가 있어 삭제할 수 없습니다. 메뉴를 먼저 옮기거나 지우세요.");
        jdbc.update("DELETE FROM sys_modules WHERE module_code = ?", moduleCode);
    }

    // ---- menus (메뉴 tree) and programs
    public record MenuInput(String moduleCode, Long parentId, String menuType, String programCode, String menuName, Integer sortOrder, String icon) {}

    @GetMapping("/programs")
    public List<Map<String, Object>> programs() {
        return jdbc.queryForList("""
            SELECT p.program_code AS "programCode", p.program_name AS "programName", p.api_paths AS "apiPaths", p.system_program AS "systemProgram",
                   COALESCE((SELECT m.module_name FROM sys_menus mn JOIN sys_modules m ON m.module_code = mn.module_code WHERE mn.program_code = p.program_code), '') AS "moduleName"
            FROM sys_programs p ORDER BY p.program_code""");
    }

    @GetMapping("/menus")
    public List<Map<String, Object>> menus(@RequestParam(required = false) String module) {
        return jdbc.queryForList("""
            SELECT mn.menu_id AS "menuId", mn.module_code AS "moduleCode", mn.parent_id AS "parentId", mn.menu_type AS "menuType",
                   COALESCE(mn.program_code, '') AS "programCode", mn.menu_name AS "menuName", mn.sort_order AS "sortOrder", COALESCE(mn.icon, '') AS icon
            FROM sys_menus mn WHERE (CAST(? AS VARCHAR) IS NULL OR mn.module_code = ?) ORDER BY mn.sort_order, mn.menu_name""", module, module);
    }

    @PostMapping("/menus")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> createMenu(@RequestBody MenuInput input) {
        String type = "FOLDER".equals(input.menuType()) ? "FOLDER" : "PROGRAM";
        String program = type.equals("PROGRAM") ? text(input.programCode()) : null;
        if (type.equals("PROGRAM")) {
            if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_programs WHERE program_code = ?", Integer.class, program) == 0) throw bad("없는 프로그램입니다.");
            if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_menus WHERE program_code = ?", Integer.class, program) > 0) throw conflict("이미 메뉴에 배치된 프로그램입니다.");
        }
        String name = text(input.menuName());
        if (name.isEmpty() && type.equals("PROGRAM")) name = jdbc.queryForObject("SELECT program_name FROM sys_programs WHERE program_code = ?", String.class, program);
        if (name.isEmpty()) throw bad("메뉴 이름을 입력하세요.");
        checkParent(input.moduleCode(), input.parentId(), null);
        Long id = jdbc.queryForObject("INSERT INTO sys_menus (module_code, parent_id, menu_type, program_code, menu_name, sort_order, icon) VALUES (?, ?, ?, ?, ?, ?, NULLIF(?, '')) RETURNING menu_id",
                Long.class, input.moduleCode(), input.parentId(), type, program, name, input.sortOrder() == null ? nextOrder(input.moduleCode(), input.parentId()) : input.sortOrder(), icon(input.icon()));
        return Map.of("menuId", id);
    }

    @PutMapping("/menus/{menuId}")
    public Map<String, Object> saveMenu(@PathVariable long menuId, @RequestBody MenuInput input) {
        String name = text(input.menuName());
        if (name.isEmpty()) throw bad("메뉴 이름을 입력하세요.");
        checkParent(input.moduleCode(), input.parentId(), menuId);
        if (jdbc.update("UPDATE sys_menus SET module_code = ?, parent_id = ?, menu_name = ?, sort_order = ?, icon = NULLIF(?, '') WHERE menu_id = ?",
                input.moduleCode(), input.parentId(), name, input.sortOrder() == null ? 0 : input.sortOrder(), icon(input.icon()), menuId) == 0)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "메뉴를 찾을 수 없습니다.");
        // Children follow their folder into another module.
        jdbc.update("""
            WITH RECURSIVE below AS (SELECT menu_id FROM sys_menus WHERE parent_id = ? UNION ALL
                                     SELECT c.menu_id FROM sys_menus c JOIN below b ON c.parent_id = b.menu_id)
            UPDATE sys_menus SET module_code = ? WHERE menu_id IN (SELECT menu_id FROM below)""", menuId, input.moduleCode());
        return Map.of("menuId", menuId);
    }

    @DeleteMapping("/menus/{menuId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteMenu(@PathVariable long menuId) {
        // Removing a folder removes what is inside; the programs themselves stay and become unplaced again.
        jdbc.update("DELETE FROM sys_menus WHERE menu_id = ?", menuId);
    }

    private int nextOrder(String module, Long parent) {
        return jdbc.queryForObject("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM sys_menus WHERE module_code = ? AND parent_id IS NOT DISTINCT FROM ?", Integer.class, module, parent);
    }

    private void checkParent(String module, Long parent, Long self) {
        if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_modules WHERE module_code = ?", Integer.class, module) == 0) throw bad("없는 모듈입니다.");
        if (parent == null) return;
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT module_code, menu_type FROM sys_menus WHERE menu_id = ?", parent);
        if (rows.isEmpty() || !"FOLDER".equals(rows.get(0).get("menu_type"))) throw bad("상위는 폴더여야 합니다.");
        if (!module.equals(rows.get(0).get("module_code"))) throw bad("상위 폴더가 다른 모듈에 있습니다.");
        if (self != null) {
            Integer inside = jdbc.queryForObject("""
                WITH RECURSIVE below AS (SELECT menu_id FROM sys_menus WHERE menu_id = ? UNION ALL
                                         SELECT c.menu_id FROM sys_menus c JOIN below b ON c.parent_id = b.menu_id)
                SELECT COUNT(*) FROM below WHERE menu_id = ?""", Integer.class, self, parent);
            if (inside != null && inside > 0) throw bad("폴더를 자기 자신이나 하위 폴더 안으로 옮길 수 없습니다.");
        }
    }

    // ---- menu permission and program permission per role
    public record RoleMenusInput(List<Long> menuIds) {}
    public record ProgramGrant(String programCode, boolean query, boolean create, boolean save, boolean delete, boolean print) {}
    public record RoleProgramsInput(List<ProgramGrant> programs) {}

    @GetMapping("/roles/{roleCode}/menus")
    public List<Long> roleMenus(@PathVariable String roleCode) {
        return jdbc.queryForList("SELECT menu_id FROM sys_role_menus WHERE role_code = ? ORDER BY menu_id", Long.class, roleCode);
    }

    /** Menu permission. Granting a program menu also grants 조회 in that program unless a program permission exists. */
    @PutMapping("/roles/{roleCode}/menus")
    @Transactional
    public Map<String, Object> saveRoleMenus(@PathVariable String roleCode, @RequestBody RoleMenusInput input) {
        jdbc.update("DELETE FROM sys_role_menus WHERE role_code = ?", roleCode);
        for (Long id : input.menuIds() == null ? List.<Long>of() : input.menuIds().stream().distinct().toList())
            jdbc.update("INSERT INTO sys_role_menus (role_code, menu_id) SELECT ?, menu_id FROM sys_menus WHERE menu_id = ? AND menu_type = 'PROGRAM'", roleCode, id);
        jdbc.update("""
            INSERT INTO sys_role_programs (role_code, program_code, can_query)
            SELECT rm.role_code, mn.program_code, TRUE FROM sys_role_menus rm JOIN sys_menus mn ON mn.menu_id = rm.menu_id
            WHERE rm.role_code = ? ON CONFLICT (role_code, program_code) DO NOTHING""", roleCode);
        return Map.of("roleCode", roleCode);
    }

    @GetMapping("/roles/{roleCode}/programs")
    public List<Map<String, Object>> rolePrograms(@PathVariable String roleCode) {
        return jdbc.queryForList("""
            SELECT p.program_code AS "programCode", p.program_name AS "programName",
                   COALESCE(rp.can_query, FALSE) AS query, COALESCE(rp.can_create, FALSE) AS "create", COALESCE(rp.can_save, FALSE) AS save,
                   COALESCE(rp.can_delete, FALSE) AS "delete", COALESCE(rp.can_print, FALSE) AS print,
                   EXISTS (SELECT 1 FROM sys_role_menus rm JOIN sys_menus mn ON mn.menu_id = rm.menu_id
                           WHERE rm.role_code = ? AND mn.program_code = p.program_code) AS "inMenu"
            FROM sys_programs p LEFT JOIN sys_role_programs rp ON rp.program_code = p.program_code AND rp.role_code = ?
            ORDER BY p.program_code""", roleCode, roleCode);
    }

    @PutMapping("/roles/{roleCode}/programs")
    @Transactional
    public Map<String, Object> saveRolePrograms(@PathVariable String roleCode, @RequestBody RoleProgramsInput input) {
        jdbc.update("DELETE FROM sys_role_programs WHERE role_code = ?", roleCode);
        for (ProgramGrant grant : input.programs() == null ? List.<ProgramGrant>of() : input.programs())
            if (grant.query() || grant.create() || grant.save() || grant.delete() || grant.print())
                jdbc.update("INSERT INTO sys_role_programs (role_code, program_code, can_query, can_create, can_save, can_delete, can_print) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        roleCode, grant.programCode(), grant.query(), grant.create(), grant.save(), grant.delete(), grant.print());
        return Map.of("roleCode", roleCode);
    }
}
