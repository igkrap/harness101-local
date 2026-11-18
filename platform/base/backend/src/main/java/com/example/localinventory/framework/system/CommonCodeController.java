package com.example.localinventory.framework.system;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** Common codes: any signed-in user reads the codes in use; administrators keep the groups and codes. */
@RestController
public class CommonCodeController {
    private static final String CODE = "[A-Za-z0-9_-]{1,50}";
    private final JdbcTemplate jdbc;
    public CommonCodeController(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public record GroupInput(String groupCode, String groupName, String description, Boolean enabled) {}
    public record CodeInput(String code, String codeName, Integer sortOrder, Boolean enabled) {}

    /** groups=A,B -> { "A": [{code, name}], "B": [...] }, enabled codes in order. Unknown groups give an empty list. */
    @GetMapping("/api/auth/codes")
    public Map<String, List<Map<String, Object>>> codes(@RequestParam String groups) {
        Map<String, List<Map<String, Object>>> result = new LinkedHashMap<>();
        for (String group : groups.split(",")) {
            String key = group.trim();
            if (key.isEmpty() || result.containsKey(key)) continue;
            result.put(key, jdbc.queryForList("SELECT c.code, c.code_name AS name FROM sys_codes c JOIN sys_code_groups g ON g.group_code = c.group_code "
                    + "WHERE c.group_code = ? AND c.enabled AND g.enabled ORDER BY c.sort_order, c.code", key));
        }
        return result;
    }

    @GetMapping("/api/system/code-groups")
    public List<Map<String, Object>> groups() {
        return jdbc.queryForList("SELECT g.group_code AS \"groupCode\", g.group_name AS \"groupName\", g.description, g.enabled, "
                + "(SELECT COUNT(*) FROM sys_codes c WHERE c.group_code = g.group_code) AS codes FROM sys_code_groups g ORDER BY g.group_code");
    }

    @PostMapping("/api/system/code-groups")
    public List<Map<String, Object>> addGroup(@RequestBody GroupInput input) {
        String code = input.groupCode() == null ? "" : input.groupCode().trim().toUpperCase();
        if (!code.matches(CODE)) throw bad("그룹 코드는 영문·숫자·_- 1~50자여야 합니다.");
        String name = name(input.groupName(), "그룹 이름");
        if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_code_groups WHERE group_code = ?", Integer.class, code) > 0) throw new ResponseStatusException(HttpStatus.CONFLICT, "이미 있는 그룹 코드입니다.");
        jdbc.update("INSERT INTO sys_code_groups (group_code, group_name, description) VALUES (?, ?, ?)", code, name, text(input.description()));
        return groups();
    }

    @PutMapping("/api/system/code-groups/{group}")
    public List<Map<String, Object>> updateGroup(@PathVariable String group, @RequestBody GroupInput input) {
        if (jdbc.update("UPDATE sys_code_groups SET group_name = ?, description = ?, enabled = ? WHERE group_code = ?",
                name(input.groupName(), "그룹 이름"), text(input.description()), input.enabled() == null || input.enabled(), group) == 0) throw missing();
        return groups();
    }

    @DeleteMapping("/api/system/code-groups/{group}")
    public List<Map<String, Object>> deleteGroup(@PathVariable String group) {
        if (jdbc.update("DELETE FROM sys_code_groups WHERE group_code = ?", group) == 0) throw missing();
        return groups();
    }

    @GetMapping("/api/system/code-groups/{group}/codes")
    public List<Map<String, Object>> list(@PathVariable String group) {
        return jdbc.queryForList("SELECT code, code_name AS \"codeName\", sort_order AS \"sortOrder\", enabled FROM sys_codes WHERE group_code = ? ORDER BY sort_order, code", group);
    }

    @PostMapping("/api/system/code-groups/{group}/codes")
    public List<Map<String, Object>> addCode(@PathVariable String group, @RequestBody CodeInput input) {
        if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_code_groups WHERE group_code = ?", Integer.class, group) == 0) throw missing();
        String code = input.code() == null ? "" : input.code().trim();
        if (!code.matches(CODE)) throw bad("코드는 영문·숫자·_- 1~50자여야 합니다.");
        if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_codes WHERE group_code = ? AND code = ?", Integer.class, group, code) > 0) throw new ResponseStatusException(HttpStatus.CONFLICT, "이미 있는 코드입니다.");
        jdbc.update("INSERT INTO sys_codes (group_code, code, code_name, sort_order, enabled) VALUES (?, ?, ?, ?, ?)", group, code, name(input.codeName(), "코드 이름"),
                input.sortOrder() == null ? 0 : input.sortOrder(), input.enabled() == null || input.enabled());
        return list(group);
    }

    @PutMapping("/api/system/code-groups/{group}/codes/{code}")
    public List<Map<String, Object>> updateCode(@PathVariable String group, @PathVariable String code, @RequestBody CodeInput input) {
        if (jdbc.update("UPDATE sys_codes SET code_name = ?, sort_order = ?, enabled = ? WHERE group_code = ? AND code = ?", name(input.codeName(), "코드 이름"),
                input.sortOrder() == null ? 0 : input.sortOrder(), input.enabled() == null || input.enabled(), group, code) == 0) throw missing();
        return list(group);
    }

    @DeleteMapping("/api/system/code-groups/{group}/codes/{code}")
    public List<Map<String, Object>> deleteCode(@PathVariable String group, @PathVariable String code) {
        if (jdbc.update("DELETE FROM sys_codes WHERE group_code = ? AND code = ?", group, code) == 0) throw missing();
        return list(group);
    }

    private static String name(String value, String label) {
        String text = value == null ? "" : value.trim();
        if (text.isEmpty() || text.length() > 200) throw bad(label + "을 입력하세요.");
        return text;
    }
    private static String text(String value) { String text = value == null ? "" : value.trim(); return text.length() > 500 ? text.substring(0, 500) : text; }
    private static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST, message); }
    private static ResponseStatusException missing() { return new ResponseStatusException(HttpStatus.NOT_FOUND, "대상을 찾지 못했습니다."); }
}
