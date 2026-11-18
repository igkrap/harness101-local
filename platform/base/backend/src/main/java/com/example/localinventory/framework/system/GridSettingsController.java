package com.example.localinventory.framework.system;

import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** How a person has arranged a table of a screen (their own only): which columns are hidden, their order and widths. Kept so the table opens the same way next time. */
@RestController
public class GridSettingsController {
    private final JdbcTemplate jdbc;
    private final tools.jackson.databind.ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    public GridSettingsController(JdbcTemplate jdbc) { this.jdbc = jdbc; }
    public record Settings(List<String> order, List<String> hidden, Map<String, Integer> widths) {}
    public record SaveRequest(String key, Settings settings) {}

    @GetMapping("/api/auth/grids")
    public Settings read(@RequestParam String key, Authentication authentication) {
        List<String> found = jdbc.queryForList("SELECT settings FROM sys_user_grids WHERE username = ? AND grid_key = ?", String.class, authentication.getName(), key);
        return found.isEmpty() ? new Settings(List.of(), List.of(), Map.of()) : mapper.readValue(found.get(0), Settings.class);
    }

    @PutMapping("/api/auth/grids")
    public Settings save(@RequestBody SaveRequest request, Authentication authentication) {
        Settings given = request.settings();
        if (request.key() == null || request.key().isBlank() || request.key().length() > 160 || given == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "표 설정을 저장하지 못했습니다.");
        Settings kept = new Settings(given.order() == null ? List.of() : given.order(), given.hidden() == null ? List.of() : given.hidden(), given.widths() == null ? Map.of() : given.widths());
        if (kept.order().size() > 200 || kept.hidden().size() > 200 || kept.widths().size() > 200) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "표 설정을 저장하지 못했습니다.");
        jdbc.update("INSERT INTO sys_user_grids (username, grid_key, settings) VALUES (?, ?, ?) ON CONFLICT (username, grid_key) DO UPDATE SET settings = EXCLUDED.settings, updated_at = CURRENT_TIMESTAMP",
                authentication.getName(), request.key(), mapper.writeValueAsString(kept));
        return kept;
    }

    /** Back to the table as the screen draws it. */
    @DeleteMapping("/api/auth/grids")
    public void reset(@RequestParam String key, Authentication authentication) {
        jdbc.update("DELETE FROM sys_user_grids WHERE username = ? AND grid_key = ?", authentication.getName(), key);
    }
}
