package com.example.localinventory.framework.system;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AccessLogController {
    private final JdbcTemplate jdbc;
    private final AccessLog log;
    public AccessLogController(JdbcTemplate jdbc, AccessLog log) { this.jdbc = jdbc; this.log = log; }

    public record Usage(String programCode) {}

    /** The app reports each program a user opens. */
    @PostMapping("/api/auth/usage")
    public Map<String, Object> usage(@RequestBody Usage usage, Authentication authentication) {
        if (usage.programCode() != null && usage.programCode().matches("[A-Za-z0-9_.-]{1,100}")) log.record(authentication.getName(), "PROGRAM_OPEN", usage.programCode(), "");
        return Map.of("recorded", true);
    }

    /** The programs the signed-in user opened most recently (newest first, each once), for the home page. */
    @GetMapping("/api/auth/recent-programs")
    public List<Map<String, Object>> recent(Authentication authentication) {
        return jdbc.queryForList("SELECT program_code AS \"programCode\", MAX(occurred_at) AS \"openedAt\" FROM sys_access_logs "
                + "WHERE username = ? AND event = 'PROGRAM_OPEN' AND program_code IS NOT NULL GROUP BY program_code ORDER BY MAX(occurred_at) DESC LIMIT 12", authentication.getName());
    }

    /** Administrators read the log (newest first). from/to are dates (yyyy-MM-dd). */
    @GetMapping("/api/system/access-logs")
    public List<Map<String, Object>> list(@RequestParam(defaultValue = "") String username, @RequestParam(defaultValue = "") String event,
            @RequestParam(defaultValue = "") String from, @RequestParam(defaultValue = "") String to, @RequestParam(defaultValue = "500") int limit) {
        StringBuilder sql = new StringBuilder("SELECT l.id, l.occurred_at AS \"occurredAt\", l.username, COALESCE(u.display_name, '') AS \"displayName\", l.event, "
                + "COALESCE(l.program_code, '') AS \"programCode\", COALESCE(p.program_name, '') AS \"programName\", l.ip, l.detail "
                + "FROM sys_access_logs l LEFT JOIN workspace_users u ON u.username = l.username LEFT JOIN sys_programs p ON p.program_code = l.program_code WHERE 1 = 1");
        List<Object> args = new ArrayList<>();
        if (!username.isBlank()) { sql.append(" AND LOWER(l.username) LIKE ?"); args.add("%" + username.trim().toLowerCase() + "%"); }
        if (!event.isBlank()) { sql.append(" AND l.event = ?"); args.add(event.trim()); }
        if (from.matches("\\d{4}-\\d{2}-\\d{2}")) { sql.append(" AND l.occurred_at >= CAST(? AS DATE)"); args.add(from); }
        if (to.matches("\\d{4}-\\d{2}-\\d{2}")) { sql.append(" AND l.occurred_at < CAST(? AS DATE) + INTERVAL '1 day'"); args.add(to); }
        sql.append(" ORDER BY l.occurred_at DESC, l.id DESC LIMIT ?");
        args.add(Math.max(1, Math.min(2000, limit)));
        return jdbc.queryForList(sql.toString(), args.toArray());
    }
}
